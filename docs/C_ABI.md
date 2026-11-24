# C ABI

`sdk/include/qwen3_tts.h` · `sdk/lib/libqwen3_tts.so` · Synthesize complete or streamed mono audio. Include `sdk/include/pandora_runtime.h` when configuring a Runtime explicitly.

## Build and link

Prepare the [device runtime](../README.md#prepare-the-device). In the same Python environment you will use below, install the bundled Runtime wheel and SDK as shown in [SDK installation](../sdk/README.md#install).

From the Demo root, compile against the shipped header and library; the library carries its QNN runtime:

```bash
runtime_dir=$(python -c "import pathlib,pandora_runtime; print(pathlib.Path(pandora_runtime.__file__).parent)")
cc -std=c99 -I sdk/include your_app.c -L sdk/lib -L"$runtime_dir" -Wl,--no-as-needed -l:libpandora_runtime.so.5 -Wl,--as-needed -Wl,-rpath,"$runtime_dir" -lqwen3_tts -Wl,-rpath,'$ORIGIN/sdk/lib' -o your_app
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
chunk's codes.
Fetching audio returns `Q3T_ERR_STATE` until start succeeds on that engine.
After cancellation, next_audio returns any remaining audio, then 0.
- If a request is rejected for invalid input or length, correct it and call `q3t_start` again
  while the Runtime is usable. If `q3t_next_audio` rejects the output buffer, supply a valid
  buffer and retry that call.
- A chunk generation or completion failure ends the utterance with `Q3T_END_ERROR`. The failed
  chunk leaves the caller's buffer, last returned codes, and returned-frame and chunk counts unchanged.
  Retry the utterance with a new `q3t_start` only while the Runtime is usable.
- If backend cleanup fails, keep the original diagnostic and report the failed teardown.

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

### Runtime

Use `PANDORA_RUNTIME_CONFIG_INIT` for the default settings. The public header defines
the supported modes, priorities, CPU placement and status fields. See [Runtime](../sdk/RUNTIME_API.md).

```c
pandora_runtime_config_t config = PANDORA_RUNTIME_CONFIG_INIT;
config.performance_mode = PANDORA_QNN_BALANCED;
pandora_runtime_t *runtime = NULL;
q3t_engine *model = NULL;
int rc = pandora_runtime_create(&config, &runtime);
if (rc == 0) rc = q3t_create_with_runtime("models", NULL, runtime, &model);
/* When rc is zero, submit requests and read audio. Check both cleanup results. */
int model_close_status = q3t_destroy_owned(&model);
int runtime_close_status = pandora_runtime_destroy(&runtime);
```

- Initialize status with its struct size and `PANDORA_RUNTIME_ABI_VERSION` before calling
  `pandora_runtime_get_status`.
- Pass a null Runtime to the model loader to use the SDK defaults. Models hold a reference to
  their Runtime settings and remain usable when a caller closes its Runtime handle early.
- Use a separate model slot initialized to null. On load failure, read `q3t_create_error`
  and `q3t_create_status`. On cleanup failure, the slot is retired and `q3t_create_error`
  reports the reason.

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
