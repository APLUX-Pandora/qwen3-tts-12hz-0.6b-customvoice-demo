"""Long text in any of the 10 languages: split into segments of one utterance each (one talker context), and join their
audio into one stream.

Why: one utterance holds the prefill rows plus one row per generated 80 ms frame in the talker context (CL 2048), i.e.
~560 Chinese characters at most. Longer text is split at sentence ends; every segment starts a new utterance (the
engine restores its prefix KV), so the context never fills up, and the speaker token keeps the voice.

Length unit (`units`, about one syllable; calibrated on 10 languages: 2.5-3.6 frames per unit for every language):
one per Chinese character, kana or Hangul syllable; for words in Latin, Cyrillic or Greek script the estimated
syllables (vowel groups, an all-caps acronym of <= 5 letters counts its letters).
Segments (sizes in units of the normalized text, digits already spelled out for Chinese):
  * the first one holds only the opening sentence(s), <= FIRST_MAX units: its prefill is one AR128 call, so the first
    audio chunk comes quickly, and its audio covers the next segment's start-up;
  * the others pack whole sentences up to SEG_MAX units. At SEG_MAX = 300 the slowest measured speaker / language
    (~3.6 frames per unit, ~1 text token per unit) fills ~70 % of the context. Japanese uses SEG_MAX_LANG = 150: at
    300 units the talker re-reads or skips a clause in about one of five long segments, at 150 none were seen;
  * sentence ends: 。！？!?… and a "." (or "...") followed by a space or the end of the paragraph, except after a
    known abbreviation, a single capital letter (an initial) or inside a number;
  * a sentence longer than the limit is split at ；：，、;:,, a run without any punctuation is cut hard at the limit
    (between words for space-separated scripts).
Joining: the leading silence of every segment after the first and the trailing silence of every segment are trimmed
to PAD_S, then a fixed pause is inserted according to how the segment ended (sentence / paragraph / comma / hard cut).
Audio that ends in silence is held back until the next audio arrives, so a segment's tail can still be trimmed.
"""
import re

import numpy as np

from text_norm import normalize

SR = 24000
FIRST_MAX, SEG_MAX = 50, 300
SEG_MAX_LANG = {"japanese": 150}      # per-language segment limit (units) where SEG_MAX is too long
CTX_BUDGET = 2016                     # talker CL 2048 minus the native-KV AR1 margin: prefill rows + frames <= this
PAUSE_S = {"para": 0.6, "sent": 0.3, "comma": 0.15, "hard": 0.0}
PAD_S, SIL_DB, WIN_S = 0.05, -45.0, 0.02

CJK = r"一-鿿㐀-䶿"
SYLLABIC = CJK + r"぀-ゟ゠-ヿ가-힣"       # one unit per character: CJK, hiragana, katakana, Hangul syllables
LETTERS = r"A-Za-zÀ-ÖØ-öø-ɏͰ-ϿЀ-ӿ"
WORD = re.compile(rf"[{LETTERS}]+(?:['’][{LETTERS}]+)*")
VOWELS = re.compile(r"[aeiouyàáâãäåæèéêëìíîïòóôõöøœùúûüýÿāăąēėęěīįōőūůűųаеёиоуыэюяαεηιουωάέήίόύώ]+")
SENT_END = "。！？!?…"
SOFT = "；：，、;:,"
CLOSE = "”’」』）》】)\"'"
# "." after these does not end a sentence (lower case, with their own dots)
ABBREV = ("mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "inc.", "ltd.",
          "co.", "no.", "fig.", "approx.", "dept.", "mt.", "z.b.", "bzw.", "usw.", "nr.", "mme.", "mlle.", "sra.",
          "srta.", "dra.", "sig.", "ecc.", "ca.", "p.ex.", "т.е.", "т.к.", "г.", "ул.")
ABBREV_RE = re.compile(r"(?:^|[\s(\"'«“])(?:" + "|".join(re.escape(a) for a in ABBREV) + r")$")
# frames ~= a + b * hanzi + c * comma pauses (fit on the FP reference sets, 300 utterances); other speakers: Uncle_Fu
RATE = {"serena": (5.0, 2.45, 6.2), "vivian": (6.3, 2.82, 6.1), "uncle_fu": (2.4, 3.36, 12.5)}
# other languages (calibration of 9 languages x 3-4 speakers): frames ~= 10 + 3.2 * units + 6 * soft pauses
RATE_UNITS = (10.0, 3.2, 6.0)


def hanzi(s):
    return len(re.findall(f"[{CJK}]", s))


def _word_units(w):
    if w.isupper() and len(w) <= 5:                              # acronym, read letter by letter
        return len(w)
    return max(1, len(VOWELS.findall(w.lower())))


def units(s):
    """length of a text in units (about one syllable each)"""
    return len(re.findall(f"[{SYLLABIC}]", s)) + sum(_word_units(w) for w in WORD.findall(s))


def est_frames(text, speaker, language="chinese"):
    if language.lower() == "chinese":
        a, b, c = RATE.get(speaker.lower(), RATE["uncle_fu"])
        return a + b * hanzi(text) + c * len(re.findall(r"[，、；：,;:]", text))
    a, b, c = RATE_UNITS
    return a + b * units(text) + c * len(re.findall(r"[，、；：,;:]", text))


def _sentences(p):
    """normalized paragraph -> sentences, each ending with its end punctuation and any closing quotes / brackets
    (a sentence keeps the whitespace in front of it)"""
    out, cur, i, n = [], "", 0, len(p)
    while i < n:
        ch = p[i]
        cur += ch
        i += 1
        if ch in SENT_END:
            while i < n and p[i] in SENT_END:
                cur += p[i]
                i += 1
            while i < n and p[i] in CLOSE:
                cur += p[i]
                i += 1
            out.append(cur)
            cur = ""
        elif ch == ".":
            j = i
            while j < n and p[j] == ".":                         # "..."
                j += 1
            k = j
            while k < n and p[k] in CLOSE:
                k += 1
            if (k >= n or p[k].isspace()) and (j > i or not _abbrev(cur)):
                cur += p[i:k]
                i = k
                out.append(cur)
                cur = ""
    if cur:
        out.append(cur)
    return [s for s in out if s.strip()]


def _abbrev(s):
    """s ends with "." that belongs to an abbreviation or an initial"""
    if ABBREV_RE.search(s.lower()):
        return True
    m = re.search(rf"(?:^|[^{LETTERS}])([{LETTERS}])\.$", s)
    return bool(m and m.group(1).isupper())


def _cut(part, limit):
    """index after which `part` reaches `limit` units: after a character (CJK, kana, Hangul) or after a word"""
    n, i = 0, 0
    while i < len(part):
        m = WORD.match(part, i)
        if m:
            n += _word_units(m.group())
            i = m.end()
        else:
            n += bool(re.match(f"[{SYLLABIC}]", part[i]))
            i += 1
        if n >= limit:
            return i
    return len(part)


def _pieces(s, limit):
    """a sentence longer than `limit` units -> pieces <= limit: at soft punctuation, else hard cut"""
    if units(s) <= limit:
        return [(s, None)]
    parts = re.findall(rf"[^{SOFT}]*[{SOFT}]+|[^{SOFT}]+$", s)
    out, cur = [], ""
    for part in parts:
        if cur and units(cur + part) > limit:
            out.append(cur)
            cur = ""
        while units(part) > limit:                               # no punctuation at all: hard cut
            k = _cut(part, limit)
            out.append(part[:k])
            part = part[k:]
        cur += part
    if cur:
        out.append(cur)
    return [(x, "comma" if x.rstrip()[-1] in SOFT else "hard") if i < len(out) - 1 else (x, None)
            for i, x in enumerate(out)]


def _para_space(prev, nxt):
    """paragraphs joined inside one segment: a space between them unless the join is Chinese / Japanese text or
    punctuation, which are written without spaces (Keeper. + On -> "Keeper. On", 。 + 如 -> "。如"; Hangul uses
    spaces)"""
    a, b = prev.rstrip()[-1:], nxt.lstrip()[:1]
    cjk = f"[{CJK}぀-ゟ゠-ヿ。！？；：，、…」』）》】]"
    return " " if a and b and not re.match(cjk, a) and not re.match(cjk, b) else ""


def split_text(text, language="chinese", first_max=FIRST_MAX, seg_max=None):
    """-> list of {"text", "hanzi", "units", "pause", "end"}: normalized segment text and the pause (s) to insert after
    it. Joining the segment texts (minus the comma added after a hard cut) gives back the normalized paragraphs,
    joined with a space where the script uses spaces.
    seg_max: segment limit in units (default: SEG_MAX_LANG for the language, else SEG_MAX)."""
    if seg_max is None:
        seg_max = SEG_MAX_LANG.get(language, SEG_MAX)
    sents = []                                                   # (text, end kind)
    for para in [p for p in re.split(r"\n+", str(text)) if p.strip()]:
        ss = _sentences(normalize(para, language))
        for i, s in enumerate(ss):
            if i == 0 and sents:                                 # the first sentence of a new paragraph
                s = _para_space(sents[-1][0], s) + s.lstrip()
            sents.append((s, "para" if i == len(ss) - 1 else "sent"))
    segs, cur, kind = [], "", None
    for s, end in sents:
        if not cur:
            s = s.lstrip()
        if not segs and units(cur + s) > first_max:              # the first segment is full or the sentence too long
            if cur:
                segs.append((cur, kind))
                cur = ""
                s = s.lstrip()
            else:                                                # opening sentence > first_max: its first piece
                head, cut = _pieces(s, first_max)[0]
                segs.append((head, cut))
                s = s[len(head):].lstrip()
        for piece, cut in _pieces(s, seg_max):
            if cur and units(cur + piece) > seg_max:
                segs.append((cur, kind))
                cur = ""
            cur += piece if cur else piece.lstrip()
            kind = cut or end
            if cut:                                              # a split sentence: close the segment at the cut
                segs.append((cur, kind))
                cur = ""
    if cur:
        segs.append((cur, kind))
    out = []
    for t, k in segs:
        t = t.strip()
        if not t:
            continue
        if k == "hard" and t[-1] not in SENT_END + SOFT:
            # a hard cut ends like a comma (else it is swallowed)
            t += "，" if re.match(f"[{SYLLABIC}]", t[-1]) else ","
        out.append({"text": t, "hanzi": hanzi(t), "units": units(t), "pause": PAUSE_S.get(k, 0.3), "end": k})
    if out:
        out[-1]["pause"] = 0.0
    return out


class Joiner:
    """Turns the per-segment chunk streams into one stream: trims segment edges, inserts the pauses."""

    def __init__(self, sr=SR):
        self.sr, self.win = sr, int(WIN_S * sr)
        self.pad = int(PAD_S * sr)
        self.held = np.zeros(0, np.float32)
        self.lead = False

    def _speech(self, w):
        """per-window speech mask (RMS above SIL_DB)"""
        n = len(w) // self.win
        if n == 0:
            return np.zeros(0, bool)
        r = np.sqrt((w[: n * self.win].reshape(n, self.win) ** 2).mean(1) + 1e-12)
        return 20 * np.log10(r) > SIL_DB

    def begin(self, trim_lead):
        self.lead = trim_lead
        self.spoke = False                                       # speech emitted in this segment yet

    def push(self, wav):
        """-> list of float32 arrays to emit now"""
        w = np.concatenate([self.held, np.asarray(wav, np.float32)])
        self.held = np.zeros(0, np.float32)
        if self.lead:                                            # drop the leading silence (keep PAD_S)
            m = self._speech(w)
            if not m.any():
                return []
            on = max(0, int(np.argmax(m)) * self.win - self.pad)
            w = _fade(w[on:], self.sr, fade_in=True) if on else w
            self.lead = False
        m = self._speech(w)
        self.spoke = self.spoke or bool(m.any())
        if self.spoke and len(m) and not m[-int(0.3 / WIN_S):].any():   # speech, then >= 0.3 s silence: maybe the tail
            self.held = w                                        # (a silent start is never held: no first-chunk delay)
            return []
        return [w]

    def end(self, pause_s):
        """segment finished: trim its trailing silence, append the pause"""
        w, self.held = self.held, np.zeros(0, np.float32)
        m = self._speech(w)
        if len(m) and m.any():
            off = min(len(w), (len(m) - int(np.argmax(m[::-1]))) * self.win + self.pad)
            w = _fade(w[:off], self.sr, fade_in=False)
        elif len(w):
            w = w[:0]
        out = [w] if len(w) else []
        if pause_s > 0:
            out.append(np.zeros(int(pause_s * self.sr), np.float32))
        return out


def _fade(w, sr, fade_in, ms=10):
    n = min(len(w), int(sr * ms / 1000))
    if n:
        w = w.copy()
        ramp = np.linspace(0, 1, n, dtype=np.float32)
        if fade_in:
            w[:n] *= ramp
        else:
            w[-n:] *= ramp[::-1]
    return w


if __name__ == "__main__":
    # usage: python3 demo/longtext.py [text_file [language]]   -> index, units, end kind, pause, start of the text
    import sys
    t = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else "第一句话。第二句话！"
    for i, s in enumerate(split_text(t, sys.argv[2] if len(sys.argv) > 2 else "chinese")):
        print(i, s["units"], s["end"], s["pause"], s["text"][:40])
