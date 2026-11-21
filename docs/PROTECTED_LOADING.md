# Model loading

<a id="protected-model-loading"></a>

Model files use the AIDEM format and are loaded automatically by the matching SDK. Use the model directory described in [model setup](MODEL_SETUP.md).

Complete the [LMS activation check](../README.md#1-install) before running the application. Download models from the trusted source and run the explicit package verifier after downloading or updating them, as shown in model setup. Model loading failures are reported through the [Python API](../sdk/PYTHON_API.md#errors) or [C API](C_ABI.md#errors-and-lifecycle).

Close active streams and finish in-flight calls before closing the model, then close any caller-owned Runtime. A cleanup failure remains an error; do not treat retained resources as successfully released. The SDK preserves host signal handlers, output descriptors and process limits. See the API references for ownership and cancellation rules.
