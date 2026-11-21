# C ABI

`sdk/include/qwen3_tts.h` · `sdk/lib/libqwen3_tts.so` · Synthesize complete or streamed mono audio. Include `sdk/include/pandora_runtime.h` when configuring a Runtime explicitly.

## Build and link

Prepare the [device runtime](../README.md#1-install).

From the Demo root, compile against the shipped header and library; the library carries its QNN runtime:

```bash
cc -std=c99 -I sdk/include your_app.c -L sdk/lib -lqwen3_tts -Wl,-rpath,'$ORIGIN/sdk/lib' -o your_app
```

Keep `sdk/lib/qnn248/` adjacent to the matching prebuilt library. See [environment details](MODEL_SETUP.md#environment-details) for system requirements.

## Lifecycle

```text
q3t_create → q3t_get_info → q3t_default_request → q3t_start
    → q3t_next_audio until it returns 0 → q3t_get_stats → next request or q3t_destroy
```

A new start replaces a running utterance. Input rejected for an invalid argument or excessive
length leaves the end reason at `Q3T_END_NONE`. Runtime and execution failures report
`Q3T_END_ERROR`. Both paths leave zero audio frames and chunks and clear the previous
chunk's codes. If request start and Runtime execution release both fail, the release error takes
precedence and `q3t_last_error` reports both causes.
Fetching audio returns `Q3T_ERR_STATE` until start succeeds on that engine.
After cancellation, next_audio returns any remaining audio, then 0.
- If a request is rejected for invalid input or length, correct it and call `q3t_start` again
  while the Runtime is usable. If `q3t_next_audio` rejects the output buffer, supply a valid
  buffer and retry that call.
- A chunk generation or completion failure ends the utterance with `Q3T_END_ERROR`. The failed
  chunk leaves the caller's buffer, last returned codes, and returned-frame and chunk counts unchanged.
  Retry the utterance with a new `q3t_start` only while the Runtime is usable.
- If releasing the device power vote fails at the end of execution in `q3t_start` or
  `q3t_next_audio`, the Runtime records the failure and rejects new execution for every model
  that shares it. With an explicit Runtime, `pandora_runtime_get_status` exposes these failures
  through `deferred_vote_failures`. Copy the original error before further calls and wait for in-flight
  work to return. Close every attached model with `q3t_destroy_owned` and then destroy any
  caller-owned Runtime with `pandora_runtime_destroy`. Check every teardown result. Report any
  cleanup failure. After successful cleanup, create a fresh Runtime with `pandora_runtime_create`
  and load the models again before submitting more requests. If each model owns its Runtime,
  creating a new model after successful cleanup also creates a new Runtime.

## Functions

### Data structures and defaults

The header is the authoritative binary layout; zero-initialize output structs and do not change field order/types.

- `q3t_options`: `int reserved`, keep0; `NULL` at create uses defaults.
- `q3t_request`: UTF-8 `const char* text`, `speaker`, `language`; `uint32_t seed`; `int max_frames`.
  `q3t_default_request` sets textNULL, speaker`vivian`, language`chinese`, seed0, frames0.
  Text must be nonempty and already normalized. Known voice/language lists come from enumeration functions.
  `max_frames > 0` caps80ms frames; `<= 0` stops at the model's context bound. `auto` requires its package prefix.
- `q3t_info` integer fields: `sampling_rate`24000, `samples_per_frame`1920, `frames_per_chunk`8,
  `max_chunk_samples`15360, `context_rows`, `num_speakers`, `num_languages`.
- `q3t_stats` integers: `prefill_rows`, `frames`, `chunks`, `end_reason`; double millisecond fields:
  `ms_frontend`, `ms_talker_prefill`, `ms_talker_npu`, `ms_code_predictor_npu`, `ms_codec_npu`, `ms_host`.
  End reasons:0NONE/running,1EOS,2MAX_FRAMES,3CONTEXT,4CANCELLED,5ERROR (start, chunk generation or completion failed). Counters describe one utterance.

The SDK performs model-specific tokenization/generation/decoding. Normalization, sentence splitting, pacing,
WAV output and playback remain client/business policies. The C99 example uses fixed Chinese or English text and writes mono PCM16 WAV incrementally. Native API output is float32; WAV encoding is client policy.

### Model functions

| Function | Parameters, result and ownership |
| --- | --- |
| `const char* q3t_version(void)` | Static version string; never free. |
| `void q3t_default_options(q3t_options* o)` | Writes reserved0; NULL is ignored. |
| `void q3t_default_request(q3t_request* r)` | Writes the defaults above; NULL is ignored. |
| `q3t_engine* q3t_create(const char* model_dir, const q3t_options* opt)` | Synchronously loads an exact models.json package root containing the required model resources; there is no native automatic discovery. Return owned opaque handle or NULL. `opt` may be NULL; no active options. Keep model_dir valid through the call; caller owns its storage. |
| `int q3t_prepare_process(void)` | Retired compatibility function. Returns Q3T_ERR_UNSUPPORTED without changing host policy; detail uses q3t_create_error. See [protected loading](../docs/PROTECTED_LOADING.md). |
| `const char* q3t_create_error(void)` | Thread-local error text after failed create or quarantined model close, valid until a later create changes it. Copy if retaining; do not free. |
| `void q3t_destroy(q3t_engine* e)` | Releases all engine resources; accepts NULL. Destroy a non-NULL handle exactly once, after all other users return. |
| `const char* q3t_last_error(q3t_engine* e)` | Borrowed per-engine error message, changes on subsequent operations; NULL engine yields a literal message. Copy to retain; no free. |
| `int q3t_get_info(q3t_engine* e, q3t_info* info)` | Writes metadata to a caller-owned non-NULL output;0 or negative error. |
| `const char* q3t_speaker_name(q3t_engine* e, int i)` | Borrowed UTF-8 voice name for0..num_speakers-1; NULL out of range/NULL engine. Valid while engine exists. |
| `const char* q3t_language_name(q3t_engine* e, int i)` | Borrowed UTF-8 language name for0..num_languages-1; NULL out of range. Includes auto when available; same lifetime as voices. |
| `int q3t_start(q3t_engine* e, const q3t_request* r)` | Replaces prior utterance, synchronously tokenizes/prefills;0 or negative error. Request and strings must survive until return; model state copies needed data. NULL speaker/language use model defaults. Context overflow returns TOO_LONG; split text. |
| `int q3t_next_audio(q3t_engine* e, float* out, int cap)` | Requires successful start. Caller owns writable out of at least max_chunk_samples floats; cap is sample count, not bytes. Returns written samples>0,0 when complete, or negative error. Values are mono float audio at sampling_rate; last chunk may be short. Output remains caller-owned. |
| `int q3t_last_codes(q3t_engine* e, int32_t (*out)[16], int cap_frames)` | Returns total frames in the last chunk; copies min(cap_frames,total) rows. Capacity is frames, each16int32 codes. cap0 allows NULL to query the count; negative cap or NULL with positive cap returns ARG. Never treat a return larger than cap as the number written. |
| `int q3t_cancel(q3t_engine* e)` |0 or ARG for NULL; requests stop after current frame. Only function permitted concurrently with engine work; does not wait/join/destroy. |
| `int q3t_get_stats(q3t_engine* e, q3t_stats* st)` | Writes per-utterance metadata/timings to non-NULL caller storage;0 or negative error. |

### Runtime C ABI4

Include both installed headers. Initialize configuration with
`PANDORA_RUNTIME_CONFIG_INIT`; exact current size and ABI4 are required (no prefix
compatibility). Zero reserved fields. The Python Runtime table documents the same
nine accepted modes, normal-only priority, optional control override and unsupported
system_settings/explicit polling overrides. C enum IDs are in `pandora_runtime.h`.

```c
pandora_runtime_config_t cfg = PANDORA_RUNTIME_CONFIG_INIT;
cfg.qnn.performance_mode = PANDORA_QNN_BURST;
cfg.qnn.device_id = 0; /* immutable device selection; no fallback */
cfg.qnn_override_flags = PANDORA_QNN_OVERRIDE_RPC_CONTROL_LATENCY;
cfg.rpc_control_latency_us = 0; /* explicit zero, not an absent override */
pandora_runtime_t *runtime = NULL;
q3t_engine *model = NULL;
int rc = pandora_runtime_create(&cfg, &runtime);
if (rc == 0) rc = q3t_create_with_runtime("/path/to/models", NULL, runtime, &model);
/* Use existing request/audio functions if rc == 0. Always clean up owned slots. */
q3t_destroy_owned(&model);
pandora_runtime_destroy(&runtime);
```

- `pandora_runtime_create(config, &empty_slot)` validates and owns an immutable config.
- `pandora_runtime_get_status(runtime, &status)` requires initialized struct_size and
  abi_version4; returns submitted requirements and direct-QNN resource/vote counters.
  Polling reports the active preset (burst=9999 us, retained other modes=0). The process field reports this provider's submitted active-vote aggregate, not a driver-wide query; UINT32_MAX means unknown. See Python status scope and power limitations.
- `pandora_runtime_last_error()` returns borrowed thread-local error text until the next
  Runtime operation. Copy if retained. Runtime calls return0 or negative codes.
- `pandora_runtime_destroy(&slot)` requires all attached models closed; BUSY(-8)
  leaves the slot intact. Successful close nulls it; a null value is idempotent.
- `q3t_create_with_runtime(root, options, runtime, &empty_model_slot)` supports a NULL
  runtime for private defaults. The slot owns the handle before returning to the caller.
  Failure leaves it empty; detail is q3t_create_error, code is q3t_create_status().
- `q3t_destroy_owned(&model_slot)` nulls ownership before teardown; repeated close is
  safe for an empty slot. A nonzero close reports quarantine; the slot is retired and must not be reused. Read q3t_create_error for its thread-local detail. Use it for language bindings; legacy pointer-return create/void destroy remain.
- `q3t_get_protection_status(runtime, &status)` requires initialized struct_size and
  returns attached_models plus SDK-wide current resource bytes and cumulative lock failures. locked_bytes=UINT64_MAX is unobservable; do not present it as a byte count or per-model cleanup proof.

### CPU configuration and queries

CPU options have their own ABI1 and exact struct size. Runtime config requires ABI4 and its full current size; old Runtime ABI2/ABI3 configs are rejected without reading their missing CPU tail. The default initializer selects `PANDORA_CPU_AFFINITY_DEFAULT`. Set `cfg.cpu.policy=PANDORA_CPU_AFFINITY_INHERIT` to preserve host placement, or use EXPLICIT with a nonempty `uint32_t` CPU array and count. The Runtime copies and normalizes IDs during creation; the input array may then be released. Valid IDs are 0..1023, online and allowed. Invalid size/version/reserved/pointer/count/policy combinations fail with ARG. A complete default target must be available; it is never silently truncated.

Initialize CPU query outputs with `sizeof(output)` and `PANDORA_CPU_ABI_VERSION`:
- `pandora_runtime_get_cpu_config` returns Linux ID, present hardware count, packaged config version and default mask.
- `pandora_runtime_get_cpu_status` returns policy/profile, SDK worker observations and affinity failures. Static coverage fields describe the adapter scope; they are not independent inference qualification.
- `pandora_runtime_get_cpu_ids` selects ALLOWED, RESOLVED or DEFAULT lists.
- `pandora_runtime_get_cpu_thread` reads a live registered SDK worker's TID, role and kernel mask by index. It does not enumerate arbitrary process threads or identify backend ownership through TID differences.

Array queries accept `ids=NULL` with `*count=0` to query required length. Insufficient capacity updates count without writing array elements and returns ARG. Synchronize lifecycle and indexed queries; workers disappear when closed. See [Runtime diagnostics](RUNTIME_DIAGNOSTICS.md) for observation scope and unsupported settings.

Runtime ABI4 requires reserved_protection=0. The selected context and power client must use the same observed device/core. Malformed device configuration fails validation. A well-formed uint32 device ID absent from the queried QNN topology fails model load with Q3T_ERR_NPU (-3), an empty model owner slot and a device-unavailable diagnostic; it does not select device 0 instead. Status exposes requested device_id separately from actual execution_device_id, power_device_id, core_id and device_verified; unknown IDs use UINT32_MAX. No public core selection or Genie/HTP config path is added.

## Error codes

Calls that return a status use zero or a nonnegative count for success. On failure, `q3t_create` returns `NULL` and exposes the error through `q3t_create_error`. C++ exceptions stay inside the SDK.

| Code | Meaning | What the caller should do |
| --- | --- | --- |
| `Q3T_ERR_ARG` (-1) | Invalid pointer, option, capacity, name or text. | Correct the input and retry. |
| `Q3T_ERR_MODEL` (-2) | Invalid or incomplete model package. | Check the model root and verify the package. |
| `Q3T_ERR_NPU` (-3) | Vendor runtime failure. | Read the error detail and follow the recovery steps above. |
| `Q3T_ERR_STATE` (-4) | Invalid call order or state. | Check the request and handle lifecycle. |
| `Q3T_ERR_TOO_LONG` (-5) | Input exceeds the model context. | Split the text and start a new request. |
| `Q3T_ERR_INTERNAL` (-6) | SDK operation failed. | Read the error detail before retrying. |
| `Q3T_ERR_UNSUPPORTED` (-7) | Unsupported operation or configuration. | Use a supported configuration. |
| `Q3T_ERR_BUSY` (-8) | The Runtime still has attached models. | Close the attached models before destroying the Runtime. |
| `Q3T_ERR_AUTHORIZATION` (-9) | Device authorization failed. | Check LMS activation and the error detail. |

Runtime calls use the corresponding codes for invalid arguments, NPU failures, invalid state, SDK failures, unsupported settings and busy resources.

## Threads and ownership

Only cancel may run concurrently. Serialize every other call. Wait for the in-flight SDK call to return
and join the caller thread before destroying the engine.

Signal handlers must not invoke the SDK or throw across native calls. The C99 example installs handlers that only store a sig_atomic_t request, checks between synchronous calls,
and explicitly cleans up owned native handles. It does not configure SA_RESTART explicitly; synchronous native calls may delay cooperative stopping.
Creation first returns its handle to the owner, then the pending stop is acted on. SIGINT/SIGTERM return130/143;
SIGKILL cannot run application cleanup. Stopping may wait for the current native call. Test actual target-runtime
resource return instead of treating a missing PID or a closed message as proof.

The native SDK preserves host output descriptors and does not configure process-global logging.
Model resources are loaded automatically by the matching SDK.
The examples' diagnostic wrapper handles child output as business code; it does not change native API behavior.

Native handles belong to the provider and process that created them. Inherited models reject operations/close with STATE;
a child must spawn/exec before initializing a provider used in its parent. Caller
serializes ownership/status/teardown against concurrent use; cancel remains the
existing cross-thread exception. Close models before Runtime. No SDK global
signal policy, descriptor redirection, process scheduler or device reset is introduced.

When loading multiple SDK DSOs with the generic `pandora_runtime_*` names, resolve
the function table through each DSO's own handle; do not rely on global symbol
lookup to select a provider. This provider validates its Runtime identity before
using its state. Python performs the same library-binding check.

On quarantined close, the retired owner slot remains NULL but the complete native dependency graph stays retained. Do not retry a freed pointer, automatically recreate the provider, or report successful release. Python preserves this failure on repeated close. C callers retain the returned failure themselves; closing an already NULL slot has no new engineering result.

## Example

A complete C99 program is in [examples/c/synthesize.c](../examples/c/synthesize.c). It synthesizes Chinese or English text and writes mono PCM16 WAV incrementally. See the [build and run commands](../examples/README.md#c-example).
