# Model setup

## Device requirements

- A compatible Linux device with Aidlux LMS (`sudo lms check` returns true), drivers, DSP firmware and BSP/FastRPC support.
- Python 3.10–3.12 in the Demo environment (see [Install](../README.md#1-install)).
- The SDK includes its QNN runtime libraries. Do not install QNN separately or set QNN paths.

<a id="environment-details"></a>

### Native compatibility

The prebuilt native library requires **Linux AArch64**, GLIBC 2.34, GLIBCXX 3.4.30 and CXXABI 1.3.13 or newer. Python bindings require **CPython 3.10–3.12** and the NumPy dependency declared by the SDK. The device must provide compatible drivers, DSP firmware, device nodes, BSP/FastRPC communication and Aidlux LMS. These are compatibility requirements, not a promise that every device or Linux distribution supports every model target.

Keep the supplied `qnn248/` directory adjacent to `libqwen3_tts.so`, including when deploying the C kit. The SDK queries the actual HTP architecture and loads its matching package components. Missing or conflicting components fail explicitly, with no fallback to another installed QNN or CPU backend. Use one QNN backend installation per process; different SDK/QNN versions are not guaranteed to coexist in one process.

The system loader must still find `libaidlms.so`, `libcdsprpc.so`, `libstdc++.so.6`, `libatomic.so.1`, `libm.so.6`, `libgcc_s.so.1`, `libc.so.6` and the AArch64 loader. Compatible DSP C++ firmware libraries are also device prerequisites. Follow the BSP's supported system configuration; do not replace shared system libraries. ICU/Unicode data needed by the model are included in the native SDK.

## Targets

Pick the folder for your device's SoC:

| SoC | Target folder |
| --- | --- |
| QCS8550 | `qcs8550_qnn248` |
| QCS8625 | `qcs8625_qnn248` |
| QCS8275 | `qcs8275_qnn248` |
| QCS9075 | `qcs9075_qnn248` |

### Selecting a downloaded target

Pass a package path explicitly to installed SDK integrations, or `--models PATH` to examples/Web. The Python loader accepts a root containing `models.json` or a parent with exactly one immediate child package; an invalid or ambiguous path fails. It never downloads resources automatically.

The SDK selects the target for the detected SoC when multiple targets are installed.
QCS8275 can also use the equivalent QCS8625 target when its own target is unavailable.

[SDK integration](../sdk/README.md) · [Python API](../sdk/PYTHON_API.md) · [Runtime](../sdk/RUNTIME_API.md) · [C ABI](C_ABI.md).

## Download

Replace `<target-folder>` with the exact folder name in the table.

From the Demo root, in the activated environment, download the shared resources once and then one target:

```bash
hf download APLUX-Pandora/Qwen3-TTS-12Hz-0.6B-CustomVoice --local-dir models --exclude "targets/*" --exclude "media/*" --exclude README.md --exclude .gitattributes
hf download APLUX-Pandora/Qwen3-TTS-12Hz-0.6B-CustomVoice --local-dir models --include "targets/<target-folder>/*"
```

Run `hf auth login` first if the repository is private. Keep one target per model folder: to switch devices, move the old `targets/` folder out or download into a new folder.

When switching devices, run both download commands again with the new target. If you use a different model folder, pass it to `--local-dir` in both downloads and as the package argument to the verifier. For example, use `python models/verify_model_package.py models2 --target "<target-folder>"` for a package downloaded to `models2`. After both downloads finish, verify the package before using it. If verification fails, repeat both downloads and verify again.

```bash
python models/verify_model_package.py models --target "<target-folder>"
```

## Folder layout

After the download, `models/` looks like this:

```text
models/
  models.json
  SHA256SUMS
  NOTICE
  LICENSES/
  code_predictor/
  codec/
  talker/
    prefix-kvcache/
    prefix-kvcache-auto/
  text_frontend/
  targets/
    qcs8550_qnn248/
      codec_a.serialized.bin.aidem
      codec_b1.serialized.bin.aidem
      codec_b2.serialized.bin.aidem
      cp_shared.serialized.bin.aidem
      talker_shared.serialized.bin.aidem
```

The SDK reads `models.json`, checks that the shared resources and one complete target are present, and reports what is missing. `hf download` verifies each large file's checksum.

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| Private repository access denied | Run `hf auth login` with an account that has access to the repository. |
| Package files are missing or verification fails | Download the shared resources and all files for the selected target, then run the verifier above. |
| No complete target for the detected SoC | Download the shared resources and the target for your device. |
| Device activation fails | Follow [Prepare the device](../README.md#prepare-the-device) and check activation again. |
