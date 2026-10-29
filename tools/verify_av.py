"""Check the rendered clips against their own audio, the source episodes and every second of video.

Usage:
  python3 tools/verify_av.py SRC_DIR [model] [clip_id ...]

SRC_DIR holds the official episode files (ep26.mp4, ep28.mp4, ep29.mp4, see CLIPS.md).
The default model, Whisper large-v3, is deliberately not the one that made the subtitles
(medium.en), so the subtitle check is an independent second transcription of the final audio.

For every clip it measures:
  - subtitles: the SRT words against a fresh transcript of the clip's own audio, and whether
    each word is spoken while its cue is on screen (word times from a wav2vec 2.0 CTC model,
    which is neither Whisper nor the MMS_FA aligner that timed the subtitles)
  - edits: that the clip audio is the listed source ranges (cross-correlation against the
    episode), the audio level at every edit point (a pause, or the quietest point between two
    words), and the words each cut removes (that audio transcribed on its own)
  - visuals: the branded header and footer are identical in every frame, OCR of the on-screen
    name, role and hook, OCR of the video window every second (credits, handles, URLs or any
    other text), the speaker's face in frame, black or frozen video, and a contact sheet

Writes verification/report.json and verification/<id>.jpg. tools/build_docs.py turns the
report and the manual verdicts in verification/review.json into checks, VERIFICATION.md and
the review page. Needs faster-whisper, torch and torchaudio, opencv-python-headless, pillow,
ffmpeg and tesseract.
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "verification")
W, H = 1080, 1920
VID_Y, VID_H = 380, 1350          # video window, as in tools/render.py
CAP_Y = VID_H - 170               # centre of the caption line in the video window, as in tools/render.py
SR = 16000
FONT = os.path.join(ROOT, "assets", "fonts", "ReadexPro-Medium.ttf")
# YuNet face detector (OpenCV Zoo, MIT licence): finds profile and three-quarter faces that Haar misses
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
YUNET_SHA = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET = os.path.join(os.path.expanduser("~"), ".cache", "podcast-clip-pack", "face_detection_yunet_2023mar.onnx")

FILLERS = {"um", "uh", "er", "ah", "erm", "hmm", "mm", "mhm"}
# Spellings that differ between the subtitles and a raw transcript but are the same spoken words.
SAME = {"akasha": ["acacia"], "ok": ["okay"], "gonna": ["going", "to"], "wanna": ["want", "to"],
        "liquidize": ["liquidise"], "towards": ["toward"]}
# Text that must never appear on screen.
CREDIT = [r"@\w{2,}", r"www\.", r"https?", r"\.(com|net|io|xyz)\b", r"\bfollow\b", r"\bsubscribe\b",
          r"made by", r"edited by", r"created by", r"clipped by"]


# ---------------------------------------------------------------- helpers

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def audio(path, start=None, dur=None):
    cmd = ["ffmpeg", "-v", "fatal"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}"]
    cmd += ["-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    return np.frombuffer(subprocess.check_output(cmd), np.int16).astype(np.float32) / 32768


def transcribe(model, pcm, t0=0.0):
    segs, _ = model.transcribe(pcm, language="en", word_timestamps=True, beam_size=5,
                               condition_on_previous_text=False, vad_filter=True)
    return [{"s": round(t0 + w.start, 3), "e": round(t0 + w.end, 3), "w": w.word.strip()}
            for sg in segs for w in sg.words]


_CTC = {}


def ctc_words(pcm):
    """Words and their times heard by a CTC speech model (wav2vec 2.0 large, LibriSpeech 960 h, from
    torchaudio), decoded greedily. Its letters are tied to 20 ms frames, so its word times are what the
    on-screen timing is checked against: Whisper's word times drift by up to a second around pauses
    and fillers. It is a different model from the MMS_FA aligner that timed the subtitles."""
    import torch
    import torchaudio
    if "model" not in _CTC:
        bundle = torchaudio.pipelines.WAV2VEC2_ASR_LARGE_LV60K_960H
        _CTC["model"], _CTC["labels"] = bundle.get_model().eval(), bundle.get_labels()
    labels = _CTC["labels"]
    with torch.inference_mode():
        emission, _ = _CTC["model"](torch.tensor(pcm).unsqueeze(0))
    sec = len(pcm) / emission.size(1) / SR
    words, cur, prev = [], None, None
    for i, k in enumerate(emission[0].argmax(-1).tolist()):
        if k != prev and k != 0:                      # 0 is the CTC blank
            if labels[k] == "|":
                cur = None
            elif cur is None:
                cur = {"s": round(i * sec, 3), "e": round((i + 1) * sec, 3), "w": labels[k].lower()}
                words.append(cur)
            else:
                cur["w"] += labels[k].lower()
                cur["e"] = round((i + 1) * sec, 3)
        elif k == prev and cur is not None and labels[k] != "|":
            cur["e"] = round((i + 1) * sec, 3)
        prev = k
    return words


def tokens(words):
    """Normalised comparison tokens as (token, index of the original word)."""
    out = []
    for i, w in enumerate(words):
        t = w.lower().replace("\u2019", "'")
        t = re.sub(r"[\u2010-\u2015-]", " ", t)   # hyphens and dashes split compounds
        for p in t.split():
            p = re.sub(r"[^\w'.]", "", p).strip("'.").replace(".", "")   # "2.0" and "2 .0" compare equal
            p = re.sub(r"(?<=[a-z])iz(?=(e|es|ed|ing|ation|ations|er|ers)$)", "is", p)
            if not p or p in FILLERS:
                continue
            if out and (out[-1][0], p) in {("red", "belly"), ("red", "belly's")}:
                out[-1] = ("redbelly" + p[5:], out[-1][1])
                continue
            for q in SAME.get(p, [p]):
                out.append((q, i))
    return out


def join_compounds(a, b):
    """Write "stable coin" as "stablecoin" (and the like) when the other side has the closed form."""
    vocab = {t for t, _ in b}
    pairs = set(zip([t for t, _ in b], [t for t, _ in b][1:]))
    out = []
    for tok in a:
        if out and out[-1][0] + tok[0] in vocab and (out[-1][0], tok[0]) not in pairs:
            out[-1] = (out[-1][0] + tok[0], out[-1][1])
        else:
            out.append(tok)
    return out


def parse_srt(path):
    cues = []
    for block in open(path).read().strip().split("\n\n"):
        lines = block.strip().splitlines()
        a, b = lines[1].split(" --> ")
        cues.append({"n": int(lines[0]), "s": srt_sec(a), "e": srt_sec(b), "text": " ".join(lines[2:])})
    return cues


def srt_sec(x):
    h, m, s = x.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def segments(clip):
    return clip.get("segments") or [[clip["start"], clip["end"]]]


# ---------------------------------------------------------------- subtitles vs audio

def cue_words(cues):
    """The subtitle words in order, and the cue each one is in."""
    words, cue_of = [], []
    for ci, c in enumerate(cues):
        for w in c["text"].split():
            words.append(w)
            cue_of.append(ci)
    return words, cue_of


def compare(srt_words, heard):
    """Token lists for the subtitles and a transcript, and their word-by-word alignment."""
    a = tokens(srt_words)
    b = tokens([w["w"] for w in heard])
    a, b = join_compounds(a, b), join_compounds(b, a)
    return a, b, difflib.SequenceMatcher(None, [x[0] for x in a], [x[0] for x in b], autojunk=False)


def check_timing(cues, heard):
    """Whether each subtitle word is spoken while its cue is on screen: every word the CTC model hears
    the same as the subtitles must have its midpoint within 0.3 s of its cue."""
    srt_words, cue_of = cue_words(cues)
    a, b, sm = compare(srt_words, heard)
    inside, worst, matched, late = 0, 0.0, 0, []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            continue
        for k in range(i2 - i1):
            c = cues[cue_of[a[i1 + k][1]]]
            w = heard[b[j1 + k][1]]
            mid = (w["s"] + w["e"]) / 2
            off = max(c["s"] - mid, mid - c["e"], 0.0)
            inside += off <= 0.3
            worst = max(worst, off)
            matched += 1
            if off > 0.3:
                late.append({"t": round(mid, 2), "word": srt_words[a[i1 + k][1]], "cue": [c["s"], c["e"]]})
    return {"timing_in_cue": round(inside / max(matched, 1), 4), "timing_worst_s": round(worst, 2),
            "timing_words": matched, "timing_off": late, "ctc_text": " ".join(w["w"] for w in heard)}


def check_subs(cues, asr):
    srt_words, cue_of = cue_words(cues)
    a, b, sm = compare(srt_words, asr)
    diffs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        si = sorted({a[k][1] for k in range(i1, i2)})
        aj = sorted({b[k][1] for k in range(j1, j2)})
        if si:
            t = cues[cue_of[si[0]]]["s"]
        elif aj:
            t = asr[aj[0]]["s"]
        else:
            t = 0.0
        lo = si[0] if si else (a[i1][1] if i1 < len(a) else len(srt_words))
        hi = si[-1] + 1 if si else lo
        diffs.append({"t": round(t, 2),
                      "srt": " ".join(srt_words[k] for k in range(si[0], si[-1] + 1)) if si else "",
                      "asr": " ".join(asr[k]["w"] for k in range(aj[0], aj[-1] + 1)) if aj else "",
                      "context": " ".join(srt_words[max(0, lo - 4):hi + 4])})
    return {"match": round(sm.ratio(), 4), "srt_words": len(a), "asr_words": len(b), "diffs": diffs,
            "asr_text": " ".join(w["w"] for w in asr)}


def check_cues(cues, dur):
    """Structural SRT checks: numbering, order, no overlaps, inside the clip."""
    issues = []
    for i, c in enumerate(cues):
        if c["n"] != i + 1:
            issues.append(f"cue {c['n']} numbered out of order")
        if c["e"] <= c["s"]:
            issues.append(f"cue {c['n']} ends before it starts")
        if i and c["s"] < cues[i - 1]["e"]:
            issues.append(f"cue {c['n']} overlaps cue {cues[i - 1]['n']}")
        if c["e"] > dur + 0.05:
            issues.append(f"cue {c['n']} runs past the end of the clip")
    return issues


# ---------------------------------------------------------------- edits vs source

def ncc(sig, tpl):
    """Normalised cross-correlation of tpl against every offset of sig (valid region)."""
    n = len(sig) + len(tpl)
    f = np.fft.rfft(sig, n) * np.conj(np.fft.rfft(tpl, n))
    corr = np.fft.irfft(f, n)[:len(sig) - len(tpl) + 1]
    c2 = np.concatenate([[0], np.cumsum(sig.astype(np.float64) ** 2)])
    energy = np.sqrt((c2[len(tpl):] - c2[:-len(tpl)]) * np.sum(tpl.astype(np.float64) ** 2)) + 1e-9
    r = corr / energy
    k = int(np.argmax(r))
    return k, float(r[k])


def check_sync(clip_pcm, src_pcm, src_t0, segs, lead=0.0):
    """Find each segment's head and tail in the episode; error vs the listed timestamps in ms."""
    out, off = [], lead
    for i, (a, b, *_) in enumerate(segs):
        d = b - a
        L = min(3.0, d - 0.8)
        res = {"seg": i + 1, "from": a, "to": b}
        for name, ct, st in (("head", off + 0.35, a + 0.35), ("tail", off + d - 0.35 - L, b - 0.35 - L)):
            tpl = clip_pcm[int(ct * SR):int((ct + L) * SR)]
            s0 = st - 0.5 - src_t0
            sig = src_pcm[int(s0 * SR):int((s0 + L + 1.0) * SR)]
            k, r = ncc(sig, tpl)
            res[f"{name}_ms"] = round((s0 + k / SR - (st - src_t0)) * 1000, 1)
            res[f"{name}_corr"] = round(r, 3)
        out.append(res)
        off += d
    return out


def level_db(pcm, t, src_t0, ref):
    i = int((t - src_t0) * SR)
    win = pcm[max(0, i - int(0.015 * SR)):i + int(0.015 * SR)]
    rms = float(np.sqrt(np.mean(win ** 2)) + 1e-9)
    return round(20 * np.log10(rms / ref), 1)


def kept_words(cues, off, d):
    """Subtitle words of the range that starts at `off` in the clip (cues break at every jump cut)."""
    return [w for c in cues if off - 0.01 <= c["s"] < off + d - 0.01 for w in c["text"].split()]


def check_cuts(model, cues, src_pcm, src_t0, segs, lead=0.0):
    """Level at every edit point, the words either side of it, and what each cut leaves out.

    The audio a cut removes is transcribed on its own, so the list of removed words does not
    depend on Whisper's word timestamps (which can be a few hundred ms off). The kept side of
    each edit point is read from the subtitles, which are checked against the audio separately,
    and the word heard there when that side is transcribed on its own must be the same word."""
    frames = np.lib.stride_tricks.sliding_window_view(src_pcm, int(0.03 * SR))[::int(0.03 * SR)]
    ref = float(np.percentile(np.sqrt(np.mean(frames ** 2, axis=1)), 95)) + 1e-9

    def heard(x, y):
        pcm = src_pcm[max(0, int((x - src_t0) * SR)):int((y - src_t0) * SR)]
        return [w["w"] for w in transcribe(model, pcm)] if len(pcm) > 0.3 * SR else []

    def edge(t, kind, span=2.5):
        """The word a listener hears right after an "in" point or right before an "out" point: that
        side of the edit alone, with the render's 40 ms fade and a second of silence around it."""
        x, y = (t, t + span) if kind == "in" else (t - span, t)
        pcm = src_pcm[int((x - src_t0) * SR):int((y - src_t0) * SR)].copy()
        n = int(0.04 * SR)
        pcm[:n] *= np.linspace(0, 1, n) if kind == "in" else 1
        pcm[-n:] *= np.linspace(1, 0, n) if kind == "out" else 1
        pad = np.zeros(SR, np.float32)
        words = tokens([w["w"] for w in transcribe(model, np.concatenate([pad, pcm, pad]))])
        return (words[0][0] if kind == "in" else words[-1][0]) if words else ""

    opening = heard(segs[0][0] - 4, segs[0][0])
    closing = heard(segs[-1][1], segs[-1][1] + 4)
    gaps = [heard(b, segs[i + 1][0]) for i, (a, b, *_) in enumerate(segs[:-1])]
    bounds, cuts, off = [], [], lead
    for i, (a, b, *_) in enumerate(segs):
        d = b - a
        kept = kept_words(cues, off, d)
        before = opening if i == 0 else gaps[i - 1]
        after = closing if i == len(segs) - 1 else gaps[i]
        first, last = tokens(kept[:2]), tokens(kept[-2:])
        bounds.append({"seg": i + 1, "kind": "in", "src": a, "clip": round(off, 2),
                       "prev": before[-1] if before else "", "next": kept[0] if kept else "",
                       "heard": edge(a, "in"), "expect": first[0][0] if first else "",
                       "level_db": level_db(src_pcm, a, src_t0, ref)})
        bounds.append({"seg": i + 1, "kind": "out", "src": b, "clip": round(off + d, 2),
                       "prev": kept[-1] if kept else "", "next": after[0] if after else "",
                       "heard": edge(b, "out"), "expect": last[-1][0] if last else "",
                       "level_db": level_db(src_pcm, b, src_t0, ref)})
        off += d
        if i + 1 < len(segs):
            cuts.append({"clip": round(off, 2), "from": b, "to": segs[i + 1][0],
                         "removed_s": round(segs[i + 1][0] - b, 2), "removed": " ".join(gaps[i])})
    return bounds, cuts


# ---------------------------------------------------------------- visuals

def frames(path, fps=2):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={fps}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    k = 0
    while True:
        buf = p.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        yield k / fps, np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        k += 1
    p.wait()


def ocr(img, psm=11):
    """Words tesseract reads, as [(text, confidence, vertical centre in the image)]."""
    ok, png = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2GRAY))
    tsv = subprocess.run(["tesseract", "stdin", "stdout", "--psm", str(psm), "tsv"], input=png.tobytes(),
                         capture_output=True).stdout.decode(errors="ignore")
    out = []
    for line in tsv.splitlines()[1:]:
        f = line.split("\t")
        if len(f) == 12 and f[11].strip() and float(f[10]) >= 0:
            out.append((f[11].strip(), float(f[10]), int(f[7]) + int(f[9]) / 2))
    return out


def caption_at(cues, t):
    """Letters of the caption lines that can be on screen at t (a line stays up through a pause of up
    to 1.5 s after its cue ends, see tools/render.py)."""
    return "".join(re.sub(r"[^a-z]", "", c["text"].lower()) for c in cues if c["s"] - 0.1 <= t <= c["e"] + 1.6)


def in_caption(text, caption):
    """Whether OCR text is part of the caption on screen, allowing for the words OCR fuses or misreads
    ("Redbellyjdoesn" for "Redbelly doesn't")."""
    x = re.sub(r"[^a-z]", "", text.lower())
    if len(x) < 3:
        return False
    return max(difflib.SequenceMatcher(None, x, caption[i:i + len(x)]).ratio()
               for i in range(max(1, len(caption) - len(x) + 1))) >= 0.8


def face_detector(w, h):
    if not os.path.exists(YUNET) or sha256(YUNET) != YUNET_SHA:
        os.makedirs(os.path.dirname(YUNET), exist_ok=True)
        subprocess.run(["curl", "-sSLf", "-o", YUNET, YUNET_URL], check=True)
    if sha256(YUNET) != YUNET_SHA:
        sys.exit(f"unexpected checksum for {YUNET}")
    return cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.6, 0.3, 50)


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def check_visuals(path, clip, cues, dur, sheet_path):
    vocab = {norm(w) for c in cues for w in c["text"].split()}
    shots = list(frames(path))
    ref = shots[len(shots) // 2][1]
    head, foot = ref[:VID_Y], ref[VID_Y + VID_H:]
    static = 0.0
    other, credits, face_hits = [], [], 0
    fw, fh = W // 2, VID_H // 2
    det = face_detector(fw, fh)
    for t, f in shots:
        if 0.3 <= t <= dur - 0.6:          # skip the fade in and fade out
            static = max(static,
                         float(np.abs(f[:VID_Y].astype(np.int16) - head).mean()),
                         float(np.abs(f[VID_Y + VID_H:].astype(np.int16) - foot).mean()))
        win = f[VID_Y:VID_Y + VID_H]
        _, found = det.detect(cv2.cvtColor(cv2.resize(win, (fw, fh)), cv2.COLOR_RGB2BGR))
        face_hits += found is not None and len(found) > 0
        if abs(t - round(t)) < 1e-6:          # OCR the video window once a second
            for text, conf, y in ocr(win):
                if conf < 50:
                    continue
                if abs(y - CAP_Y) <= 60 and in_caption(text, caption_at(cues, t)):
                    continue                  # the burned-in caption line
                low = text.lower()
                if any(re.search(p, low) for p in CREDIT):
                    credits.append({"t": t, "text": text})
                # other caption words (OCR often fuses or clips them) are expected; anything else is listed
                parts = [x for x in norm(text).split() if len(x) >= 3]
                if conf >= 70 and parts and not all(any(x in v for v in vocab) for x in parts):
                    other.append({"t": t, "text": text})
    # on-screen text in the branded frame, read back from the rendered video
    foot_txt = " ".join(t for t, c, _ in ocr(np.ascontiguousarray(foot), psm=6) if c >= 40)
    head_txt = " ".join(t for t, c, _ in ocr(np.ascontiguousarray(head[150:]), psm=6) if c >= 40)
    tag_txt = " ".join(t for t, c, _ in ocr(np.ascontiguousarray(head[60:150, 560:]), psm=7) if c >= 0)
    fn, ft, fh = norm(foot_txt), norm(head_txt), norm(tag_txt)

    # black or frozen video inside the window
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-an", "-vf",
                        f"crop={W}:{VID_H}:0:{VID_Y},blackdetect=d=0.1:pix_th=0.10,freezedetect=n=-60dB:d=0.75",
                        "-f", "null", "-"], capture_output=True, text=True)
    black = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr)
    freeze = re.findall(r"freeze_start: ([\d.]+)", p.stderr)

    contact_sheet(shots, sheet_path)
    return {"frames": len(shots), "static_max_diff": round(static, 2),
            "footer_ocr": foot_txt, "header_ocr": head_txt, "tag_ocr": tag_txt,
            "name_ok": norm(clip["speaker"]) in fn, "role_ok": norm(clip["role"]) in fn,
            "hook_ok": norm(clip["hook"]) in ft, "episode_ok": f"episode {clip['episode']}" in fh,
            "credits": credits, "other_text": other,
            "face_pct": round(face_hits / len(shots), 4),
            "black": [[float(a), float(b)] for a, b in black], "freeze": [float(x) for x in freeze]}


def contact_sheet(shots, path, every=2.0, cols=6, tw=216):
    """One frame every `every` seconds, each with its clip time underneath."""
    picks = [(t, f) for t, f in shots if abs(t / every - round(t / every)) < 1e-6]
    th, lab = round(tw * H / W), 24
    rows = (len(picks) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 6, rows * (th + lab + 6) + 6), (14, 27, 35))
    d = ImageDraw.Draw(sheet)
    fnt = ImageFont.truetype(FONT, 15)
    for i, (t, f) in enumerate(picks):
        x, y = 6 + (i % cols) * (tw + 6), 6 + (i // cols) * (th + lab + 6)
        sheet.paste(Image.fromarray(f).resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x + 2, y + th + 3), f"{int(t) // 60:02d}:{int(t) % 60:02d}", font=fnt, fill=(217, 217, 217))
    sheet.save(path, quality=80, optimize=True)


# ---------------------------------------------------------------- main

def main():
    src_dir = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else "large-v3"
    only = set(sys.argv[3:])
    clips = json.load(open(os.path.join(ROOT, "clips.json")))
    os.makedirs(OUT, exist_ok=True)
    rpath = os.path.join(OUT, "report.json")
    report = json.load(open(rpath)) if os.path.exists(rpath) else {}
    report.update({"model": model_name, "timing_model": "wav2vec 2.0 large (torchaudio WAV2VEC2_ASR_LARGE_LV60K_960H)",
                   "tool": "tools/verify_av.py"})
    report.setdefault("clips", {})
    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    for c in clips:
        cid = c["id"]
        if only and cid not in only:
            continue
        mp4 = os.path.join(ROOT, "clips", f"{cid}.mp4")
        cues = parse_srt(os.path.join(ROOT, "subtitles", f"{cid}.srt"))
        segs = segments(c)
        lead = c.get("lead_in", 0.0)
        dur = sum(b - a for a, b, *_ in segs) + lead
        src = os.path.join(src_dir, f"ep{c['episode']}.mp4")
        lo, hi = segs[0][0], segs[-1][1]
        t0 = max(0.0, lo - 4)
        src_pcm = audio(src, t0, hi - lo + 8)
        clip_pcm = audio(mp4)
        print(f"== {cid}: transcribing the clip audio and the audio each cut removes with {model_name}", flush=True)
        asr = transcribe(model, clip_pcm)
        subs = check_subs(cues, asr)
        subs.update(check_timing(cues, ctc_words(clip_pcm)))
        bounds, cuts = check_cuts(model, cues, src_pcm, t0, segs, lead)
        print("   checking frames", flush=True)
        report["clips"][cid] = {
            "sha256": sha256(mp4),
            "srt_sha256": sha256(os.path.join(ROOT, "subtitles", f"{cid}.srt")),
            "subs": subs,
            "cue_issues": check_cues(cues, dur),
            "sync": check_sync(clip_pcm, src_pcm, t0, segs, lead),
            "bounds": bounds,
            "cuts": cuts,
            "visual": check_visuals(mp4, c, cues, dur, os.path.join(OUT, f"{cid}.jpg")),
        }
        json.dump(report, open(rpath, "w"), indent=1)
        r = report["clips"][cid]
        print(f"   subtitles {r['subs']['match']:.1%} match, {len(r['subs']['diffs'])} differences, "
              f"{r['subs']['timing_in_cue']:.1%} in cue; sync {[ (s['head_ms'], s['tail_ms']) for s in r['sync']]}; "
              f"static {r['visual']['static_max_diff']}; face {r['visual']['face_pct']:.0%}; "
              f"credits {r['visual']['credits']}; other {[o['text'] for o in r['visual']['other_text']]}", flush=True)


if __name__ == "__main__":
    main()
