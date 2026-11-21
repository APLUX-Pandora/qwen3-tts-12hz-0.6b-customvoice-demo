#!/usr/bin/env python3
"""Streaming playback: text of any length is generated chunk by chunk and every chunk goes to a player ("sink") as
soon as it exists, so the sound starts long before the whole text is done.

The sink is the part to replace in your own application (ALSA, PulseAudio, Bluetooth, a network stream, ...):
  browser  (default) a minimal player page served by this script (Python standard library only): open
           http://<board-ip>:8800/ on any computer on the network and press Play; works without audio hardware
           on the board
  aplay    the board's own audio output through `aplay` (headphones, HDMI, ...)
  none     no playback
Every run also writes the audio to a wav file (--out) and prints a live progress line: chunks received, audio
generated, and how far generation is ahead of real-time playback.

Long text goes through the demo's business layer (demo/tts.py: normalization, sentence segments, joints, pauses).
Ctrl+C stops the generation after the current native call (the wav keeps what was generated); with the browser sink,
closing the page does the same.

usage: python3 demo/players/stream_play.py "Hello, this text to speech model runs entirely on the device."
       python3 demo/players/stream_play.py --file examples/text/long_en.txt [--sink aplay] [--out long.wav]
       options: --speaker aiden --language english (explicit text language) --seed 1 --port 8800 --models DIR
"""
import argparse
import http.server
import os
import subprocess
import sys
import threading
import time

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, f"{ROOT}/demo")
from tts import LANGUAGES, TTS  # noqa: E402
from _lifecycle import ExampleInterrupted, managed_owner  # noqa: E402

SR = 24000


class AplaySink:
    """Plays 16-bit mono PCM on the board's default audio output; aplay's buffer paces the writes."""

    def __init__(self):
        self.p = subprocess.Popen(["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(SR), "-c", "1"],
                                  stdin=subprocess.PIPE)

    def write(self, pcm):
        self.p.stdin.write(pcm.tobytes())

    def close(self):
        try:
            self.p.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()
                self.p.wait()


class HttpSink:
    """Sends 16-bit mono PCM to the browser player as an HTTP chunked response."""

    def __init__(self, handler):
        self.h = handler

    def write(self, pcm):
        b = pcm.tobytes()
        self.h.wfile.write(b"%x\r\n%s\r\n" % (len(b), b))
        self.h.wfile.flush()

    def close(self):
        self.h.wfile.write(b"0\r\n\r\n")
        self.h.wfile.flush()


def speak(tts, a, sinks, stop, request=None):
    """Generate the text, send every chunk to the sinks and to the wav file, print the progress."""
    text = open(a.file, encoding="utf-8").read() if a.file else a.text
    t0, first, audio, chunks = time.time(), None, 0.0, 0
    with sf.SoundFile(a.out, "w", SR, 1, "PCM_16") as wav:
        for chunk, event in tts.speak_long(text, a.speaker, a.language, a.seed, stop=stop):
            if request is not None:
                request.check()
            if chunk is None:
                if event["event"] == "start":
                    print(f"{event['segments']} segment(s)")
                elif event["event"] == "done":
                    print(f"\n{a.out}: {event['audio_s']:.1f} s of audio, "
                          f"first chunk after {event['first_chunk_s']:.2f} s, "
                          f"playback gaps: {event['stalls']}{', stopped' if event['stopped'] else ''}")
                continue
            pcm = (np.clip(chunk, -1, 1) * 32767).astype("<i2")
            wav.write(pcm)
            for s in sinks:
                try:
                    s.write(pcm)
                except (BrokenPipeError, ConnectionResetError):        # the player went away: stop generating
                    stop.set()
                    tts.cancel()
            now = time.time() - t0
            first = now if first is None else first
            chunks += 1
            audio += len(chunk) / SR
            print(f"\r  chunks {chunks:4d} | audio {audio:7.1f} s | ahead of playback {audio - (now - first):6.1f} s",
                  end="", flush=True)


PAGE = b"""<!doctype html><html><head><meta charset="utf-8"><title>TTS player</title>
<style>body{font:15px system-ui,sans-serif;margin:40px}button{font:inherit;padding:8px 20px}</style></head>
<body><h3>Streaming player</h3><button id="play">Play</button> <span id="st"></span>
<script>
// Plays the 16-bit 24 kHz PCM stream of /stream while it arrives: every piece is scheduled right after the previous.
const st = document.getElementById("st");
document.getElementById("play").onclick = async () => {
  const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
  await ctx.resume();
  let next = 0, odd = null, audio = 0, gaps = 0;
  const reader = (await fetch("/stream")).body.getReader();
  st.textContent = "playing...";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    let bytes = value;
    if (odd) { bytes = new Uint8Array(odd.length + value.length); bytes.set(odd); bytes.set(value, odd.length); }
    const n = bytes.length >> 1;
    odd = bytes.length & 1 ? bytes.slice(-1) : null;
    if (!n) continue;
    const pcm = new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + 2 * n));
    const f = new Float32Array(n);
    for (let i = 0; i < n; i++) f[i] = pcm[i] / 32768;
    const buf = ctx.createBuffer(1, n, 24000); buf.copyToChannel(f, 0);
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(ctx.destination);
    if (next < ctx.currentTime) { if (next) gaps++; next = ctx.currentTime + 0.05; }
    src.start(next); next += buf.duration; audio += buf.duration;
    st.textContent = `received ${audio.toFixed(1)} s of audio, playback gaps: ${gaps}`;
  }
  st.textContent += " - done";
};
</script></body></html>"""


def serve(tts, a, request):
    lock, stop = threading.Lock(), threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(PAGE)))
                self.end_headers()
                self.wfile.write(PAGE)
            elif self.path == "/stream":
                if not lock.acquire(blocking=False):                  # one generation at a time
                    self.send_error(409, "busy")
                    return
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    sink = HttpSink(self)
                    stop.clear()
                    speak(tts, a, [sink], stop)
                    try:
                        sink.close()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                finally:
                    lock.release()
            else:
                self.send_error(404)

    class Server(http.server.ThreadingHTTPServer):
        daemon_threads = False
        block_on_close = True

    srv = Server(("0.0.0.0", a.port), Handler)
    finished = threading.Event()

    def shutdown():
        while not finished.wait(0.05):
            if request.signum is not None:
                stop.set()
                tts.cancel()
                srv.shutdown()
                return

    watcher = threading.Thread(target=shutdown, name="example-shutdown")
    print(f"player: open http://<board-ip>:{a.port}/ in a browser and press Play (Ctrl+C to quit)")
    try:
        watcher.start()
        srv.serve_forever(poll_interval=0.1)
    finally:                                                   # End a running generation before closing
        stop.set()
        tts.cancel()
        srv.server_close()
        finished.set()
        if watcher.ident is not None:
            watcher.join()
    request.check()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("text", nargs="?", default="Hello, this text to speech model runs entirely on the device.")
    ap.add_argument("--file", help="read the text from this file (any length)")
    ap.add_argument("--speaker", default="aiden")
    ap.add_argument(
        "--language", default="english", type=str.lower,
        choices=[*LANGUAGES.values(), *LANGUAGES],
        help="explicit text language (name or two-letter code)",
    )
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--sink", default="browser", choices=["browser", "aplay", "none"])
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--out", default="stream.wav")
    ap.add_argument("--models", default=os.environ.get("QWEN3_TTS_MODELS"))
    a = ap.parse_args()
    a.language = LANGUAGES.get(a.language, a.language)

    with managed_owner(lambda path: TTS(path), a.models) as (tts, request):
        if a.sink == "browser":
            serve(tts, a, request)
        else:
            sinks = []
            try:
                if a.sink == "aplay":
                    sinks.append(AplaySink())
                stop = threading.Event()
                speak(tts, a, sinks, stop, request)
            finally:
                for sink in sinks:
                    sink.close()


if __name__ == "__main__":
    from runtime_logging import entrypoint
    try:
        raise SystemExit(entrypoint(main))
    except ExampleInterrupted as exc:
        raise SystemExit(128 + exc.signum)
