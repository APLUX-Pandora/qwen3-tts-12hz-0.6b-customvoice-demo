# Qwen3-TTS-12Hz-0.6B-CustomVoice SDK

This SDK loads Qwen3-TTS-12Hz-0.6B-CustomVoice and produces complete or streamed mono audio.

## What's included

| Path | Content |
| --- | --- |
| `python/pandora_qwen3_tts_12hz_0_6b_customvoice/` | Python package (`from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel`) |
| `include/` | C header |
| `lib/` | Prebuilt native library with its QNN runtime |
| `SHA256SUMS` | Checksums of the shipped files |

From `sdk/`, run `sha256sum -c SHA256SUMS` to verify the native libraries, headers, Python package files, and shared Runtime wheel. The model library and its bundled QNN libraries also have a list at `lib/SHA256SUMS`.

## Install

In your application's activated Python 3.10–3.12 environment, from the Demo root:

```bash
python -m pip install sdk/wheels/pandora_runtime-*.whl
python -m pip install ./sdk
```

The device must pass `sudo lms check`. The SDK does not install LMS or drivers and does not download models; see [Get the model](../README.md#2-get-the-model).

See [native compatibility](../docs/MODEL_SETUP.md#environment-details) for Linux and Python requirements.

## Usage

From the Demo root in the activated environment:

```python
from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel

with TTSModel.from_pretrained("models") as model:
    result = model.synthesize(
        "你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",
        speaker="vivian", language="zh")
    print(result.sample_rate, result.duration_s, result.finish_reason)
```

Pass the path to your model package when integrating from another directory. Saving and playback belong to the application.

## Documentation

- [Python API](PYTHON_API.md)
- [Runtime](RUNTIME_API.md)
- [C ABI](../docs/C_ABI.md)
- [Examples](../examples/README.md)
- [Licensing](../LICENSING.md)
