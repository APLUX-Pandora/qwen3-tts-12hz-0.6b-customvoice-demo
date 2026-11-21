# Model resources

Model assets are downloaded separately from
[APLUX-Pandora/Qwen3-TTS-12Hz-0.6B-CustomVoice](https://huggingface.co/APLUX-Pandora/Qwen3-TTS-12Hz-0.6B-CustomVoice).
Download matching model resources from the repository main as described in
[model setup](../docs/MODEL_SETUP.md).

The package uses root `models.json`, shared functional resources and flat
`targets/<soc>_qnn248/` directories. Download and verify one complete target.
Keep the original shared-resource filenames, including both prefix resources.
Choose the target matching your device SoC and the supplied SDK. The SDK includes its QNN runtime libraries; no separate QNN installation or QNN path configuration is required.
