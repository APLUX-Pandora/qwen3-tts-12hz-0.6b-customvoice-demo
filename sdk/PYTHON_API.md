# Python API

`pandora_qwen3_tts_12hz_0_6b_customvoice` · Synthesize complete or streamed mono audio.

## Quick start

Complete [SDK installation](README.md) and [model preparation](../docs/MODEL_SETUP.md). Run from the Demo root in the activated environment.

```python
from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel

with TTSModel.from_pretrained("models") as model:
    result = model.synthesize(
        "你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",
        speaker="vivian", language="zh")
    print(result.sample_rate, result.duration_s, result.finish_reason)
```

The returned audio remains valid after the model closes.

## API overview

Signatures below are the public bound calls (`self`/`cls` omitted). Return types describe the actual objects.

| Signature / property | Purpose and return | Example |
| --- | --- | --- |
| `TTSModel.from_pretrained(model_dir, *, runtime=None) -> TTSModel` | Synchronously load local resources and return an owned model; no download. | Quick start above; [complete example](../examples/python/synthesize.py). |
| `model.synthesize(text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None) -> SynthesisResult` | Consume a complete text string; return the full waveform after generation and tail processing finish. | Quick start above. |
| `model.synthesize_stream(text, *, speaker, language, prompt=None, seed=None, max_new_tokens=None) -> AudioStream` | Consume a complete text string; reserve the model immediately and return a closeable iterator. Audio is generated when iterated, not at stream construction. | Streaming example below; [WAV streaming example](../examples/python/stream.py). |
| `model.speakers -> tuple[str, ...]` | Query the loaded package's available voice IDs. | Voice query below. |
| `model.capabilities -> TTSCapabilities` | Query immutable support flags; not required before ordinary calls. | `print(model.capabilities.prompt)` inside a model context. |
| `model.close() -> None` | Release an idle model and its internally owned Runtime. | `with TTSModel.from_pretrained("models") as model:` closes on exit. |
| `stream.close() -> None` | Stop further scheduling, wait for in-flight work and release request ownership. | Inner `with` below, including after `break`. |

An `AudioStream` supports `iter(stream)`, `next(stream) -> AudioChunk` (or `StopIteration`), and context management. It is returned by the model; callers do not construct it directly.

```python
from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel

with TTSModel.from_pretrained("models") as model:
    with model.synthesize_stream(
        "Hello, welcome to text-to-speech. Today, we use a clear and natural voice to turn written words into speech you can hear.",
        speaker="ryan", language="en") as stream:
        for chunk in stream:
            print(chunk.audio.shape, chunk.sample_rate)
    print(stream.finish_reason)
```

## Parameters

### Loading: from_pretrained

| Parameter | Type | Required / omitted or None | Legal values, units and limits |
| --- | --- | --- | --- |
| `model_dir` | `str`, path-like or `None` | Required. Omitting it raises `TypeError`. Passing `None` or an invalid path raises `TTSLoadError`. | Local package root containing `models.json`, or a parent containing exactly one immediate child package. No automatic download or fallback to another root. Relative paths use the caller's working directory; `~` is expanded. |
| `runtime` | This SDK's `Runtime` or `None` | Default `None`: create a model-owned default Runtime. | CPU `default`, QNN `burst`, priority `normal`, device `0`; activity RPC control preset 100 μs. The model holds a reference to a supplied Runtime. Closing that Runtime first leaves already loaded models usable. See the independent [Runtime reference](RUNTIME_API.md) for configuration and supported settings. |

### Requests: shared by synthesize and synthesize_stream

| Parameter | Type | Required / omitted or None | Legal values, units and limits |
| --- | --- | --- | --- |
| `text` | `str` | Required; no default; `None` rejected. | Nonempty after whitespace check, NUL-free. Passed intact to the model tokenizer; no hidden number normalization, sentence splitting or incremental text ingestion. Context limits below apply after tokenization. |
| `speaker` | `str` | Required; no default; `None` rejected. | Exact, case-sensitive ID from the [built-in speaker table](#built-in-speakers) and `model.speakers`; unknown IDs fail. A voice ID selects conditioning, not an arbitrary reference recording. |
| `language` | `str` | Required; no default; `None` and `"auto"` unsupported. | One of the codes below that is present in `model.languages`. Declares the text language, not translation, automatic detection or a style instruction. Case-sensitive. |
| `prompt` | `str` or `None` | Omitted/`None`, empty or whitespace-only string resolves to no instruction. | NUL-free. This 0.6B CustomVoice model rejects nonempty instructions with `TTSUnsupportedError`; arbitrary style prompts and voice cloning are unsupported. |
| `seed` | `int` or `None` | Omitted/`None` resolves to native seed **0**, for this request. | Inclusive `0..4294967295` (uint32); reject bool, floats and out-of-range values. Seed 0 is a fixed seed, not an instruction to choose a random seed. |
| `max_new_tokens` | `int` or `None` | Omitted/`None` resolves to native `max_frames=0`: no caller cap, still subject to the model context bound. | Explicit inclusive `1..2147483647`; reject bool/floats. Counts main speech frames, each 80 ms, not text tokens, samples or seconds. Limits actual generation; no full generation followed by slicing. A larger value cannot extend the fixed graph/context capacity. |

All defaults reset per request; omitted values do not inherit a previous request's overrides. The SDK does not expose temperature/top-k/top-p controls. Web/business-layer seed and segmentation choices are caller settings, not these SDK defaults.

The fixed Talker graph has 2048 rows; the request uses a 2016-row input-plus-generation bound and rejects a prefill longer than 1919 rows. The remaining generation capacity depends on the tokenized input, including voice/language/template tokens. Do not infer a character-count limit or unlimited generation from `None`; split long text in the application when needed.

### Built-in speakers

The supplied CustomVoice model package provides these nine voice IDs. Pass an exact lower-case ID as `speaker` to either synthesis method; it is required and has no default.

| Voice ID (`speaker`) | Built-in voice | Native language / dialect |
| --- | --- | --- |
| `vivian` | Vivian | Chinese |
| `serena` | Serena | Chinese |
| `uncle_fu` | Uncle Fu | Chinese |
| `ryan` | Ryan | English |
| `aiden` | Aiden | English |
| `ono_anna` | Ono Anna | Japanese |
| `sohee` | Sohee | Korean |
| `eric` | Eric | Chinese (Sichuan) |
| `dylan` | Dylan | Chinese (Beijing) |

Native-language labels follow the [upstream speaker descriptions](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice#supported-speakers); the upstream recommends each voice's native language for the best results. This describes the voice, while `language` specifies the input text language. For `dylan` and `eric`, use `language="zh"`; Beijing and Sichuan are voice/dialect characteristics, not additional Python language codes.

`speaker` selects the built-in voice; `language` separately selects the text language. For example, use `speaker="vivian", language="zh"` or `speaker="ryan", language="en"`. Query `model.speakers` after loading to confirm the IDs in your local package; see [voice queries](#voice-and-capability-queries).

### Text-language codes

These are the complete Python code mappings; the loaded model's `model.languages` query reports available codes. Use explicit lower-case codes with either synthesis method.

| Code | Text language |
| --- | --- |
| `zh` | Chinese（中文） |
| `en` | English（英语） |
| `ja` | Japanese（日语） |
| `ko` | Korean（韩语） |
| `de` | German（德语） |
| `fr` | French（法语） |
| `ru` | Russian（俄语） |
| `es` | Spanish（西班牙语） |
| `it` | Italian（意大利语） |
| `pt` | Portuguese（葡萄牙语） |

The C ABI uses its own enumerated native language names; do not pass those names in place of Python codes.

### Voice and capability queries

Voice IDs come from the loaded package rather than a caller-defined enum. Query them through the public property:

```python
from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel

with TTSModel.from_pretrained("models") as model:
    print(model.speakers)       # tuple of exact accepted voice IDs
    print(model.languages)      # tuple of available language codes
    print(model.capabilities)   # streaming=True, prompt=False, seed=True,
                               # max_new_tokens=True for this model
```

The [speaker table](#built-in-speakers) lists all nine supplied voices, including `vivian` and `ryan` used above. Select an ID from the actual query; there is no public method to create or register cloned voices in this SDK.

## Results and cleanup

### Complete and streamed audio

| Value / field | Type and meaning |
| --- | --- |
| `SynthesisResult.audio` | Independently owned, writable NumPy `float32` array, mono shape `(samples,)`. Valid after later calls or model closure. |
| `SynthesisResult.sample_rate` | `int`, actual output samples/second (24000 for this model). |
| `SynthesisResult.duration_s` | `float`, `len(audio) / sample_rate`, in seconds. |
| `SynthesisResult.finish_reason` | `"stop"`: normal native termination with required waveform tails drained. `"length"`: generation budget or context bound stopped generation; valid but incomplete audio. |
| `SynthesisResult.is_complete` | `bool`, exactly `finish_reason == "stop"`. |
| `AudioChunk.audio` | Independently owned `float32` mono array containing only new samples, not the cumulative waveform. |
| `AudioChunk.sample_rate` | `int`, actual sample rate, fixed throughout this request. |
| `stream.sample_rate` | `int`, available before iteration. |
| `stream.finish_reason` | `None` before completion; `"stop"` or `"length"` on exhaustion; `"cancelled"` after early close. Closing an exhausted stream preserves its reason. |

Result/chunk dataclass fields are read-only; the arrays themselves are writable. Streaming keeps no full waveform. Saving, concatenation and playback are caller responsibilities.

### Errors

| Exception | Meaning / response |
| --- | --- |
| `TypeError` | Wrong request type, bool-as-int, missing required arguments, or a foreign Runtime type. |
| `ValueError` | Empty/NUL-containing text or IDs, unknown speaker, invalid integer range, malformed prompt, or text too long for one utterance (split it). Correct the input; the model stays usable after the stream is closed. |
| `TTSUnsupportedError` | Unsupported text-language code or nonempty instruction prompt. |
| `TTSLoadError` | Package discovery/integrity, native SDK/ABI, authorization or backend initialization failed; no loaded model is returned. Load-path failures are wrapped here, with the cause retained. A well-formed device ID absent from QNN topology has `native_code=-3`; no device fallback occurs. |
| `TTSInferenceError` | Native request/generation failure or invalid audio output. Close the stream and recreate the model after successful cleanup. |
| `TTSStateError` | Busy, closed, failed, fork-inherited model or invalid stream order; finish/release the owner before reuse. |

TTS-specific exceptions derive from `TTSError` (`RuntimeError`) and expose `native_code` (an integer when available, otherwise `None`); wrapped failures retain `__cause__`. Validation errors before generation release the request claim without poisoning the model. Runtime-specific errors and unsupported Runtime settings are described in [Runtime](RUNTIME_API.md).

### Lifecycle

Use nested model/stream context managers as above. A stream reserves the model immediately **until explicitly closed**, including after iterator exhaustion. A stream dropped without `close()` releases the model when it is garbage-collected; do not rely on that timing. After early `break`, the inner context closes the stream, stops further scheduling and waits for in-flight work. It does not generate the rest of the text or fabricate normal completion. The model can then serve another request.

Each model permits one active request. Reusing or closing a busy model raises `TTSStateError`; close the stream and finish active calls first. Sequential successful `close()` is idempotent. A close failure remains an error on repeated model close; retained resources are not successful cleanup. Handles are process-local: do not inherit them through fork; create them after spawn/exec. Applications own signal handling and cooperative cancellation.

Closing a model releases its FastRPC buffers and its reference to the native SDK. The vendor runtime keeps a shared DMA heap descriptor and logging socket for the lifetime of the process.

## Advanced

- [Runnable Python examples and file outputs](../examples/README.md).
- [Runtime configuration and ownership](RUNTIME_API.md); it is separate from synthesis parameters.
- [C ABI integration](../docs/C_ABI.md) for native clients.
- [Read-only diagnostics](../docs/DIAGNOSTICS_API.md): `model.languages`, `model.info`, `model.stats()`, `sample_rate` and `sdk_version` are diagnostic extensions, not alternate synthesis paths.
- [Web/business layer](../demo/README.md): normalization, long-text splitting, joining, pacing and HTTP belong to the caller. The SDK processes one complete text string per request.
