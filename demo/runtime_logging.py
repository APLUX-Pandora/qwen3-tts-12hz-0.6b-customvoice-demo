# SPDX-License-Identifier: Apache-2.0
"""Application process wrapper; retain optional raw diagnostics outside delivery."""
import argparse
import codecs
import os
from pathlib import Path
import re
import signal
import selectors
import subprocess
import sys

PATHS = re.compile(r"(?<![\w:/])/(?:home|Users|data\d*|root|local|tmp|private|mnt|opt|usr|var|etc|run|source|workspace)(?:/[^\s\"'<>:,]*)?")
PRIVATE_IPS = re.compile(r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b")

LICENSE_IDS = re.compile(r"(?i)(license ID:\s*)aid[a-z0-9]+")


def sanitize(text):
    return LICENSE_IDS.sub(r"\1<device-license>", PRIVATE_IPS.sub("<private-address>", PATHS.sub("<path>", text)))


def run(command, *, startup_signal_mask=None, worker_stop_signal=None):
    raw = None
    raw_path = os.environ.get("MT01_RAW_LOG")
    if raw_path:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(Path(raw_path).expanduser(), flags, 0o600)
        os.fchmod(fd, 0o600)
        raw = os.fdopen(fd, "w", encoding="utf-8")
    child = None
    stopping_signal = None
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    def stop(signum, _frame):
        nonlocal stopping_signal
        stopping_signal = signum
        # Forward in the handler: an async exception can interrupt buffered log
        # reads or their cleanup. The worker owns cancellation and model closure.
        if child is not None:
            try:
                child.send_signal(worker_stop_signal if worker_stop_signal is not None else signum)
            except ProcessLookupError:
                pass

    for sig in previous:
        signal.signal(sig, stop)
    try:
        if startup_signal_mask is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, startup_signal_mask)
        child = subprocess.Popen(command, stderr=subprocess.PIPE, text=True,
                                 encoding="utf-8", errors="replace", start_new_session=True,
                                 env={**os.environ, "MT01_FILTER_WORKER": "1"})
        # A signal can arrive between installing handlers and receiving the PID.
        if stopping_signal is not None:
            stop(stopping_signal, None)
        # Native dependencies may have existing unblocked threads. A process
        # signal can arrive on one of them, so the main thread must periodically
        # run Python even when the worker has no diagnostics to write.
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        pending = ""
        with selectors.DefaultSelector() as selector:
            selector.register(child.stderr, selectors.EVENT_READ)
            while selector.get_map():
                for key, _events in selector.select(timeout=0.1):
                    data = os.read(key.fd, 65536)
                    pending += decoder.decode(data, final=not data)
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        line += "\n"
                        if raw:
                            raw.write(line); raw.flush()
                        sys.stderr.write(sanitize(line)); sys.stderr.flush()
                    if not data:
                        selector.unregister(key.fileobj)
                        if pending:
                            if raw:
                                raw.write(pending); raw.flush()
                            sys.stderr.write(sanitize(pending)); sys.stderr.flush()
        code = child.wait()
        return code if code >= 0 else 128 - code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if child is not None:
            child.stderr.close()
            if child.poll() is None:
                child.terminate(); child.wait(timeout=5)
        if raw:
            raw.close()


def entrypoint(main, *, startup_signal_mask=None, worker_stop_signal=None):
    """Filter native/Python stderr at CLI boundaries without changing result stdout."""
    if os.environ.get("MT01_FILTER_WORKER") == "1":
        result = main()
        return 0 if result is None else result
    return run([sys.executable, *sys.argv], startup_signal_mask=startup_signal_mask,
               worker_stop_signal=worker_stop_signal)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required")
    raise SystemExit(run(command))
