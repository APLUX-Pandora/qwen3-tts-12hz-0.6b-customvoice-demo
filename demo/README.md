# demo

The web demo and the business layer of the TTS: everything around the model that is a policy rather than part of
the model (text normalization, splitting long text, joining the segments, pacing, the web page).

## Start

Create the project-local `.venv` and install dependencies using [installation](../README.md#1-install) first.

On the board, from the repository root (the model package of your chip, e.g. `models`, see
[../docs/MODEL_SETUP.md](../docs/MODEL_SETUP.md); the SDK library in `sdk/lib/`):

```bash
source .venv/bin/activate
export QWEN3_TTS_MODELS=models                                 # the model package of your chip
demo/run.sh --port 8765                                                  # foreground
setsid -f demo/run.sh --port 8765 > demo/web.log 2>&1 < /dev/null        # background
```

The launcher uses that project environment and resolves relative model paths from the repository root.
A missing environment is an error; it never falls back to system Python.

Open `http://<board-ip>:8765/`.

| Option / variable | Default | |
|---|---|---|
| `--models` | automatic / `QWEN3_TTS_MODELS` | exact models.json package root; overrides the environment |
| `--port`, `--host` | 8765, 0.0.0.0 | HTTP server |
| `QWEN3_TTS_MODELS` | `models/` | the model package (the directory with `models.json`) |
| `QWEN3_TTS_LIB` | installed package library | explicit .so override |

## The page

The page has two columns.

- **Left, input:** pick a speaker, a language and a seed. Below them, two text boxes:
  - **Sample** (read-only): a built-in text of about one minute in the selected language, the same short story in all 10 languages (`samples/`). **Play sample** plays it with the selected
    speaker, so any voice and language can be heard without typing.
  - **Your text**: type or paste text of any length and press **Run** (or Ctrl+Enter).

  Choose the explicit text language; it controls model conditioning and text rules.
  **Stop** (next to Play sample or Run) ends generation after the current frame; **Download wav** saves the whole
  audio (written by the server, the last 3 are kept in `demo/out/`). A hint appears when the speaker is not a native
  speaker of the language.
- **Right, output:** the browser schedules each audio chunk for continuous playback. The bars show the spectrum of the
  audio being played (low frequencies in the middle). Below them: the segment progress bar (segments done / total),
  the status line, and the statistics - time from the click to the first sound, audio length, generation time and RTF,
  playback gaps, number of chunks, and how far generation is ahead of playback.

On a narrow window the two columns are stacked.

The page schedules the first chunk with a 0.50 s startup buffer to absorb short variations in generation time.
This adds startup latency; longer supply interruptions still appear in the playback-gap counter.
The server statistics assume immediate playback and can therefore report supply gaps even when browser playback is continuous.
There is one NPU, so requests are served one at a time.

## Command line

`demo/tts.py` runs the same business layer without the browser:

```bash
source .venv/bin/activate
python demo/tts.py --text "Hello, this text to speech model runs entirely on the device." \
    --speaker ryan --language english --out-dir out
python demo/tts.py --file examples/text/long_zh.txt --speaker vivian --language chinese \
    --out-dir out
python demo/tts.py --set texts.jsonl --out-dir out    # jsonl: id, text, optional speaker, language
```

Use `--ahead-s 30` to set the application audio-ahead limit when needed.

Defaults: `--speaker aiden --language english --seed 1`, as on the page. It writes `<id>.wav` and `<id>_info.json`
(first-chunk latency, playback gaps assuming playback starts with the first chunk, RTF, per-segment statistics for long
text).

## HTTP API

| Request | Response |
|---|---|
| `GET /` | the page |
| `POST /tts` `{"text", "speaker", "language", "seed"}` | a binary stream of frames: 1 byte type + uint32 LE length + payload. Type 0: audio chunk, int16 LE mono 24 kHz; type 1: JSON statistics (end); type 2: error text; type 3: JSON progress (`start` with the request id and the number of segments, then one `segment` event per segment) |
| `GET /samples` | the built-in sample texts, `{language: text}` |
| `GET /wav/<id>` | the request's audio as a wav file |

A client that disconnects cancels its request: no new segment is started and the running one ends after its current
frame.

## Long text

`longtext.py` splits the normalized text at sentence ends. Lengths are counted in units of about one syllable: one
per Chinese character, kana or Hangul syllable, the estimated syllables of a word in Latin or Cyrillic script. The
first segment holds only the opening sentence(s) (at most 50 units, so the first sound comes quickly), the others pack
whole sentences up to 300 units, well within one utterance; Japanese segments hold up to 150 units (longer Japanese
segments sometimes re-read or skip a clause). Longer sentences are split at commas, a run without punctuation is cut.
Each segment is one utterance from the same voice; the silence at the joints is trimmed and a pause inserted
(sentence 0.3 s, paragraph 0.6 s, comma 0.15 s). The server stays at most 30 s of audio ahead of playback.

## Text normalization

`text_norm.py` runs before the tokenizer: whitespace, final punctuation, and for Chinese the reading of numbers
(dates, times, percentages, units, phone numbers digit by digit, ...). Self-test: `python demo/text_norm.py`.

## Files

| File | Content |
|---|---|
| `app.py` | Flask web server (`/`, `/tts`, `/samples`, `/wav/<id>`) |
| `tts.py` | business layer over the SDK: `TTS.speak()` (one utterance with statistics), `TTS.speak_long()` (any length) |
| `longtext.py` | segmentation, joining (silence trim, pauses), frame estimates |
| `text_norm.py` | rule-based text normalization |
| `index.html` | the page |
| `samples/<language>.txt` | the sample texts of the page (one per language, replaceable) |
| `run.sh` | starts `app.py` |

## Input errors and diagnostics

POST /tts requires a JSON object with a string text field. Non-object JSON or incorrectly typed fields return
HTTP 400 with an error message; an empty text retains the binary stream's error frame.
CLI startup filters stderr paths, private addresses and device license IDs. MT01_RAW_LOG optionally saves raw
stderr to a private 0600 file; keep it outside delivery directories. The HTTP stream contains neutral diagnostics.

## CPU placement


Long-text synthesis derives each segment seed as `(seed + zero_based_segment_index) % (2**32)`. The caller seed must still be an integer in `0..2**32-1`; invalid values are rejected before segmentation.
