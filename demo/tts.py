#!/usr/bin/env python3
"""Business layer of the TTS demo over the SDK (sdk/python/qwen3_tts.py): text normalization, streaming of one
utterance with latency / stall statistics, and long text as one continuous stream (longtext.py: segments, joining,
pauses, pacing). The explicit text language controls conditioning and text normalization.

usage: python3 demo/tts.py --text "Hello, this text to speech model runs entirely on the device." \
           --speaker ryan --language english [--out-dir out]
       python3 demo/tts.py --file long.txt [--ahead-s 30] --out-dir out   (any length: segments, longtext.py)
       python3 demo/tts.py --set texts.jsonl --out-dir out
           (jsonl: id, text, and optionally speaker, language)
Writes <out-dir>/<id>.wav (concatenated chunks) and <id>_info.json (first chunk latency, stalls, timing).
"""
import argparse
import json
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel, Runtime, TTSStateError
LANGUAGES = dict(zh="chinese", en="english", ja="japanese", ko="korean", de="german", fr="french", ru="russian", es="spanish", it="italian", pt="portuguese")
from text_norm import normalize  # noqa: E402

MODELS = os.environ.get("QWEN3_TTS_MODELS", os.path.join(ROOT, "models"))


STALL_S = 0.02                                          # a chunk later than this after the previous one ended is a gap


def playback_stats(ready):
    """ready: [(time since start, chunk duration)] -> first chunk, slack of every chunk (playback starting at the first
    chunk; negative = the chunk arrived after the previous one had finished playing)"""
    r0, play, slack = ready[0][0], ready[0][0], []
    for r, d in ready:
        slack.append(play - r)
        play = max(play, r) + d
    return r0, slack


def cpu_placement(value):
    """Parse the application's CLI option using the SDK's public validation."""
    from pandora_qwen3_tts_12hz_0_6b_customvoice import CpuOptions
    try:
        if value in ("default", "inherit"):
            return CpuOptions(affinity=value)
        if not value or any(not item.isascii() or not item.isdecimal() for item in value.split(",")):
            raise ValueError("use default, inherit, or comma-separated CPU IDs")
        return CpuOptions(affinity=[int(item) for item in value.split(",")])
    except (TypeError, ValueError) as exc:
        import argparse
        raise argparse.ArgumentTypeError(str(exc)) from exc


class TTS:
    def __init__(self, model_dir=MODELS, *, cpu=None):
        t0 = time.time()
        self._runtime = Runtime(cpu=cpu)
        try:
            self.engine = TTSModel.from_pretrained(MODELS if model_dir is None else model_dir, runtime=self._runtime)
        except BaseException:
            self._runtime.close()
            raise
        self._active_stream = None
        self._cancelled = threading.Event()
        self.sr = self.engine.sample_rate
        self.ctx_rows = self.engine.info["context_rows"]
        self.init_s = time.time() - t0

    def cancel(self):
        """May be called from another thread: closes the running stream; the iterating side ends normally."""
        stream = self._active_stream
        if stream is not None:
            self._cancelled.set()
            stream.close()

    def _stream_audio(self, text, speaker, language, seed, max_frames):
        codes = {name: code for code, name in LANGUAGES.items()}
        code = codes.get(language.lower(), language.lower())
        with self.engine.synthesize_stream(text, speaker=speaker, language=code,
                seed=seed, max_new_tokens=max_frames if max_frames > 0 else None) as stream:
            self._cancelled.clear()
            self._active_stream = stream
            try:
                while stream.finish_reason is None:
                    try:
                        chunk = next(stream)
                    except StopIteration:
                        break
                    except TTSStateError:
                        # cancel() closed the stream between two chunks: a normal early end.
                        if self._cancelled.is_set():
                            break
                        raise
                    yield chunk.audio
            finally:
                self._active_stream = None

    def speak(self, text, speaker="aiden", language="english", seed=1, max_frames=1000):
        """Generator of audio chunks (float32 24 kHz) of one utterance; last item (None, stats).
        Text normalization follows the explicit language."""
        t0 = time.time()
        text = normalize(text, language)
        ready = []
        for wav in self._stream_audio(text, speaker, language, seed, max_frames):
            ready.append((time.time() - t0, len(wav) / self.sr))
            yield wav, None
        st = self.engine.stats()
        if not ready:
            yield None, {"normalized_text": text, "text_language": language, "frames": 0, "audio_s": 0,
                         "end_reason": st["end_reason"]}
            return
        r0, slack = playback_stats(ready)
        audio = sum(d for _, d in ready)
        yield None, {"normalized_text": text, "text_language": language,
                     "truncated": st["end_reason"] in ("max_frames", "context"),
                     "frames": st["frames"], "first_chunk_s": round(r0, 3), "chunks": len(ready),
                     "audio_s": round(audio, 2), "stalls": sum(x < -STALL_S for x in slack),
                     "min_slack_s": round(min(slack), 3),
                     "total_s": round(ready[-1][0], 3), "rtf": round(ready[-1][0] / audio, 3)}

    def speak_long(self, text, speaker="aiden", language="english", seed=1, ahead_s=None, stop=None):
        """Any text length (longtext.py): one utterance per segment, one continuous audio stream.
        Generator of (float32 chunk, None); (None, {"event": "segment", ...}) after each segment; last (None, stats).
        ahead_s: do not start a segment while more than ahead_s of audio is ahead of playback (playback = wall time
        since the first chunk).
        stop (threading.Event): once set, no new segment is started; the caller also calls self.cancel() so the
        running segment ends after its current frame, and keeps iterating to collect the rest.
        Text normalization follows the explicit language."""
        # Validate the caller's seed before deriving any bounded per-segment value.
        # Preserve the SDK contract: invalid input is never silently wrapped.
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an integer")
        if not 0 <= seed <= 2**32 - 1:
            raise ValueError("seed must be in 0..2**32-1")
        from longtext import SR, Joiner, est_frames, split_text
        t0 = time.time()
        segs = split_text(text, language)
        joiner, ready, seg_stats = Joiner(), [], []
        state = {"first": None, "audio": 0.0}

        def emit(ws):
            for w in ws:
                if len(w):
                    now = time.time() - t0
                    state["first"] = now if state["first"] is None else state["first"]
                    ready.append((now, len(w) / SR))
                    state["audio"] += len(w) / SR
                    yield w, None

        yield None, {"event": "start", "segments": len(segs), "hanzi": sum(s["hanzi"] for s in segs),
                     "units": sum(s["units"] for s in segs), "text_language": language}
        for k, sg in enumerate(segs):
            while ahead_s and state["first"] is not None and not (stop and stop.is_set()) and \
                    state["audio"] - (time.time() - t0 - state["first"]) > ahead_s:
                time.sleep(0.05)
            if stop and stop.is_set():
                break
            est = est_frames(sg["text"], speaker, language)
            a0, ts = state["audio"], time.time()
            joiner.begin(trim_lead=k > 0)
            # max_frames 0: until the context is full (prefill rows + frames <= context rows)
            for w in self._stream_audio(sg["text"], speaker, language, (seed + k) % (2**32), 0):
                if stop and stop.is_set():
                    self.cancel()
                yield from emit(joiner.push(w))
            st = self.engine.stats()
            frames, rows = st["frames"], st["prefill_rows"]
            yield from emit(joiner.end(sg["pause"]))
            short = frames < 0.5 * est and not (stop and stop.is_set())
            max_frames = self.ctx_rows - rows
            st = {"event": "segment", "index": k, "segments": len(segs), "hanzi": sg["hanzi"], "units": sg["units"],
                  "text": sg["text"],
                  "audio_start_s": round(a0, 3), "audio_end_s": round(state["audio"], 3), "prefill_rows": rows,
                  "frames": frames, "est_frames": round(est), "max_frames": max_frames,
                  "context_used": round((rows + frames) / self.ctx_rows, 3), "gen_s": round(time.time() - ts, 2),
                  "flag": "short" if short else ("max_frames" if frames >= max_frames else
                                                ("long" if frames > 2 * est else ""))}
            seg_stats.append(st)
            yield None, st
        if not ready:
            yield None, {"event": "done", "segments": len(segs), "stopped": True, "audio_s": 0}
            return
        r0, slack = playback_stats(ready)
        audio = sum(d for _, d in ready)
        yield None, {"event": "done", "segments": len(segs), "stopped": bool(stop and stop.is_set()),
                     "segments_done": len(seg_stats), "hanzi": sum(s["hanzi"] for s in segs),
                     "frames": sum(s["frames"] for s in seg_stats), "first_chunk_s": round(r0, 3),
                     "audio_s": round(audio, 2), "stalls": sum(x < -STALL_S for x in slack),
                     "min_slack_s": round(min(slack), 3), "total_s": round(ready[-1][0], 3),
                     "rtf": round(ready[-1][0] / audio, 3),
                     "max_context_used": max(s["context_used"] for s in seg_stats),
                     "flags": [(s["index"], s["flag"]) for s in seg_stats if s["flag"]]}

    def close(self):
        self.engine.close()
        self._runtime.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="append")
    ap.add_argument("--set")
    ap.add_argument("--speaker", default="aiden")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-frames", type=int, default=1000, help="per utterance (80 ms each)")
    ap.add_argument("--language", default="english", help="explicit text language")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--file", help="long text file (any length): speak_long, one wav written while it is generated")
    ap.add_argument("--ahead-s", type=float, default=None, help="--file: throttle to this much audio ahead of playback")
    ap.add_argument("--cpu-affinity", type=cpu_placement, default="default")
    a = ap.parse_args()
    import soundfile as sf
    os.makedirs(a.out_dir, exist_ok=True)
    tts = TTS(cpu=a.cpu_affinity)
    print(json.dumps({"init_s": round(tts.init_s, 2)}), flush=True)
    if a.file:
        uid = os.path.splitext(os.path.basename(a.file))[0]
        segs = []
        with sf.SoundFile(os.path.join(a.out_dir, uid + ".wav"), "w", 24000, 1, "PCM_16") as f:
            for wav, st in tts.speak_long(open(a.file, encoding="utf-8").read(), a.speaker, a.language, a.seed,
                                          ahead_s=a.ahead_s):
                if wav is not None:
                    f.write(np.clip(wav, -1, 1))
                    continue
                print(json.dumps(st, ensure_ascii=False), flush=True)
                if st["event"] == "segment":
                    segs.append(st)
        st.update({"id": uid, "speaker": a.speaker, "seed": a.seed, "segment_stats": segs})
        json.dump(st, open(os.path.join(a.out_dir, uid + "_info.json"), "w"), indent=1, ensure_ascii=False)
        tts.close()
        return
    items = ([json.loads(l) for l in open(a.set, encoding="utf-8") if l.strip()] if a.set else
             [{"id": f"text{i:03d}", "text": x, "speaker": a.speaker} for i, x in enumerate(a.text or [])])
    for it in items:
        parts = []
        for wav, st in tts.speak(it["text"], it.get("speaker", a.speaker), it.get("language", a.language), a.seed,
                                 a.max_frames):
            if wav is None:
                break
            parts.append(wav)                           # a player would consume the chunk here
        sf.write(os.path.join(a.out_dir, it["id"] + ".wav"), np.concatenate(parts) if parts else np.zeros(0), 24000)
        st.update({"id": it["id"], "speaker": it.get("speaker", a.speaker), "seed": a.seed})
        json.dump(st, open(os.path.join(a.out_dir, it["id"] + "_info.json"), "w"), indent=1, ensure_ascii=False)
        print(json.dumps(st, ensure_ascii=False), flush=True)
    tts.close()


if __name__ == "__main__":
    main()
