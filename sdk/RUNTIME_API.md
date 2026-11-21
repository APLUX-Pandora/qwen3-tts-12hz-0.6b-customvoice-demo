# Pandora Runtime Python API v1

Runtime configures CPU affinity, QNN performance mode, QNN priority and the NPU device. Import `Runtime`, `CpuOptions`, and `QnnOptions` from the model SDK. Pass the configuration as `runtime=` when loading the model. Omit the argument or pass `None` to let the SDK create and manage the default Runtime, using CPU affinity `"default"`, burst performance, normal priority and device 0. `Runtime()` and `CpuOptions()` also select `"default"`; select `"inherit"` explicitly to follow host placement. Backend configuration is managed by the SDK; users do not prepare Genie or HTP configuration files.

## Configuration

| Option | Default | Values |
| --- | --- | --- |
| `CpuOptions.affinity` | `"default"` | `"inherit"` follows the application's CPU placement. `"default"` selects the SDK's recommended placement for the platform. You can also pass a nonempty collection of CPU IDs, such as `[3, 4]`, from the process's allowed set. |
| `QnnOptions.performance_mode` | `"burst"` | See the performance modes below. |
| `QnnOptions.priority` | `"normal"` | `"low"`, `"normal"`, `"normal_high"`, and `"high"`, in ascending order. |
| `QnnOptions.device_id` | `0` | A nonnegative uint32 device ID present on the target. On IQ9, device IDs 0 and 1 both use internal core 0. Unavailable devices fail explicitly without fallback. |

Active RPC control latency defaults internally to 100 microseconds. RPC polling and low-level voltage/DCVS/sleep settings are SDK-managed backend presets, not additional required user parameters. The common baseline is burst; adding power-saving modes is not required. Any additional supported modes and legacy overrides depend on the actual SDK version and platform.

| Performance mode | Values |
| --- | --- |
| Performance | `"burst"`, `"sustained_high_performance"`, `"high_performance"` |
| Balanced | `"balanced"`, `"low_balanced"` |
| Power saving | `"high_power_saver"`, `"power_saver"`, `"low_power_saver"`, `"extreme_power_saver"` |
| System managed | `"system_settings"` lets the system manage performance settings. |

Available QNN settings depend on the model and platform. See the model SDK documentation for supported values and any version-specific extensions. By default, the SDK raises an error when you request an unsupported setting.

## Python usage

Create the Runtime, pass it to the model loader, and release both objects explicitly. For packages with SoC/QNN variants, follow the model's download instructions to select the resources for your device. Pass the local model directory and the Runtime to the loader. The model loader and inference call depend on the SDK.

<!-- BEGIN PANDORA RUNTIME USAGE -->
```python
from pandora_qwen3_tts_12hz_0_6b_customvoice import CpuOptions, TTSModel, QnnOptions, Runtime

runtime = Runtime(
    cpu=CpuOptions(affinity="default"),
    qnn=QnnOptions(performance_mode="burst", priority="normal", device_id=0),
)
try:
    model = TTSModel.from_pretrained("models", runtime=runtime)
    try:
        result = model.synthesize(
            "Hello, welcome to text-to-speech.",
            speaker="ryan", language="en")
        print(result.sample_rate, result.duration_s)
    finally:
        model.close()
finally:
    runtime.close()
```
<!-- END PANDORA RUNTIME USAGE -->

Configuration is fixed for the lifetime of a Runtime. Create a new Runtime to use different settings. When your application creates the Runtime, finish any in-flight inference and close streams or caches first, then close the attached models and finally the Runtime. Runtime and model objects also support context managers. Each process creates its own Runtime from the model SDK it uses.

Choose another available NPU with `QnnOptions(device_id=1)` inside `Runtime(qnn=...)`; device_id is not a top-level Runtime argument. Parameter type/range checks happen at construction, while device availability may be checked at first model load for lazy initialization. A bool, float, negative or out-of-range value is invalid. Changing devices requires a new Runtime and model; there is no live context migration. The execution device and its power client must match. CPU placement and model SoC/QNN resource selection remain separate. Unsupported fields or mismatched native libraries must not be silently ignored; use the model SDK's stated supported interface/version.


The native Runtime resolves CPU defaults from its packaged, versioned platform configuration.
It reads Linux `/sys/devices/soc0/soc_id` and the hardware CPU list in
`/sys/devices/system/cpu/present`. For soc_id 603, eight present CPUs select `0xe0`
(CPU 5,6,7), and six present CPUs select `0x38` (CPU 3,4,5). soc_id 702 selects
`0x8c` (CPU 2,3,7); an unregistered ID selects `0xe0`. A read failure or an
unsupported present-CPU count for a registered ID is an error. Online CPU count,
process affinity and cpuset restrictions must not be used to reclassify hardware.
The complete target must be present, online and allowed; no silent mask truncation.
Python, C and Web share this native resolution. Explicit inherit and CPU collections
retain their semantics. Configuration identity, detected hardware count, selected
mask and observed thread masks are distinct state fields.

## Qwen3-TTS provider support and extensions

This provider supports normal priority only. Other recognized priorities, system_settings and explicit RPC polling fail explicitly. Previously supported performance modes remain available; the shared default is burst. Voltage/DCVS/sleep settings and backend configuration stay inside the SDK; there is no user Genie/HTP JSON input.

device_id is fixed for the Runtime lifetime. The SDK queries platform topology at model load, creates a restricted device handle, verifies its actual device/core and creates its power client for that same pair. Status distinguishes the request from observed execution/power device IDs; this is not a measured-clock or scheduling guarantee.

Model and Runtime close errors remain errors on repeated Python close. A quarantined backend is retained for safety and cannot be treated as a successful release.

The existing `QnnOptions.rpc_control_latency_us` override accepts a uint32 value; `None` uses the 100 microsecond active preset, and explicit zero is distinct from omission.
