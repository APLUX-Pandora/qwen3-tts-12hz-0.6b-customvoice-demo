/*
 * qwen3_tts.h - Qwen3-TTS-12Hz-0.6B-CustomVoice text-to-speech on Qualcomm NPUs.
 * Model files use the AIDEM format and are loaded automatically by the matching SDK.
 * C ABI of libqwen3_tts.so. The NPU architecture is a property of the model files; the library itself is
 * architecture-neutral.
 *
 * The engine implements the model's own generation protocol: the text frontend (chat template, tokenizer, projected
 * text embeddings, prefill row layout with speaker and language tokens), the talker (28 layers, NPU, native KV, fixed
 * prefix KV, AR128 prefill + AR1 decode), its code0 sampler, the code predictor (5 layers, NPU, codes 1..15 of every
 * frame) and its sampler, the per-frame feedback into the talker, and the streaming codec decoder (RVQ on the CPU,
 * three NPU stages) that turns every 8 frames (80 ms each) into 0.64 s of 24 kHz audio.
 * Model computation runs synchronously on model-owned CPU workers; package loading performs file IO. q3t_next_audio waits for the next chunk; the caller
 * decides when to ask for it. Policies (text normalization, splitting long text, pauses between segments, pacing,
 * retries, UI) belong to the caller.
 *
 * Typical use (include <stdio.h> and <stdlib.h>; play is supplied by the caller):
 *   int speak(const char *model_dir, const char *text) {
 *       q3t_engine *e = q3t_create(model_dir, NULL);
 *       if (!e) {
 *           fprintf(stderr, "%s\n", q3t_create_error());
 *           return 1;
 *       }
 *       q3t_info info;
 *       q3t_request r;
 *       float *buf = NULL;
 *       int result = 1;
 *       if (q3t_get_info(e, &info) != Q3T_OK) {
 *           fprintf(stderr, "%s\n", q3t_last_error(e));
 *           goto cleanup;
 *       }
 *       buf = malloc(sizeof(*buf) * (size_t)info.max_chunk_samples);
 *       if (!buf) {
 *           fprintf(stderr, "Could not allocate the audio buffer\n");
 *           goto cleanup;
 *       }
 *       q3t_default_request(&r);
 *       r.text = text;
 *       r.speaker = "vivian";
 *       r.language = "chinese";
 *       if (q3t_start(e, &r) != Q3T_OK) {
 *           fprintf(stderr, "%s\n", q3t_last_error(e));
 *           goto cleanup;
 *       }
 *       int n;
 *       while ((n = q3t_next_audio(e, buf, info.max_chunk_samples)) > 0) play(buf, n);
 *       if (n < 0) {
 *           fprintf(stderr, "%s\n", q3t_last_error(e));
 *           goto cleanup;
 *       }
 *       q3t_stats stats;
 *       if (q3t_get_stats(e, &stats) != Q3T_OK) {
 *           fprintf(stderr, "%s\n", q3t_last_error(e));
 *           goto cleanup;
 *       }
 *       if (stats.end_reason == Q3T_END_EOS) {
 *           result = 0;
 *       } else if (stats.end_reason == Q3T_END_CONTEXT || stats.end_reason == Q3T_END_MAX_FRAMES) {
 *           fprintf(stderr, "Speech was truncated. Split the text into shorter segments.\n");
 *       } else {
 *           fprintf(stderr, "Speech ended before completion (reason %d).\n", stats.end_reason);
 *       }
 *   cleanup:
 *       free(buf);
 *       if (q3t_destroy_owned(&e) != Q3T_OK) {
 *           fprintf(stderr, "%s\n", q3t_create_error());
 *           result = 1;
 *       }
 *       return result;
 *   }
 *
 * One utterance holds its prefill rows plus one row per generated frame in the talker context (info.context_rows
 * rows: roughly 550 Chinese characters with their audio). Longer text must be split by the caller into several q3t_start calls.
 * Determinism: the same text, speaker, language and seed give the same audio (sampling uses the request's seed only).
 * One engine is not thread-safe; use it from one thread at a time. Exception: q3t_cancel may be called from any
 * thread.
 */
#ifndef QWEN3_TTS_H
#define QWEN3_TTS_H

#include <stdint.h>
#include "pandora_runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

#define Q3T_VERSION "1.0.0"

#if defined(__GNUC__)
#define Q3T_API __attribute__((visibility("default")))
#else
#define Q3T_API
#endif

/* return codes (>= 0 = success or a count) */
#define Q3T_OK 0
#define Q3T_ERR_ARG -1       /* bad argument (unknown speaker / language, empty text, NULL pointer, ...) */
#define Q3T_ERR_MODEL -2     /* model file missing / malformed / inconsistent */
#define Q3T_ERR_NPU -3       /* QNN failure */
#define Q3T_ERR_STATE -4     /* call not valid in the current state (e.g. q3t_next_audio before q3t_start) */
#define Q3T_ERR_TOO_LONG -5  /* the text's prefill rows do not fit the talker context: split the text */
#define Q3T_ERR_UNSUPPORTED -7 /* recognized option not supported by this provider */
#define Q3T_ERR_AUTHORIZATION -9 /* LMS denied, failed or unavailable; no fallback */
#define Q3T_ERR_BUSY -8        /* close models before their Runtime */
#define Q3T_ERR_INTERNAL -6  /* unexpected failure inside the library (e.g. out of memory) */

#define Q3T_NUM_CODEBOOKS 16 /* codes per frame: code0 from the talker, codes 1..15 from the code predictor */

typedef struct q3t_engine q3t_engine;

/* engine options (create time); NULL = defaults */
typedef struct {
    int reserved;        /* no options yet; keep 0 */
} q3t_options;

/* one utterance */
typedef struct {
    const char *text;        /* UTF-8, already normalized by the caller (digits spelled out, final punctuation, ...) */
    const char *speaker;     /* built-in speaker name, see q3t_speaker_name (e.g. "vivian") */
    const char *language;    /* language name, see q3t_language_name (e.g. "chinese"), or "auto": the model picks the
                                language from the text (needs the prefix of language auto in the model package; very
                                short texts may be read in the wrong language) */
    uint32_t seed;           /* sampling seed (talker and code predictor); default 0 */
    int max_frames;          /* stop after this many frames (80 ms each); <= 0 = until the talker context is full */
} q3t_request;

/* why the last utterance ended */
#define Q3T_END_NONE 0       /* still running */
#define Q3T_END_EOS 1        /* the talker produced the end token */
#define Q3T_END_MAX_FRAMES 2 /* request.max_frames reached */
#define Q3T_END_CONTEXT 3    /* talker context full */
#define Q3T_END_CANCELLED 4  /* q3t_cancel */
#define Q3T_END_ERROR 5      /* start, generation or completion checks failed */

typedef struct {
    int sampling_rate;       /* 24000 */
    int samples_per_frame;   /* 1920 (80 ms) */
    int frames_per_chunk;    /* 8: every q3t_next_audio returns up to 8 frames (fixed by the codec binaries) */
    int max_chunk_samples;   /* frames_per_chunk * samples_per_frame: the buffer size q3t_next_audio needs */
    int context_rows;        /* talker context budget per utterance: prefill rows + frames <= context_rows */
    int num_speakers;
    int num_languages;
} q3t_info;

/* per-utterance statistics (reset by q3t_start) */
typedef struct {
    int prefill_rows;        /* talker rows of the text (including the fixed prefix) */
    int frames;              /* frames in audio returned so far */
    int chunks;              /* chunks returned so far */
    int end_reason;          /* Q3T_END_* */
    double ms_frontend;      /* tokenizer + embedding rows (host) */
    double ms_talker_prefill;/* AR128 calls (NPU + host) */
    double ms_talker_npu;    /* AR1 calls, NPU execute */
    double ms_code_predictor_npu; /* AR2 + AR1 calls, NPU execute */
    double ms_codec_npu;     /* codec stages, NPU execute */
    double ms_host;          /* everything else on the host (samplers, feedback rows, KV writes, RVQ, ...) */
} q3t_stats;

Q3T_API const char *q3t_version(void);
/* Retired: returns Q3T_ERR_UNSUPPORTED and changes no host policy. */
Q3T_API int q3t_prepare_process(void);
Q3T_API void q3t_default_options(q3t_options *o);
Q3T_API void q3t_default_request(q3t_request *r);

/* Load the model package in model_dir: its models.json lists the resources. NULL on failure, see q3t_create_error(). */
Q3T_API q3t_engine *q3t_create(const char *model_dir, const q3t_options *opt);
Q3T_API const char *q3t_create_error(void);    /* last q3t_create failure (thread-local) */
Q3T_API void q3t_destroy(q3t_engine *e);
Q3T_API const char *q3t_last_error(q3t_engine *e);

Q3T_API int q3t_get_info(q3t_engine *e, q3t_info *info);
/* built-in speakers / languages by index (0 .. num-1); NULL when out of range. The languages start with "auto" when
   the model package supports it. Dialect speakers (eric: Sichuan, dylan: Beijing) speak their dialect when the
   language is "chinese" or "auto" (the model card's rule). */
Q3T_API const char *q3t_speaker_name(q3t_engine *e, int i);
Q3T_API const char *q3t_language_name(q3t_engine *e, int i);

/* Start an utterance: frontend + talker prefill from the fixed prefix KV. Any running utterance is dropped.
   Returns Q3T_OK, or < 0 (Q3T_ERR_TOO_LONG when the text does not fit the context).
   An input rejection (ARG or TOO_LONG) leaves Q3T_END_NONE. A Runtime or execution failure
   reports Q3T_END_ERROR. Both paths report zero audio frames and chunks. If request start and
   Runtime execution release both fail, the release error takes precedence and last_error
   reports both causes. */
Q3T_API int q3t_start(q3t_engine *e, const q3t_request *r);

/* Generate the next chunk: up to frames_per_chunk frames, decoded to audio. Writes float samples in [-1, 1] at
   sampling_rate. Returns the number of samples (> 0), 0 when the utterance has ended (see q3t_stats.end_reason;
   the last chunk before that may be shorter), or < 0. cap must be >= max_chunk_samples.
   If the output buffer is rejected, supply a valid buffer and retry this call. A generation or completion
   failure ends the request with Q3T_END_ERROR. Retry with a new q3t_start only while the Runtime is usable.
   If a device power vote fails to release during start or generation, the Runtime rejects further execution.
   Copy q3t_last_error before further calls, wait for in-flight work, destroy every attached model with
   q3t_destroy_owned, then use pandora_runtime_destroy for a caller-owned Runtime. Check the teardown results. */
Q3T_API int q3t_next_audio(q3t_engine *e, float *out, int cap);

/* Codes of the frames in the last returned audio chunk ([frames][16], code0 first). Returns the frame count.
   The codes remain available after reading the end marker and are cleared by a new start. */
Q3T_API int q3t_last_codes(q3t_engine *e, int32_t (*out)[Q3T_NUM_CODEBOOKS], int cap_frames);

/* End the running utterance after its current frame; the next q3t_next_audio returns the audio generated so far (if
   any), then 0 with end_reason Q3T_END_CANCELLED. The only call that may be made from another thread. */
Q3T_API int q3t_cancel(q3t_engine *e);

Q3T_API int q3t_get_stats(q3t_engine *e, q3t_stats *st);

/* Runtime configuration is ABI4/exact-size. Old q3t_options layout is unchanged.
 * Empty owner slots retain a created handle before language-level signal delivery.
 * Caller synchronizes create/status/close. Runtime destruction rejects attached models.
 * Handles are provider/process-local; initialize after spawn/exec, never reuse after fork. */
Q3T_API int q3t_create_with_runtime(const char *, const q3t_options *, pandora_runtime_t *, q3t_engine **);
Q3T_API int q3t_destroy_owned(q3t_engine **);
Q3T_API int q3t_create_status(void);
typedef struct {
    uint32_t struct_size, attached_models;
    uint64_t mapped_bytes, locked_bytes, lock_failures;
    /* Per-Runtime cumulative attempts, not license identifiers or success assertions. */
    uint64_t authorization_checks, key_provider_calls, decrypt_calls;
    uint64_t backend_initialization_attempts, quarantined_backend_failures;
} q3t_protection_status;
Q3T_API int q3t_get_protection_status(pandora_runtime_t *, q3t_protection_status *);

#ifdef __cplusplus
}
#endif

#endif /* QWEN3_TTS_H */
