# Weight-shared model resources

The delivered Talker graphs share one serialized context, and the Code Predictor graphs share another. Codec stages remain separate. These are model-package properties; applications use the same synthesis API for both ordinary and streamed output.

The root `models.json` identifies resources and graph roles, while `SHA256SUMS` supplies content checksums. Download common resources plus one complete target and verify the closure using [model setup](MODEL_SETUP.md). Do not edit graph bytes or substitute resources from another model/target.

Close active streams and finish in-flight calls before closing a model, then close any caller-owned Runtime. See [Python API](../sdk/PYTHON_API.md), [Runtime](../sdk/RUNTIME_API.md) and [protected loading](PROTECTED_LOADING.md).

Context sharing does not establish a speedup, a memory bound, or validation on another device. Conversion tools, private implementation, historical benchmarks and build inputs are maintained separately from the user SDK.
