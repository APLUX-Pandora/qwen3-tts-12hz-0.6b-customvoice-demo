# Examples

## Overview

| Example | What it shows |
| --- | --- |
| [python/synthesize.py](python/synthesize.py) | Synthesize a complete utterance and write a WAV file. |
| [python/stream.py](python/stream.py) | Write each chunk to a mono PCM16 WAV file as it arrives. |
| [c/synthesize.c](c/synthesize.c) | Synthesize audio and write a WAV file using the public C ABI. |

Both Python scripts share [python/_lifecycle.py](python/_lifecycle.py) for signal handling and resource cleanup.

## Before you run

Complete [Install](../README.md#1-install) and [Get the model](../README.md#2-get-the-model). Run every command from the Demo root in the activated environment. Stop the Web Demo first; examples and the Web Demo share the NPU.

## Python examples

### synthesize.py

Synthesize the built-in English text and save the complete waveform.

```bash
python examples/python/synthesize.py --out speech.wav
```

Open `speech.wav` in an audio player to hear the complete utterance.

### stream.py

Synthesize the built-in English text, writing chunks of audio to disk as they arrive.

```bash
python examples/python/stream.py --out stream.wav
```

Open `stream.wav` in an audio player to hear the audio saved during streaming.

Both scripts default to `speech.wav` when `--out` is omitted. Use `--out` to choose a filename, `--models` to select another package, or `--language` and `--speaker` to select the input language and voice. Start either script with `--help` for all options. See the [Runtime guide](../sdk/RUNTIME_API.md) for custom hardware settings.

## C example

### synthesize.c

Synthesize the built-in Chinese text and save it to `native.wav`.

Build against the headers and prebuilt library in `sdk/`:

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -Wall -Wextra -Werror -I sdk/include examples/c/synthesize.c -L sdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" -lqwen3_tts -Wl,-rpath,'$ORIGIN/../../sdk/lib' -lm -o examples/c/synthesize
examples/c/synthesize models native.wav zh
```

Open `native.wav` in an audio player to hear the result.

Arguments are `MODEL_DIRECTORY OUTPUT_WAV [zh|en] [TEXT]`; the optional language defaults to `en`. The model directory contains `models.json` and its required resources. The optional `TEXT` replaces the fixed text for the selected language. The client writes mono PCM16 WAV incrementally. See [C ABI integration](../docs/C_ABI.md#build-and-link) for build/link details and ownership rules.

## Reference

### Built-in speakers
The supplied CustomVoice model provides the following voice IDs. `speaker` selects a voice, while `language` selects the input text language.

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

For example, in the activated environment:

```bash
python examples/python/synthesize.py --language en --speaker aiden --text "Welcome to Pandora." --out aiden.wav
```

### Text languages

The public SDK supports these explicit language codes. The two convenience scripts accept `en` and `zh`; use [the Python API](../sdk/PYTHON_API.md) directly for the other codes. Pass `speaker` and `language` explicitly and query `model.speakers` / `model.languages` for the loaded package. `None` and `auto` are not accepted language selections.

| Code (`language`) | Text language |
| --- | --- |
| `zh` | Chinese |
| `en` | English |
| `ja` | Japanese |
| `ko` | Korean |
| `de` | German |
| `fr` | French |
| `ru` | Russian |
| `es` | Spanish |
| `it` | Italian |
| `pt` | Portuguese |

[Python API](../sdk/PYTHON_API.md) · [Runtime](../sdk/RUNTIME_API.md).
