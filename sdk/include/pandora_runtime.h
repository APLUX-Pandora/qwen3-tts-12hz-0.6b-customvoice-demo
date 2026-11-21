/* Pandora runtime configuration ABI v4 (exact-size validation). This provider is delivered by libqwen3_tts.
 * Handles are process-local and provider-local. Never pass a handle to another SDK provider.
 * Models retain the runtime; close attached models before destroying the caller handle.
 * No model handle may be inherited through fork. Defaults: QNN / burst / normal / device 0; protected model buffers are managed by the SDK. */
#ifndef PANDORA_RUNTIME_H
#define PANDORA_RUNTIME_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#if defined(_WIN32)
#define PANDORA_API __declspec(dllexport)
#else
#define PANDORA_API __attribute__((visibility("default")))
#endif
typedef struct pandora_runtime pandora_runtime_t;
enum { PANDORA_OK = 0, PANDORA_ERROR_ARGUMENT = -1, PANDORA_ERROR_BACKEND = -3,
       PANDORA_ERROR_STATE = -4, PANDORA_ERROR_INTERNAL = -6, PANDORA_ERROR_UNSUPPORTED = -7, PANDORA_ERROR_BUSY = -8 };
enum { PANDORA_BACKEND_QNN = 1 };
/* Existing candidate values remain stable. These are profile IDs, not voltage values. */
enum { PANDORA_QNN_BURST = 0, PANDORA_QNN_BALANCED = 1, PANDORA_QNN_SYSTEM_SETTINGS = 2,
       PANDORA_QNN_SUSTAINED_HIGH_PERFORMANCE = 3, PANDORA_QNN_HIGH_PERFORMANCE = 4,
       PANDORA_QNN_LOW_BALANCED = 5, PANDORA_QNN_HIGH_POWER_SAVER = 6,
       PANDORA_QNN_POWER_SAVER = 7, PANDORA_QNN_LOW_POWER_SAVER = 8,
       PANDORA_QNN_EXTREME_POWER_SAVER = 9 };
enum { PANDORA_PRIORITY_LOW = 0, PANDORA_PRIORITY_NORMAL = 100,
       PANDORA_PRIORITY_NORMAL_HIGH = 150, PANDORA_PRIORITY_HIGH = 200 };
typedef struct { uint32_t performance_mode; int32_t priority; uint32_t device_id; uint32_t reserved; } pandora_qnn_options_t;
#define PANDORA_RUNTIME_ABI_VERSION 4
#define PANDORA_CPU_ABI_VERSION 1
enum { PANDORA_CPU_AFFINITY_INHERIT=0, PANDORA_CPU_AFFINITY_DEFAULT=1, PANDORA_CPU_AFFINITY_EXPLICIT=2 };
typedef struct {
    uint32_t struct_size, abi_version, policy, cpu_count;
    const uint32_t *cpu_ids;
    uint32_t reserved[2];
} pandora_cpu_options_t;
#define PANDORA_CPU_OPTIONS_INIT {sizeof(pandora_cpu_options_t), PANDORA_CPU_ABI_VERSION, PANDORA_CPU_AFFINITY_DEFAULT, 0, 0, {0,0}}

enum { PANDORA_QNN_OVERRIDE_RPC_CONTROL_LATENCY = 1, PANDORA_QNN_OVERRIDE_RPC_POLLING_TIME = 2 };
typedef struct {
    uint32_t struct_size, abi_version, backend, reserved_protection;
    pandora_qnn_options_t qnn;
    /* ABI v2 append-only overrides. Flags distinguish explicit zero from preset defaults. */
    uint32_t qnn_override_flags, rpc_control_latency_us, rpc_polling_time_us, reserved;
    pandora_cpu_options_t cpu;
} pandora_runtime_config_t;
#define PANDORA_RUNTIME_CONFIG_INIT {sizeof(pandora_runtime_config_t), PANDORA_RUNTIME_ABI_VERSION, PANDORA_BACKEND_QNN, 0, {PANDORA_QNN_BURST, PANDORA_PRIORITY_NORMAL, 0, 0}, 0, 0, 0, 0, PANDORA_CPU_OPTIONS_INIT}
typedef struct {
    uint32_t struct_size, abi_version, performance_mode;
    int32_t priority;
    uint32_t reserved_protection, active_contexts, power_client_created, active_executions;
    uint64_t accepted_active_votes, accepted_release_votes;
    uint32_t rpc_control_latency_us, rpc_polling_time_us, process_rpc_polling_time_us, deferred_vote_failures;
    uint32_t device_id, execution_device_id, power_device_id, core_id, device_verified;
} pandora_runtime_status_t;
/* Qwen provider accepts exactly ABI4/current struct sizes; ABI2/ABI3 are rejected. Nine performance
 * modes apply to all directly executed QNN graphs. system_settings,
 * non-normal priority and explicit RPC polling are unsupported and return -7.
 * RPC control latency accepts uint32_t, None/preset=100 us; explicit zero is valid.
 * power/vote counters describe the direct-QNN client only. Burst requests RPC
 * polling 9999 us internally. process_rpc_polling_time_us is the last successfully
 * submitted aggregate of this provider; UINT32_MAX means unknown. It is not a
 * query of other SDKs or measured hardware state. Status reports submitted requirements,
 * never measured clocks or a guarantee of scheduling priority.
 * Caller serializes configuration/status/close against model create/destroy.
 * Native handles must never cross providers or fork. */
PANDORA_API const char *pandora_runtime_last_error(void);
PANDORA_API int pandora_runtime_create(const pandora_runtime_config_t *, pandora_runtime_t **out);
PANDORA_API int pandora_runtime_get_status(pandora_runtime_t *, pandora_runtime_status_t *);
PANDORA_API int pandora_runtime_destroy(pandora_runtime_t **);
enum { PANDORA_CPU_IDS_ALLOWED=0, PANDORA_CPU_IDS_RESOLVED=1, PANDORA_CPU_IDS_DEFAULT=2 };
enum { PANDORA_CPU_COVERAGE_MODEL_EXECUTION=2 };
enum { PANDORA_CPU_THREAD_MODEL=3, PANDORA_CPU_THREAD_RUNTIME=4, PANDORA_CPU_THREAD_POWER=5, PANDORA_CPU_THREAD_PROCESSOR=6 };
enum { PANDORA_CPU_PROFILE_NONE=0, PANDORA_CPU_PROFILE_RESERVED=1,
       PANDORA_CPU_PROFILE_603_8=2, PANDORA_CPU_PROFILE_603_6=3,
       PANDORA_CPU_PROFILE_702=4, PANDORA_CPU_PROFILE_FALLBACK=5 };
/* Separate ABI1 query; existing status sizes and reserved fields remain unchanged.
 * Detection fields are zero until default placement has been resolved.
 * default_mask is the full selected target; observed masks use get_cpu_thread. */
typedef struct {
    uint32_t struct_size, abi_version, linux_soc_id, present_cpu_count;
    uint64_t default_mask;
    char config_version[32];
} pandora_cpu_config_status_t;
PANDORA_API int pandora_runtime_get_cpu_config(pandora_runtime_t *, pandora_cpu_config_status_t *);
typedef struct {
    uint32_t struct_size, abi_version, policy, coverage;
    uint32_t supported_policies, backend_override_supported, active_workers, observed_threads;
    uint32_t verified_threads, profile_id, reserved[2];
    uint64_t affinity_failures;
} pandora_cpu_status_t;
typedef struct {
    uint32_t struct_size, abi_version;
    uint64_t tid;
    uint32_t scope, cpu_count, verified, reserved;
} pandora_cpu_thread_status_t;
/* CPU query structs use PANDORA_CPU_ABI_VERSION. Array queries accept NULL
 * with *count=0 to report required size. Insufficient capacity updates *count,
 * writes no array elements and returns ARGUMENT. Query each thread by index
 * only while model lifecycles are quiescent; records disappear on model close.
 * Observed masks are freshly read from the kernel, not config echoes. */
PANDORA_API int pandora_runtime_get_cpu_status(pandora_runtime_t *, pandora_cpu_status_t *);
PANDORA_API int pandora_runtime_get_cpu_ids(pandora_runtime_t *, uint32_t kind, uint32_t *ids, uint32_t *count);
PANDORA_API int pandora_runtime_get_cpu_thread(pandora_runtime_t *, uint32_t index, pandora_cpu_thread_status_t *, uint32_t *ids, uint32_t *count);
#ifdef __cplusplus
}
#endif
#endif
