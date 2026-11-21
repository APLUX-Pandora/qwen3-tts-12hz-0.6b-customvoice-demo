"""Qwen3-TTS task API; transport and text segmentation remain caller policies."""

from contextlib import suppress

from ._native import Q3TError, _Native, resolve_model_dir
from ._types import (
    TTSLoadError,
    TTSInferenceError,
    TTSStateError,
    TTSCapabilities,
    LANGUAGES,
    options,
)
from ._runtime import Runtime
from ._request import ModelOwner, RequestRejected, native_signals, error

# Native start rejections caused by the request itself (Q3T_ERR_ARG, Q3T_ERR_TOO_LONG).
_INPUT_CODES = (-1, -5)


class TTSModel(ModelOwner):
    _capabilities = TTSCapabilities(True, False, True, True)

    @classmethod
    def from_pretrained(cls, model_dir=None, *, library=None, runtime=None):
        if runtime is not None and not isinstance(runtime, Runtime):
            raise TypeError("runtime must be this SDK Runtime")
        model = cls.__new__(cls)
        model._ownership()
        model._native = None
        model.runtime = runtime if runtime is not None else Runtime()
        model._owns_runtime = runtime is None
        try:
            model.model_dir = resolve_model_dir(model_dir)
            model._native = _Native.__new__(_Native)
            model._native._pid = model._pid
            import ctypes
            model._native._slot = ctypes.c_void_p()
            with native_signals():
                model._native.__init__(model.model_dir, library=library, runtime=model.runtime)
            native = model._native
            model.sample_rate = native.sampling_rate
            from types import MappingProxyType
            model.info = MappingProxyType(dict(native.info))
            model._speakers = tuple(native.speakers)
            model._languages = tuple(
                code for code, name in LANGUAGES.items() if name in native.languages
            )
            model.sdk_version = native._lib.q3t_version().decode()
            model._stats = {}
            model._last_codes = None
            return model
        except BaseException as exc:
            if model._native is not None:
                with native_signals():
                    model._native.close()
            if model._owns_runtime:
                model.runtime.close()
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise error(exc, TTSLoadError) from exc

    def _validate(self, *args):
        return options(*args, self.speakers, self.languages, False)

    def _audio(self, request, state):
        native = self._native
        self._stats = {}
        self._last_codes = None
        with native_signals():
            try:
                native.start(
                    request["text"],
                    request["speaker"],
                    LANGUAGES[request["language"]],
                    request["seed"],
                    request["max_new_tokens"],
                )
            except Q3TError as exc:
                with suppress(Q3TError):
                    self._stats = native.stats()
                if exc.code in _INPUT_CODES:
                    raise RequestRejected(str(exc), exc.code) from exc
                raise
        while not state.stop.is_set():
            with native_signals():
                try:
                    audio = native.next_audio()
                except Q3TError:
                    with suppress(Q3TError):
                        self._stats = native.stats()
                    raise
                self._stats = native.stats()
                if audio is not None:
                    self._last_codes = native.last_codes()
            if audio is not None and len(audio):
                yield audio
            if self._stats["end_reason"] != "running":
                reason = {
                    "eos": "stop",
                    "max_frames": "length",
                    "context": "length",
                    "cancelled": "cancelled",
                }.get(self._stats["end_reason"])
                if reason is None:
                    raise TTSInferenceError("Unknown native end reason")
                state.finish_reason = reason
                return
            if audio is None:
                raise TTSInferenceError("Native returned no audio while still running")
        state.finish_reason = "cancelled"

    def _stop_backend(self):
        if self._native is not None:
            with native_signals():
                self._native.cancel()

    def _close_backend(self):
        failure = None
        if self._native is not None:
            try:
                with native_signals():
                    self._native.close()
            except BaseException as exc:
                failure = exc
            if not self._native._slot.value:
                self._native = None
        if self._owns_runtime:
            try:
                self.runtime.close()
            except BaseException as exc:
                if failure is None: failure = exc
        if failure is not None:
            if isinstance(failure, (KeyboardInterrupt, SystemExit)): raise failure
            raise error(failure, TTSStateError) from failure
