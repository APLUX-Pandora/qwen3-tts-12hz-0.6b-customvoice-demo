"""Internal ctypes transport for the public qwen3_tts.TTSModel inference API.

Installed packages resolve their bundled native library. Explicit library choices
are strict; source-only diagnostic builds may use sdk/lib or sdk/build.
"""

from contextlib import nullcontext
import ctypes as C
import os
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.dirname(HERE)
# Source-only discovery is unavailable in an installed SDK.
SOURCE_CHECKOUT = (Path(SDK) / "CMakeLists.txt").is_file()
ERRORS = {
    -1: "Q3T_ERR_ARG",
    -2: "Q3T_ERR_MODEL",
    -3: "Q3T_ERR_NPU",
    -4: "Q3T_ERR_STATE",
    -5: "Q3T_ERR_TOO_LONG",
    -6: "Q3T_ERR_INTERNAL",
    -7: "Q3T_ERR_UNSUPPORTED",
    -8: "Q3T_ERR_BUSY",
    -9: "Q3T_ERR_AUTHORIZATION",
}
END_REASONS = {0: "running", 1: "eos", 2: "max_frames", 3: "context", 4: "cancelled", 5: "error"}
NUM_CODEBOOKS = 16


class Q3TError(RuntimeError):
    """Machine-readable Q3T_ERR_* code and native provider diagnostic."""

    def __init__(self, code, msg):
        super().__init__(
            f"{'q3t_create failed' if code is None else ERRORS.get(code, code)}: {msg}"
        )
        self.code = code


class _Request(C.Structure):
    _fields_ = [
        ("text", C.c_char_p),
        ("speaker", C.c_char_p),
        ("language", C.c_char_p),
        ("seed", C.c_uint32),
        ("max_frames", C.c_int),
    ]


class _Info(C.Structure):
    _fields_ = [
        ("sampling_rate", C.c_int),
        ("samples_per_frame", C.c_int),
        ("frames_per_chunk", C.c_int),
        ("max_chunk_samples", C.c_int),
        ("context_rows", C.c_int),
        ("num_speakers", C.c_int),
        ("num_languages", C.c_int),
    ]


class _Stats(C.Structure):
    _fields_ = [
        ("prefill_rows", C.c_int),
        ("frames", C.c_int),
        ("chunks", C.c_int),
        ("end_reason", C.c_int),
        ("ms_frontend", C.c_double),
        ("ms_talker_prefill", C.c_double),
        ("ms_talker_npu", C.c_double),
        ("ms_code_predictor_npu", C.c_double),
        ("ms_codec_npu", C.c_double),
        ("ms_host", C.c_double),
    ]


_LIB = None


def lib(library=None):
    if library is not None:
        selected = str(Path(library).expanduser().resolve(strict=True))
    elif os.environ.get("QWEN3_TTS_LIB"):
        selected = str(
            Path(os.environ["QWEN3_TTS_LIB"]).expanduser().resolve(strict=True)
        )
    else:
        bundled = Path(HERE) / "lib/libqwen3_tts.so"
        if bundled.is_file():
            selected = str(bundled)
        elif SOURCE_CHECKOUT:
            candidates = [Path(SDK) / "lib/libqwen3_tts.so", Path(SDK) / "build/libqwen3_tts.so"]
            selected = str(next((p for p in candidates if p.is_file()), candidates[0]))
        else:
            raise FileNotFoundError("Installed SDK is missing its bundled libqwen3_tts.so")
    from pandora_runtime import load_library as load_runtime_library
    load_runtime_library()
    L = C.CDLL(selected)
    P = C.c_void_p
    signatures = {
        "q3t_version": (C.c_char_p, []),
        "q3t_prepare_process": (C.c_int, []),
        "q3t_create": (P, [C.c_char_p, P]),
        "q3t_create_with_runtime": (C.c_int, [C.c_char_p, P, P, C.POINTER(P)]),
        "q3t_destroy_owned": (C.c_int, [C.POINTER(P)]),
        "q3t_create_error": (C.c_char_p, []),
        "q3t_destroy": (None, [P]),
        "q3t_last_error": (C.c_char_p, [P]),
        "q3t_get_info": (C.c_int, [P, C.POINTER(_Info)]),
        "q3t_speaker_name": (C.c_char_p, [P, C.c_int]),
        "q3t_language_name": (C.c_char_p, [P, C.c_int]),
        "q3t_default_request": (None, [C.POINTER(_Request)]),
        "q3t_start": (C.c_int, [P, C.POINTER(_Request)]),
        "q3t_next_audio": (C.c_int, [P, C.POINTER(C.c_float), C.c_int]),
        "q3t_last_codes": (C.c_int, [P, C.POINTER(C.c_int32), C.c_int]),
        "q3t_cancel": (C.c_int, [P]),
        "q3t_get_stats": (C.c_int, [P, C.POINTER(_Stats)]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(L, name)
        function.restype = result
        function.argtypes = arguments
    return L


def library():
    global _LIB
    if _LIB is None:
        _LIB = lib()
    return _LIB


def resolve_model_dir(model_dir=None):
    """Require the current models.json/AIDEM package; no legacy model fallback."""
    def configured(path):
        return (path / "models.json").is_file()
    if model_dir is None:
        if not SOURCE_CHECKOUT:
            raise ValueError("Installed SDK requires an explicit model package root containing models.json")
        base = Path(__file__).resolve().parents[2] / "models"
    else:
        if not os.fspath(model_dir):
            raise ValueError("Model package path must not be empty")
        base = Path(model_dir).expanduser().resolve()
    if configured(base):
        return str(base)
    packages = sorted(p for p in base.glob("*") if p.is_dir() and configured(p))
    if len(packages) == 1:
        return str(packages[0])
    names = ", ".join(str(p) for p in packages) or "none"
    raise FileNotFoundError(f"Choose one models.json package root; searched {base}; candidates: {names}")


class _Native:
    def __init__(self, model_dir=None, *, runtime=None):
        model_dir = resolve_model_dir(model_dir)
        L = self._lib = library()
        self._pid = os.getpid()
        self._slot = C.c_void_p()
        self._runtime = runtime
        with runtime.borrow_handle() if runtime is not None else nullcontext() as handle:
            rc = L.q3t_create_with_runtime(os.fsencode(model_dir), None, handle, C.byref(self._slot))
        if rc < 0:
            raise Q3TError(rc, L.q3t_create_error().decode())
        i = _Info()
        self._check(L.q3t_get_info(self._h, C.byref(i)))
        self.info = {k: getattr(i, k) for k, _ in _Info._fields_}
        self.sampling_rate = i.sampling_rate
        self.speakers = [
            L.q3t_speaker_name(self._h, k).decode() for k in range(i.num_speakers)
        ]
        self.languages = [
            L.q3t_language_name(self._h, k).decode() for k in range(i.num_languages)
        ]
        self._buf = np.zeros(i.max_chunk_samples, np.float32)
        self._codes = np.zeros((i.frames_per_chunk, NUM_CODEBOOKS), np.int32)
        self._req = None

    @property
    def _h(self):
        if os.getpid() != self._pid:
            raise Q3TError(-4, "Model inherited through fork; use spawn/exec")
        return self._slot.value

    def _check(self, rc):
        if rc < 0:
            raise Q3TError(rc, self._lib.q3t_last_error(self._h).decode())
        return rc

    def start(self, text, speaker="vivian", language="chinese", seed=0, max_frames=0):
        """Start one utterance (text already normalized). max_frames <= 0: until the talker context is full."""
        self._req = [
            text.encode(),
            speaker.encode(),
            language.encode(),
        ]  # keep the bytes alive
        r = _Request(
            self._req[0],
            self._req[1],
            self._req[2],
            int(seed) & 0xFFFFFFFF,
            int(max_frames),
        )
        self._check(self._lib.q3t_start(self._h, C.byref(r)))

    def next_audio(self):
        """Next chunk (float32, up to 8 frames = 0.64 s, a copy), or None when the utterance has ended."""
        n = self._check(
            self._lib.q3t_next_audio(
                self._h, self._buf.ctypes.data_as(C.POINTER(C.c_float)), self._buf.size
            )
        )
        return self._buf[:n].copy() if n else None

    def last_codes(self):
        """codes of the last chunk's frames, int32 [frames, 16] (a copy)"""
        n = self._check(
            self._lib.q3t_last_codes(
                self._h,
                self._codes.ctypes.data_as(C.POINTER(C.c_int32)),
                self._codes.shape[0],
            )
        )
        return self._codes[:n].copy()

    def speak(self, text, speaker="vivian", language="chinese", seed=0, max_frames=0):
        """Generator of audio chunks of one utterance."""
        self.start(text, speaker, language, seed, max_frames)
        while True:
            w = self.next_audio()
            if w is None:
                return
            yield w

    def cancel(self):
        """End the running utterance after its current frame (any thread)."""
        self._lib.q3t_cancel(self._h)

    def stats(self):
        s = _Stats()
        self._check(self._lib.q3t_get_stats(self._h, C.byref(s)))
        d = {k: getattr(s, k) for k, _ in _Stats._fields_}
        d["end_reason"] = END_REASONS.get(d["end_reason"], d["end_reason"])
        return d

    def close(self):
        if getattr(self, "_slot", None) is None:
            return
        if self._h:
            rc = self._lib.q3t_destroy_owned(C.byref(self._slot))
            if rc < 0:
                # destroy_owned clears the slot even on quarantine; never query a retired model handle.
                raise Q3TError(rc, self._lib.q3t_create_error().decode(errors="replace"))

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
