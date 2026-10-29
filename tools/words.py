"""Word-level transcript for each clip window, used to build the subtitles.

Usage:
  python3 tools/words.py SRC_DIR WORK_DIR [model] [clip_id ...]

Transcribes [start - 2s, end + 2s] of the episode audio with word timestamps,
applies the term glossary (Redbelly, RBNT, Tokeniser, ...) and the clip's own
manual `fixes` from clips.json, and writes WORK_DIR/<id>.words.json.
Times in the output are absolute episode seconds.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np
from faster_whisper import WhisperModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Single-token replacements applied to every clip.
GLOSSARY = [
    (r"^[Rr]ed-?[Bb]elly", "Redbelly"), (r"^[Tt]okeni[sz]er", "Tokeniser"),
    (r"^tokeniz", "tokenis"), (r"^Tokeniz", "Tokenis"),
    (r"^R\.?B\.?N\.?T\.?$", "RBNT"), (r"^acacia", "Acacia"),
]
# Two-token names the model splits ("red" + "belly").
PAIRS = {("red", "belly"): "Redbelly", ("red", "belly's"): "Redbelly's"}


def clean(word):
    for pat, rep in GLOSSARY:
        word = re.sub(pat, rep, word)
    return word


def merge(words):
    """Re-join hyphen/decimal fragments and split names, then apply the glossary."""
    out = []
    for w in words:
        if out and re.match(r"^[-.]\w", w["w"]):
            out[-1]["w"] += w["w"]
            out[-1]["e"] = w["e"]
            continue
        if out:
            key = (re.sub(r"\W", "", out[-1]["w"]).lower(), re.sub(r"[^\w']", "", w["w"]).lower())
            if key in PAIRS:
                tail = re.sub(r"^[\w']+", "", w["w"])
                out[-1]["w"] = PAIRS[key] + tail
                out[-1]["e"] = w["e"]
                continue
        out.append(dict(w))
    for w in out:
        w["w"] = clean(w["w"])
    return out


def apply_fixes(words, fixes):
    """Phrase-level corrections checked against the audio: {"from": "a b", "to": "c d"}.

    An optional "s" gives the time the phrase actually starts in the audio, for the few
    words whose Whisper timestamp lands on the wrong side of an edit point."""
    for fx in fixes:
        src, dst = fx["from"].split(), fx["to"].split()
        i = 0
        while i <= len(words) - len(src):
            if [w["w"] for w in words[i:i + len(src)]] == src:
                s, e = fx.get("s", words[i]["s"]), words[i + len(src) - 1]["e"]
                step = (e - s) / len(dst)
                new = [{"s": round(s + k * step, 3), "e": round(s + (k + 1) * step, 3), "w": t} for k, t in enumerate(dst)]
                if len(dst) == len(src) and "s" not in fx:
                    new = [dict(words[i + k], w=t) for k, t in enumerate(dst)]
                words[i:i + len(src)] = new
                i += len(dst)
            else:
                i += 1
    return words


def load_audio(src, start, dur):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", src,
                                   "-ac", "1", "-ar", "16000", "-f", "s16le", "-"])
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def main():
    src_dir, work = sys.argv[1], sys.argv[2]
    model_name = sys.argv[3] if len(sys.argv) > 3 else "medium.en"
    only = set(sys.argv[4:])
    clips = json.load(open(os.path.join(ROOT, "clips.json")))
    cache = {}

    def model():
        if "m" not in cache:
            cache["m"] = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4)
        return cache["m"]
    for c in clips:
        if only and c["id"] not in only:
            continue
        segs_cfg = c.get("segments") or [[c["start"], c["end"]]]
        lo, hi = segs_cfg[0][0], segs_cfg[-1][1]
        t0 = max(0.0, lo - 2)
        raw_path = os.path.join(work, f"{c['id']}.raw.json")
        raw = json.load(open(raw_path)) if os.path.exists(raw_path) else None
        if not raw or raw["t0"] > lo or raw["t1"] < hi:
            segs, _ = model().transcribe(load_audio(os.path.join(src_dir, f"ep{c['episode']}.mp4"), t0, hi - lo + 4),
                                         language="en", word_timestamps=True, beam_size=5,
                                         # no initial_prompt: with one, Whisper silently dropped
                                         # 20-60 s of speech in several windows
                                         condition_on_previous_text=False, vad_filter=True)
            raw = {"t0": lo, "t1": hi, "words": [{"s": round(t0 + w.start, 3), "e": round(t0 + w.end, 3), "w": w.word.strip()}
                                                 for sg in segs for w in sg.words]}
            json.dump(raw, open(raw_path, "w"))
        words = apply_fixes(merge(raw["words"]), c.get("fixes", []))
        json.dump(words, open(os.path.join(work, f"{c['id']}.words.json"), "w"), indent=0)
        print(f"== {c['id']}")
        for a, b, *_ in segs_cfg:
            print(f"  [{a:.2f}-{b:.2f}] " + " ".join(w["w"] for w in words if a - 0.05 <= w["s"] and (w["s"] + w["e"]) / 2 <= b))


if __name__ == "__main__":
    main()
