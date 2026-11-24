# Qwen3-TTS-12Hz-0.6B-CustomVoice

<p align="center">
  <a href="https://huggingface.co/APLUX-Pandora/Qwen3-TTS-12Hz-0.6B-CustomVoice"><img src="https://img.shields.io/badge/Hugging%20Face-QWEN3--TTS--12HZ--0.6B--CUSTOMVOICE-E3B800?style=for-the-badge&amp;logo=huggingface&amp;logoColor=FFD21E&amp;labelColor=555555" alt="Hugging Face: Qwen3-TTS-12Hz-0.6B-CustomVoice"></a>
  <a href="https://github.com/APLUX-Pandora/qwen3-tts-12hz-0.6b-customvoice-demo"><img src="https://img.shields.io/badge/GitHub-QWEN3--TTS--12HZ--0.6B--CUSTOMVOICE-000000?style=for-the-badge&amp;logo=github&amp;logoColor=white&amp;labelColor=555555" alt="GitHub: Qwen3-TTS-12Hz-0.6B-CustomVoice"></a>
</p>

Streaming text-to-speech with nine built-in voices and ten explicit text languages, running on the device NPU.

Based on [Qwen3-TTS-12Hz-0.6B-CustomVoice](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice).

**Demo recording:** reserved for a post-release recording.

## 1. Install

Clone the Demo and enter its root directory:

```bash
git clone https://github.com/APLUX-Pandora/qwen3-tts-12hz-0.6b-customvoice-demo.git
cd qwen3-tts-12hz-0.6b-customvoice-demo
```

### Prepare the device

Use a compatible Linux device with Aidlux LMS and the required drivers, DSP firmware and BSP/FastRPC support. The SDK includes its QNN runtime libraries; no separate QNN installation or path configuration is required.

Check the activation:

```bash
sudo lms check
```

Continue only when it returns true.

Install the system packages the Demo needs:

```bash
sudo apt install libsndfile1 python3-venv
```

### Install the Demo and SDK

Use Python 3.10–3.12. Create and activate the Demo environment, then install:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

This installs the SDK, the Web Demo and the Hugging Face CLI. To use only the SDK in your own application, see the [SDK installation](sdk/README.md#install).

## 2. Get the model

Download the shared files and one device target. The commands below use QCS8550; for another device, use the folder in the [targets table](docs/MODEL_SETUP.md#targets).

For a private model, run `hf auth login` first.

```bash
hf download APLUX-Pandora/Qwen3-TTS-12Hz-0.6B-CustomVoice --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Qwen3-TTS-12Hz-0.6B-CustomVoice --local-dir models --include "targets/qcs8550_qnn248/*"
```

Verify the downloaded target:

```bash
python models/verify_model_package.py models --target "qcs8550_qnn248"
```

## 3. Run the Web Demo

From the Demo root, with the same project environment:

```bash
bash demo/run.sh --port 8765
```

Open `http://<device-ip>:8765/` and select a voice and text language. Stop it with `Ctrl+C`. See the [Web Demo guide](demo/README.md).

## 4. Python Usage

In the same environment, from the Demo root:

```python
from pandora_qwen3_tts_12hz_0_6b_customvoice import TTSModel

with TTSModel.from_pretrained("models") as model:
    result = model.synthesize(
        "你好，欢迎使用语音合成。今天，我们用清晰自然的声音，把文字变成可以听见的表达。",
        speaker="vivian", language="zh")
    print(result.sample_rate, result.duration_s, result.finish_reason)
```

More in the [Python API](sdk/PYTHON_API.md) and [examples](examples/README.md).

## Documentation

- [Model setup](docs/MODEL_SETUP.md) covers device requirements, targets, download and folder layout.
- [SDK](sdk/README.md) covers installation for applications.
- [Python API](sdk/PYTHON_API.md) documents synthesis, streaming and cleanup.
- [Runtime](sdk/RUNTIME_API.md) covers device selection, performance and ownership.
- [C ABI](docs/C_ABI.md) covers native integration.
- [Examples](examples/README.md) provides runnable Python and C examples.
- [Diagnostics API](docs/DIAGNOSTICS_API.md) describes read-only model information and metrics.
- [Protected loading](docs/PROTECTED_LOADING.md) explains model loading and memory ownership.
- [Weight sharing](docs/WEIGHT_SHARING.md) explains the bundled model's shared graph resources.
- [Licensing](LICENSING.md) documents component-specific terms.

## License

See [LICENSING.md](LICENSING.md), [NOTICE](NOTICE) and [LICENSES](LICENSES/) for component-specific rights and attribution.
