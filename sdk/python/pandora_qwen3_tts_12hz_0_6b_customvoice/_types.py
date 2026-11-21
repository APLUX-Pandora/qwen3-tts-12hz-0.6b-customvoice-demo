"""Owned audio values and errors for this independently installed TTS SDK."""

from dataclasses import dataclass
import numpy as np


class TTSError(RuntimeError):
    def __init__(self, message, *, native_code=None):
        super().__init__(message)
        self.native_code = native_code


class TTSLoadError(TTSError):
    pass


class TTSInferenceError(TTSError):
    pass


class TTSStateError(TTSError):
    pass


class TTSUnsupportedError(TTSError):
    pass


@dataclass(frozen=True)
class TTSCapabilities:
    streaming: bool
    prompt: bool
    seed: bool
    max_new_tokens: bool


@dataclass(frozen=True)
class AudioChunk:
    audio: np.ndarray
    sample_rate: int


@dataclass(frozen=True)
class SynthesisResult:
    audio: np.ndarray
    sample_rate: int
    finish_reason: str

    @property
    def duration_s(self):
        return len(self.audio) / self.sample_rate

    @property
    def is_complete(self):
        return self.finish_reason == "stop"


LANGUAGES = {
    "zh": "chinese",
    "en": "english",
    "ja": "japanese",
    "ko": "korean",
    "de": "german",
    "fr": "french",
    "ru": "russian",
    "es": "spanish",
    "it": "italian",
    "pt": "portuguese",
}


def string(value, name):
    if not isinstance(value, str):
        raise TypeError(name + " must be a string")
    if not value.strip() or "\0" in value:
        raise ValueError(name + " must be nonempty and NUL-free")
    return value


def integer(value, name, default, minimum, maximum):
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(name + " must be an integer or None")
    if not minimum <= value <= maximum:
        raise ValueError(name + " is outside the supported range")
    return value


def options(
    text,
    speaker,
    language,
    prompt,
    seed,
    max_new_tokens,
    speakers,
    languages,
    supports_prompt,
):
    string(text, "text")
    string(speaker, "speaker")
    string(language, "language")
    if speaker not in speakers:
        raise ValueError("Unknown speaker: " + speaker)
    if language not in languages:
        raise TTSUnsupportedError("Unsupported text language: " + language)
    if prompt is not None:
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a string or None")
        if "\0" in prompt:
            raise ValueError("prompt must be NUL-free")
        prompt = prompt.strip() or None
    if prompt is not None and not supports_prompt:
        raise TTSUnsupportedError("This model does not support prompt instructions")
    return dict(
        text=text,
        speaker=speaker,
        language=language,
        prompt=prompt,
        seed=integer(seed, "seed", 0, 0, 2**32 - 1),
        max_new_tokens=integer(max_new_tokens, "max_new_tokens", 0, 1, 2**31 - 1),
    )
