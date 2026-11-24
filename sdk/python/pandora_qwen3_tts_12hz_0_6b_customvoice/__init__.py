"""Pandora Qwen3-TTS CustomVoice inference SDK."""
from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _distribution_version
from pathlib import Path as _Path

from ._model import TTSModel
from ._types import (TTSError, TTSLoadError, TTSInferenceError, TTSStateError,
    TTSUnsupportedError, TTSCapabilities, AudioChunk, SynthesisResult)
from ._runtime import Runtime, CpuOptions, QnnOptions, RuntimeNativeError


try:
    __version__ = _distribution_version("pandora-qwen3-tts-12hz-0-6b-customvoice")
except _PackageNotFoundError:
    __version__ = (_Path(__file__).resolve().parents[3] / "VERSION").read_text().strip()

__all__ = ["TTSModel", "TTSError", "TTSLoadError", "TTSInferenceError", "TTSStateError",
    "TTSUnsupportedError", "TTSCapabilities", "AudioChunk", "SynthesisResult",
    "Runtime", "CpuOptions", "QnnOptions", "RuntimeNativeError"]
