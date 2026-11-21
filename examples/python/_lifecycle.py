"""Cooperative ownership for CLI examples, separate from the SDK."""
from contextlib import contextmanager
import signal


class ExampleInterrupted(Exception):
    def __init__(self, signum):
        super().__init__(f"interrupted by signal {signum}")
        self.signum = signum


class StopRequest:
    def __init__(self):
        self.signum = None

    def check(self):
        if self.signum is not None:
            raise ExampleInterrupted(self.signum)


@contextmanager
def managed_owner(factory, *args, **kwargs):
    """Keep native calls restartable and let the returned handle get an owner."""
    stop = StopRequest()
    owner = None

    def request_stop(signum, _frame):
        if stop.signum is None:
            stop.signum = signum

    previous = {s: signal.signal(s, request_stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for sig in previous:
            signal.siginterrupt(sig, False)
        owner = factory(*args, **kwargs)
        stop.check()
        yield owner, stop
        stop.check()
    finally:
        try:
            if owner is not None:
                owner.close()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


@contextmanager
def runtime_kwargs(cpu):
    """Own an explicit CLI override until the model has closed."""
    if cpu is None:
        yield {}
        return

    from pandora_qwen3_tts_12hz_0_6b_customvoice import Runtime

    with managed_owner(Runtime, cpu=cpu) as (runtime, _):
        yield {"runtime": runtime}


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
