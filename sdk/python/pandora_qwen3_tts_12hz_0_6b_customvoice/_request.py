"""Synchronous request ownership; audio transport and playback belong to callers."""

from contextlib import contextmanager, suppress
import os
import threading
import numpy as np
from ._types import (
    AudioChunk,
    SynthesisResult,
    TTSStateError,
    TTSInferenceError,
)


@contextmanager
def native_signals():
    # Compatibility context: the SDK never changes application signal masks.
    yield


class RequestRejected(ValueError):
    """The native layer refused the request before generating anything; the model stays usable."""

    def __init__(self, message, native_code):
        super().__init__(message)
        self.native_code = native_code


class StreamState:
    """Shared by a stream and its generator without referencing the stream, so dropping it releases at once."""

    def __init__(self):
        self.stop = threading.Event()
        self.finish_reason = None


def error(exc, category=TTSInferenceError):
    return category(
        str(exc), native_code=getattr(exc, "code", getattr(exc, "native_code", None))
    )


class ModelOwner:
    def _ownership(self):
        self._pid = os.getpid()
        self._request = threading.Lock()
        self._closed = False
        self._failed = False
        self._close_error = None
        self._stats = {}

    def _check_pid(self):
        if os.getpid() != self._pid:
            raise TTSStateError("Model inherited through fork; use spawn/exec")

    def _claim(self):
        self._check_pid()
        if not self._request.acquire(blocking=False):
            raise TTSStateError("Model has an active request; close it first")
        if self._closed or self._failed:
            self._request.release()
            raise TTSStateError("Model is closed or requires recreation after failure")

    @property
    def capabilities(self):
        return self._capabilities

    @property
    def speakers(self):
        return tuple(self._speakers)

    @property
    def languages(self):
        return tuple(self._languages)

    def stats(self):
        return dict(self._stats)

    def synthesize(
        self, text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None
    ):
        with self.synthesize_stream(
            text,
            speaker=speaker,
            language=language,
            prompt=prompt,
            seed=seed,
            max_new_tokens=max_new_tokens,
        ) as stream:
            parts = [chunk.audio for chunk in stream]
            if stream.finish_reason not in ("stop", "length"):
                raise TTSInferenceError("Synthesis did not complete normally")
            audio = np.concatenate(parts) if parts else np.empty(0, np.float32)
            return SynthesisResult(audio, stream.sample_rate, stream.finish_reason)

    def synthesize_stream(
        self, text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None
    ):
        self._claim()
        try:
            request = self._validate(
                text, speaker, language, prompt, seed, max_new_tokens
            )
            return AudioStream(self, request)
        except BaseException:
            self._request.release()
            raise

    def close(self):
        self._check_pid()
        if self._close_error is not None: raise self._close_error
        if not self._request.acquire(blocking=False):
            raise TTSStateError("Close the active request before closing the model")
        try:
            if not self._closed:
                try:
                    self._close_backend()
                except BaseException as exc:
                    self._failed, self._close_error = True, exc
                    raise
                self._closed = True
        finally:
            self._check_pid()
            self._request.release()

    def __enter__(self):
        self._check_pid()
        if self._closed:
            raise TTSStateError("Model is closed")
        return self

    def __exit__(self, *_):
        self.close()


class AudioStream:
    def __init__(self, model, request):
        self._model = model
        self._request = request
        self.sample_rate = model.sample_rate
        self._state = StreamState()
        self._iterator = None
        self._closed = False
        self._operation = threading.Lock()
        self._rejected = False

    @property
    def finish_reason(self):
        return self._state.finish_reason

    @finish_reason.setter
    def finish_reason(self, value):
        self._state.finish_reason = value

    def __iter__(self):
        return self

    def __next__(self):
        self._model._check_pid()
        if not self._operation.acquire(blocking=False):
            raise TTSStateError("Stream has an active call")
        try:
            if self._closed:
                raise TTSStateError("Stream is closed")
            if self._rejected:
                raise TTSStateError("Request was rejected; close the stream")
            if self.finish_reason is not None:
                raise StopIteration
            if self._state.stop.is_set():
                self.finish_reason = "cancelled"
                raise StopIteration
            if self._iterator is None:
                self._iterator = iter(self._model._audio(self._request, self._state))
            try:
                audio = next(self._iterator)
            except StopIteration:
                if self.finish_reason not in ("stop", "length", "cancelled"):
                    self._model._failed = True
                    raise TTSInferenceError(
                        "Native stream ended without a terminal reason"
                    )
                raise
            except RequestRejected:
                # Rejected before generation; the model stays usable once this stream is closed.
                self._rejected = True
                raise
            except BaseException as exc:
                self._model._failed = True
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                if isinstance(exc, TTSInferenceError):
                    raise
                raise error(exc) from exc
            output = np.array(audio, dtype=np.float32, copy=True, order="C")
            if output.ndim != 1 or not np.isfinite(output).all():
                self._model._failed = True
                raise TTSInferenceError("Invalid native audio output")
            return AudioChunk(output, self.sample_rate)
        finally:
            self._model._check_pid()
            self._operation.release()

    def close(self):
        self._model._check_pid()
        self._state.stop.set()
        with self._operation:
            if self._closed:
                return
            try:
                if self._iterator is not None:
                    self._iterator.close()
                self._model._stop_backend()
            except BaseException:
                self._model._failed = True
                raise
            finally:
                if self.finish_reason is None:
                    self.finish_reason = "cancelled"
                self._closed = True
                self._model._request.release()

    def __enter__(self):
        self._model._check_pid()
        if self._closed:
            raise TTSStateError("Stream is closed")
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        # Safety net for streams dropped without close(): release the model reservation.
        # A finalizer cannot report failures; close() already marks the model failed if cleanup fails.
        with suppress(Exception):
            if not self._closed and os.getpid() == self._model._pid:
                self.close()
