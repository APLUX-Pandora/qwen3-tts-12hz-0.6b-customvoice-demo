#!/usr/bin/env python3
"""Web demo: play the built-in sample of a language or type any text, and hear it while it is being generated.

GET  /     -> index.html; /static/<file> -> logo and icon
POST /tts  {"text" (any length), "speaker", "language", "seed"}
           -> binary stream of frames: 1 byte type + uint32 LE length + payload
           type 0: audio chunk, int16 LE mono 24 kHz; type 1: JSON stats (end); type 2: error text;
           type 3: JSON progress ({"event": "start", "id", "segments"} / {"event": "segment", "index", ...})
GET  /samples -> {language: sample text}: the built-in texts of the page's sample box (samples/<language>.txt)
GET  /wav/<id> -> the whole utterance as a wav, written by the server while it streams (the last KEEP_WAVS are kept)
Any length: the text is split into segments (demo/longtext.py, one utterance each) and streamed as one audio stream;
generation stays at most AHEAD_S of audio ahead of playback. One engine (one NPU): requests are served one at a time.
If the browser disconnects, no new segment is started and the running one is cancelled (q3t_cancel).
usage: demo/run.sh [--port 8765] [--host 0.0.0.0]   (env: QWEN3_TTS_MODELS, QWEN3_TTS_LIB)
"""
import argparse
import glob
import json
import os
import signal

# This CLI owns its signal policy. Block before NumPy/vendor imports create
# threads; only the main thread restores the caller mask after model loading.
_STARTUP_SIGNAL_MASK = (signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGINT, signal.SIGTERM))
                        if __name__ == "__main__" else None)
from pathlib import Path
import struct
import sys
import threading
import time
import uuid

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tts import TTS, cpu_placement  # noqa: E402
from runtime_logging import sanitize  # noqa: E402

SPEAKERS = ["vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee"]
LANGUAGES = ["chinese", "english", "japanese", "korean", "german", "french", "russian", "portuguese", "spanish",
             "italian"]
AHEAD_S = 30.0                                          # generation runs at most this much audio ahead of playback
KEEP_WAVS = 3
OUT = os.path.join(HERE, "out")


def frame(t, payload):
    return struct.pack("<BI", t, len(payload)) + payload


def serve(web, factory, stopping, lock, get_active_stop, assign_tts, host, port):
    """Wait for request threads before releasing the shared model owner."""
    from werkzeug.serving import ThreadedWSGIServer, WSGIRequestHandler

    class RequestHandler(WSGIRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

    class Server(ThreadedWSGIServer):
        daemon_threads = False
        block_on_close = True

    def stop(_signum, _frame):
        # Do not raise during ctypes initialization: the returned handle must first get an owner.
        stopping.set()

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    tts = server = watcher = None
    finished = threading.Event()

    def shutdown():
        while not finished.wait(0.05):
            if stopping.is_set():
                event = get_active_stop()
                if event is not None:
                    event.set()
                tts.cancel()
                server.shutdown()
                return

    try:
        print(json.dumps({"tts_loading": True}), flush=True)
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, previous)
        try:
            tts = factory()
            assign_tts(tts)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK,
                                   _STARTUP_SIGNAL_MASK if _STARTUP_SIGNAL_MASK is not None else mask)
        print(json.dumps({"tts_init_s": round(tts.init_s, 2)}), flush=True)
        if stopping.is_set():
            return
        server = Server(host, port, web, handler=RequestHandler)
        watcher = threading.Thread(target=shutdown, name="tts-shutdown")
        watcher.start()
        server.serve_forever(poll_interval=0.1)
    finally:
        stopping.set()
        if server is not None:
            server.server_close()
        finished.set()
        if watcher is not None:
            watcher.join()
        if tts is not None:
            # server_close joins handlers, including any native inference in progress.
            with lock:
                tts.close()
            print(json.dumps({"tts_closed": True}), flush=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--models", default=os.environ.get("QWEN3_TTS_MODELS"),
                    help="model package directory containing models.json")
    ap.add_argument("--cpu-affinity", type=cpu_placement, default="default")
    a = ap.parse_args()
    from flask import Flask, Response, request, send_from_directory
    lock = threading.Lock()
    stopping = threading.Event()
    active_stop = None
    tts = None
    web = Flask(__name__)

    @web.get("/")
    def index():
        return send_from_directory(HERE, "index.html")

    @web.get("/static/<name>")
    def static_file(name):
        return send_from_directory(os.path.join(HERE, "static"), name)

    samples = {os.path.basename(p)[:-4]: Path(p).read_text(encoding="utf-8").strip()
               for p in sorted(glob.glob(os.path.join(HERE, "samples", "*.txt")))}

    @web.get("/samples")
    def get_samples():
        return samples

    @web.get("/wav/<rid>")
    def wav(rid):
        if not rid.isalnum():
            return "bad id", 400
        return send_from_directory(OUT, rid + ".wav", as_attachment=True, download_name="qwen3_tts.wav")

    @web.post("/tts")
    def synth():
        if stopping.is_set():
            return {"error": "Service is stopping."}, 503
        req = request.get_json(force=True, silent=True)
        if not isinstance(req, dict):
            return {"error": "Expected a JSON object."}, 400
        if not isinstance(req.get("text", ""), str):
            return {"error": "text must be a string."}, 400
        text = req.get("text", "").strip()
        for field in ("speaker", "language"):
            if field in req and not isinstance(req[field], str):
                return {"error": field + " must be a string."}, 400
        speaker = req.get("speaker", "aiden")
        if speaker not in SPEAKERS:
            return {"error": "Unsupported speaker."}, 400
        language = req.get("language", "english")
        if language not in LANGUAGES:
            return {"error": "Unsupported text language; choose an explicit supported language."}, 400
        seed = req.get("seed", 1)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
            return {"error": "seed must be an integer in 0..2**32-1."}, 400

        def gen():
            nonlocal active_stop
            if not text:
                yield frame(2, "empty text".encode())
                return
            import soundfile as sf
            while not lock.acquire(timeout=0.1):
                if stopping.is_set():
                    return
            try:
                if stopping.is_set():
                    return
                t0, rid, stop = time.time(), uuid.uuid4().hex[:12], threading.Event()
                active_stop = stop
                if stopping.is_set():
                    stop.set()
                    return
                os.makedirs(OUT, exist_ok=True)
                old = sorted(glob.glob(os.path.join(OUT, "*.wav")), key=os.path.getmtime)
                for f_old in old[:-(KEEP_WAVS - 1) or None]:
                    os.remove(f_old)
                it = tts.speak_long(text, speaker, language, seed, ahead_s=AHEAD_S, stop=stop)
                f = sf.SoundFile(os.path.join(OUT, rid + ".wav"), "w", 24000, 1, "PCM_16")
                try:
                    for wav, st in it:
                        if wav is not None:
                            pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2")
                            f.write(pcm)
                            yield frame(0, pcm.tobytes())
                        elif st["event"] == "done":
                            st.update({"id": rid, "chars": len(text), "speaker": speaker, "language": language,
                                       "seed": seed, "server_s": round(time.time() - t0, 3)})
                            print(json.dumps(st, ensure_ascii=False), flush=True)
                            yield frame(1, json.dumps(st, ensure_ascii=False).encode())
                        else:
                            if st["event"] == "start":
                                st["id"] = rid
                            st.pop("text", None)
                            yield frame(3, json.dumps(st, ensure_ascii=False).encode())
                except GeneratorExit:                    # client went away: no new segment, abort the running query
                    stop.set()
                    tts.cancel()
                    for _ in it:
                        pass
                    print(json.dumps({"client_disconnected": text[:20], "id": rid}, ensure_ascii=False), flush=True)
                    raise
                except Exception as e:                   # noqa: BLE001
                    message = sanitize(str(e))
                    print(json.dumps({"error": message}), flush=True)
                    yield frame(2, message.encode())
                finally:
                    it.close()
                    f.close()
            finally:
                active_stop = None
                lock.release()

        return Response(gen(), mimetype="application/octet-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def assign_tts(value):
        nonlocal tts
        tts = value

    serve(web, lambda: TTS(a.models, cpu=a.cpu_affinity), stopping, lock,
          lambda: active_stop, assign_tts, a.host, a.port)


if __name__ == "__main__":
    from runtime_logging import entrypoint
    raise SystemExit(entrypoint(main, startup_signal_mask=_STARTUP_SIGNAL_MASK,
                                worker_stop_signal=signal.SIGTERM))
