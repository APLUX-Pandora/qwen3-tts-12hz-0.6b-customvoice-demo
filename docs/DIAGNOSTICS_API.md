# Read-only synthesis diagnostics

These extensions support the Demo's business metrics; synthesis still uses the public TTSModel methods.

- model.languages returns a tuple of supported text-language codes.
- model.info is an immutable mapping copied at initialization: sampling_rate, samples_per_frame, frames_per_chunk, max_chunk_samples, context_rows, num_speakers, num_languages. It owns no model memory.
- model.stats() returns a copied snapshot of the most recently observed native request statistics. frames, chunks and prefill_rows are counts; timing fields use milliseconds; end_reason is running/eos/max_frames/context/cancelled/error. Values describe generation, not browser playback or a performance guarantee. Query from the application's serialized request thread; no concurrent snapshot guarantee is made.
- model.sample_rate is the model's actual output sampling rate; model.sdk_version identifies the loaded native library. Neither is a second inference entry.

TTSStateError/busy rules of the synthesis API still apply. Runtime diagnostics belong to the Runtime reference.
