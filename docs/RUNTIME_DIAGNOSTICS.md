# Runtime diagnostics and extensions

Use the public `Runtime`, `CpuOptions` and `QnnOptions` from this model SDK. The common reference is [Runtime](../sdk/RUNTIME_API.md).

`Runtime.status()` returns a copied snapshot of submitted QNN settings, direct-QNN active context/execution and vote counters, and SDK-wide protected-buffer counters. mapped_bytes is current SDK-wide resource bytes, locked_bytes is None when aggregate locked size is unobservable, and lock_failures is cumulative; these are not per-model release assertions. QNN fields describe requested settings, not measured clocks. All inference graphs execute through direct QNN. A loaded model has five contexts: two shared Talker/Code Predictor contexts and three independent Codec contexts. The direct-QNN counters cover model inference.

`QnnOptions.rpc_control_latency_us` accepts None (preset 100 microseconds) or integer 0..2**32-1; explicit zero differs from an omitted value. Explicit `rpc_polling_time_us`, non-normal priority and `system_settings` are unsupported by this provider and fail. Bool is not accepted as an integer. The SDK does not change host dump/debug or limit policies.

The default burst preset internally requests RPC polling for 9999 microseconds during active work. No extra user configuration is required. `rpc_polling_time_us` reports this Runtime's active preset (9999 for burst, 0 for the retained other modes). `process_rpc_polling_time_us` reports the last successfully submitted maximum among this provider's active Runtime requirements; it is 0 after the last active request releases its vote and None before a known submission or after an uncertain vendor failure. These are submitted settings, not a driver-wide readback. RPC polling affects the process: this provider coordinates its own Runtime objects, but cannot manage unknown votes from unrelated SDKs/DSOs. Explicit polling overrides remain unsupported.

`Runtime.cpu_status()` reports:
- `affinity`, the caller's immutable policy or normalized CPU tuple.
- `bound`: whether a native Runtime exists. Before binding, resolved/allowed/defaults are None and threads is empty.
- `linux_soc_id`, `present_cpu_count`, `config_version`, `default_mask` and `profile_id`: native default-resolution identity. Detection fields remain zero/empty for inherit or explicit policies.
- `allowed`, `resolved` and `defaults`: copied CPU ID lists captured/resolved at native Runtime creation, rather than live per-thread masks.
- `threads`: currently registered SDK-owned model/control workers, each with OS `tid`, scope, freshly read `cpus`, and `verified` comparison against the resolved placement.
- `active_workers`, `observed_threads`, `verified_threads` and `affinity_failures`: worker observations and errors.

The observation scope is SDK-owned execution/control workers. Backend descendant threads need separate lifecycle/inference sampling; these fields do not claim that all vendor threads have been sampled. Entries are removed before worker exit. Query while model lifecycles are quiescent: concurrent create/close may change indices between native calls and raise a query error. An idle Runtime with no workers is not an applied model affinity result.

The returned snapshots own no engine memory. Synchronize queries with Runtime/model close; close streams and finish in-flight calls, then models, then caller-owned Runtime. These handles cannot cross providers or fork.

## Initialization and stop signals

Applications own signal handlers. Native calls are synchronous: a pending stop may wait for the current native call to return. Do not call SDK functions from a signal handler. Close the request before destroying its model.

## This provider

Prepare the [runtime and models](../README.md#1-install) and activate the Demo environment before using the Python example. The target source requires a matching Runtime ABI4 native library. Retained ABI2/ABI3 binaries cannot implement it. See [environment details](../docs/MODEL_SETUP.md#environment-details) for platform and runtime compatibility requirements.

The direct-QNN inference provider accepts the nine performance modes other than `system_settings`. Model-wide priority is `normal` only. Unsupported settings raise `RuntimeNativeError`; no setting is silently ignored. Existing RPC control latency and read-only protection diagnostics are described in [Runtime diagnostics](../docs/RUNTIME_DIAGNOSTICS.md).

Each model owns a synchronous execution worker. Shared direct-QNN Runtime resources use a separate control worker with the same CPU policy. Python and Web calls wait for native completion. Cancellation is cooperative and does not permit destroy while a call is active. Applications retain ownership of signals, playback and HTTP.

Native CPU IDs are copied, sorted and deduplicated. This provider accepts IDs 0..1023 only when online and allowed. CLI entry points accept `--cpu-affinity default`, `inherit`, or a comma-separated collection such as `3,4,5`. Examples are hardware dependent. See [observed CPU state](../docs/RUNTIME_DIAGNOSTICS.md); configuration and worker unit tests do not establish vendor-thread/model-path qualification.

## Resource lifetime and current integration limit

Closing a model releases its contexts, protected model mappings and model worker.
An application-owned Runtime can retain its shared QNN backend, control worker
and backend buffers until `runtime.close()`. Close every attached model first,
then close the Runtime when the application no longer needs those shared resources.

A failure during backend teardown retains the complete dependency graph and reports failure; memory retention in that state is not normal successful close.

device_id is requested configuration. execution_device_id/core_id are returned by the actual selected QNN device query; power_device_id identifies the successfully created power client. device_verified is false until those checks complete. Unobserved IDs are None. These fields do not claim measured power or clocks.

## Unavailable execution device

The SDK checks uint32 type/range before binding. At model loading, a well-formed device ID absent from the actual QNN topology fails with a device-unavailable diagnostic; Python raises `TTSLoadError` with `native_code=-3` (Q3T_ERR_NPU). No model is returned and the SDK does not substitute device 0. Close the caller-owned Runtime after handling the failure.
