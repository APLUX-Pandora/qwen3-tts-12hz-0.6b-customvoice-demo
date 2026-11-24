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
