"""Render the Redbelly Insights clip pack.

Usage:
  python3 tools/render.py SRC_DIR WORK_DIR [--subs-only] [clip_id ...]

SRC_DIR holds the official episode files (ep25.mp4 ... ep29.mp4, see
CLIPS.md). WORK_DIR holds per-clip word timings produced by
tools/words.py. Output goes to clips/ and subtitles/ in the repo.
--subs-only rewrites the SRT files from the same word timings without re-encoding.
"""
import json
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import facetrack

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1080, 1920
VID_Y, VID_W, VID_H = 380, 1080, 1350   # 4:5 video window
FPS = 30
FONT_DIR = os.path.join(ROOT, "assets", "fonts")      # Readex Pro, the Redbelly brand typeface (OFL)
LOGO = os.path.join(ROOT, "assets", "redbelly-logo.png")  # official horizontal negative logo
# Redbelly brand palette (redbelly.network/brand)
RED = (255, 80, 80)          # #FF5050
NAVY = (40, 58, 70)          # #283A46
NAVY_D = (20, 37, 48)        # #142530
GREY_L = (217, 217, 217)     # #D9D9D9
WHITE = (255, 255, 255)


def font(weight, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, f"ReadexPro-{weight}.ttf"), size)


def wrap(draw, text, fnt, width):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def frame_png(clip, path):
    """Static frame: brand background, official logo, episode tag, hook, name and role."""
    img = Image.new("RGB", (W, H), NAVY_D)
    # header: navy to dark navy with a soft brand-red glow from the top-left
    head = Image.new("RGB", (W, VID_Y), NAVY_D)
    px = head.load()
    for y in range(VID_Y):
        for x in range(0, W, 2):
            r = ((x / W) ** 2 + (y / VID_Y) ** 2) ** 0.5
            glow = max(0.0, 1 - r / 1.1) ** 2 * 0.45
            base = 1 - y / VID_Y
            c = tuple(int(NAVY_D[i] + (NAVY[i] - NAVY_D[i]) * base + (RED[i] - NAVY_D[i]) * glow) for i in range(3))
            px[x, y] = c
            if x + 1 < W:
                px[x + 1, y] = c
    img.paste(head, (0, 0))
    d = ImageDraw.Draw(img)

    logo = Image.open(LOGO).convert("RGBA")
    lh = 58
    logo = logo.resize((round(logo.width * lh / logo.height), lh), Image.LANCZOS)  # keep aspect ratio
    img.paste(logo, (64, 78), logo)
    tag = f"INSIGHTS  ·  EPISODE {clip['episode']}"
    tf = font("Medium", 26)
    tw = d.textlength(tag, font=tf)
    d.text((W - 64 - tw, 92), tag, font=tf, fill=GREY_L)

    size = 66
    while True:
        hook_f = font("Medium", size)
        lines = wrap(d, clip["hook"], hook_f, W - 128)
        if len(lines) <= 2 or size <= 50:
            break
        size -= 2
    y = 178 if len(lines) == 2 else 214
    for ln in lines[:2]:
        d.text((64, y), ln, font=hook_f, fill=WHITE)
        y += round(size * 1.18)

    # name and role under the video
    ny = VID_Y + VID_H + 26
    d.rectangle([64, ny + 8, 71, ny + 90], fill=RED)
    d.text((94, ny), clip["speaker"], font=font("Medium", 44), fill=WHITE)
    d.text((94, ny + 56), clip["role"], font=font("Regular", 30), fill=GREY_L)
    img.save(path)


# ---------------------------------------------------------------- captions

def ass_time(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def srt_time(t):
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def chunk(words, max_chars=24, max_words=5):
    """Group words into short caption lines, breaking at punctuation and pauses."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x["w"] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["s"] - w["e"]) if nxt else 9
        nxt_len = len(text) + 1 + len(nxt["w"]) if nxt else 0
        if (not nxt or nxt.get("cut") or nxt.get("br") or re.search(r"[.?!,;:]$", w["w"]) and len(cur) >= 2 or gap > 0.45
                or len(cur) >= max_words or nxt_len > max_chars):
            out.append(cur)
            cur = []
    return out


def write_subs(words, ass_path, srt_path, sub_y, dur):
    chunks = chunk(words)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Readex Pro SemiBold,62,&H00FFFFFF,&H00FFFFFF,&H00302514,&H64302514,0,0,0,0,100,100,0,0,1,6,2,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    hi = "{\\c&H5050FF&}"   # Redbelly red #FF5050 (ASS colours are BGR)
    norm = "{\\c&HFFFFFF&}"
    ev, srt = [], []
    for ci, c in enumerate(chunks):
        c_end = c[-1]["e"]
        nxt = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else None
        # through a pause of up to 1.5 s the line stays up with its last word lit until the next
        # line starts ("blockchain ... um ... is pretty important")
        if nxt is not None and nxt - c_end < 1.5:
            c_end = nxt
        # SRT cues never overlap: hold each line 150 ms after its last word, but end it
        # no later than the next line starts (overlapping cues are rejected or stacked by some platforms)
        s_end = min(c[-1]["e"] + 0.15, dur)
        if nxt is not None:
            s_end = min(s_end, nxt)
        srt.append(f"{ci + 1}\n{srt_time(c[0]['s'])} --> {srt_time(s_end)}\n"
                   + " ".join(w["w"] for w in c) + "\n")
        for wi, w in enumerate(c):
            s = w["s"] if wi else c[0]["s"]
            e = c[wi + 1]["s"] if wi + 1 < len(c) else c_end
            txt = " ".join((hi + x["w"] + norm) if j == wi else x["w"] for j, x in enumerate(c))
            ev.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Cap,,0,0,0,,{{\\pos({W // 2},{sub_y})}}{txt}")
    open(ass_path, "w").write(header + "\n".join(ev) + "\n")
    open(srt_path, "w").write("\n".join(srt))


def speech(src, lo, hi, sr=16000):
    """Mono audio of [lo, hi] in the episode, to settle which side of an edit a word is on."""
    raw = subprocess.check_output(["ffmpeg", "-v", "fatal", "-ss", f"{lo:.3f}", "-t", f"{hi - lo:.3f}", "-i", src,
                                   "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"])
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def in_segment(w, a, b, pcm, t0, sr=16000):
    """Whisper word times can be a few hundred ms off and edit points sit in pauses, so a word
    that straddles an edit point belongs to the side that holds most of its sound energy."""
    if w["e"] <= a or w["s"] >= b:
        return False
    if w["s"] >= a and w["e"] <= b:
        return True
    energy = lambda x, y: float(np.sum(pcm[int((x - t0) * sr):int((y - t0) * sr)] ** 2)) if y > x else 0.0
    inside = energy(max(w["s"], a), min(w["e"], b))
    return inside > energy(w["s"], w["e"]) - inside


_ALIGNER = {}
# Numbers in the subtitles, as the aligner should hear them
SPOKEN = {"2019": "twenty nineteen", "2.0": "two point o"}


def spoken(word):
    """Letters the aligner listens for in a subtitle word ("double-spend," -> double spend)."""
    w = word.replace("\u2019", "'")
    for k, v in SPOKEN.items():
        w = w.replace(k, f" {v} ")
    w = re.sub(r"[-\u2010-\u2015]", " ", w).lower()
    return [p for p in re.sub(r"[^a-z' ]", "", w).split() if p.strip("'")]


def align(words, pcm, sr=16000):
    """Start and end (seconds into pcm) of each word, by CTC forced alignment of the subtitle text
    with torchaudio's MMS_FA model. Whisper's own word times can be half a second off around
    pauses and fillers ("blockchain, um, is"); the aligner finds where each word is spoken."""
    import torch
    import torchaudio
    import torchaudio.functional as F
    if "model" not in _ALIGNER:
        bundle = torchaudio.pipelines.MMS_FA
        _ALIGNER["model"], _ALIGNER["dict"] = bundle.get_model().eval(), bundle.get_dict()
    model, index = _ALIGNER["model"], _ALIGNER["dict"]
    tokens, owner = [], []                   # letter ids, and the word each letter belongs to
    for i, w in enumerate(words):
        for c in "".join(spoken(w["w"])):
            tokens.append(index[c])
            owner.append(i)
    if not tokens:
        return [None] * len(words)
    with torch.inference_mode():
        emission, _ = model(torch.tensor(pcm).unsqueeze(0))
    path, score = F.forced_align(emission, torch.tensor([tokens], dtype=torch.int32), blank=0)
    sec = len(pcm) / emission.size(1) / sr
    out = [None] * len(words)
    for span, i in zip(F.merge_tokens(path[0], score[0].exp()), owner):
        a, b = span.start * sec, span.end * sec
        out[i] = (min(out[i][0], a), max(out[i][1], b)) if out[i] else (a, b)
    return out


def clip_words(allw, segs, pcm, t0, lead=0.0):
    """Words of each range on the output timeline, timed by forced alignment against that range's
    audio; "cut" starts a new caption line at each jump cut."""
    words, offset = [], lead
    for a, b, *_ in segs:
        mine = [w for w in allw if in_segment(w, a, b, pcm, t0)]
        spans = align(mine, pcm[int((a - t0) * 16000):int((b - t0) * 16000)])
        for k, (w, span) in enumerate(zip(mine, spans)):
            s, e = (a + span[0], a + span[1]) if span else (max(a, w["s"]), min(b, w["e"]))
            words.append(dict(w, s=s - a + offset, e=e - a + offset, cut=k == 0))
        offset += b - a
    return words


# ---------------------------------------------------------------- video

def probe(src):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "csv=p=0", src]).decode()
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def crop_expr(plan):
    expr = str(plan[-1][1])
    for i in range(len(plan) - 2, -1, -1):
        expr = f"if(lt(t,{plan[i + 1][0]:.3f}),{plan[i][1]},{expr})"
    return expr


def graph(clip, segs, lo, cw, ch, y0, plans, ass, bg_dur, lead=0.0):
    """filter_complex for: per-segment trim + face-tracked square crop, concat, frame overlay, captions.
    `lead` seconds of silence open the clip on the speaker's first frame, before the first word."""
    parts, aparts, vlabels, alabels = [], [], [], []
    for i, (seg, plan) in enumerate(zip(segs, plans)):
        a, b = seg[:2]
        d = b - a
        # optional third value: first usable video frame (skips a cutaway away from the speaker
        # by holding that frame for the first few hundred ms; audio is untouched)
        va = seg[2] if len(seg) > 2 else a
        pad = va - a + (lead if i == 0 else 0.0)
        hold = f",tpad=start_mode=clone:start_duration={pad:.3f}" if pad > 0 else ""
        parts.append(f"[1:v]trim=start={va - lo:.3f}:end={b - lo:.3f},setpts=PTS-STARTPTS,fps={FPS}{hold},"
                     f"crop={cw}:{ch}:'{crop_expr(plan)}':{y0},scale={VID_W}:{VID_H}:flags=lanczos,setsar=1[v{i}]")
        aparts.append(f"[1:a]atrim=start={a - lo:.3f}:end={b - lo:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.04,afade=t=out:st={d - 0.04:.3f}:d=0.04[a{i}]")
        vlabels.append(f"[v{i}]")
        alabels.append(f"[a{i}]")
    n = len(segs)
    parts.append(f"{''.join(vlabels)}concat=n={n}:v=1:a=0[vc]")
    aparts.append(f"{''.join(alabels)}concat=n={n}:v=0:a=1[ac]")
    parts.append(f"[0:v][vc]overlay=0:{VID_Y}:shortest=1,ass={ass}:fontsdir={FONT_DIR},"
                 f"fade=t=in:d=0.2,fade=t=out:st={bg_dur - 0.3:.3f}:d=0.3,format=yuv420p[out]")
    return ";".join(parts), ";".join(aparts)


def render(clip, src_dir, work, subs_only=False):
    src = os.path.join(src_dir, f"ep{clip['episode']}.mp4")
    cid = clip["id"]
    segs = clip.get("segments") or [[clip["start"], clip["end"]]]
    lo, hi = segs[0][0], segs[-1][1]
    lead = clip.get("lead_in", 0.0)          # optional silent beat before the first word
    dur = sum(sg[1] - sg[0] for sg in segs) + lead
    fw, fh = probe(src)

    # captions on the output timeline
    pcm = speech(src, lo - 3, hi + 3)
    allw = json.load(open(os.path.join(work, f"{cid}.words.json")))
    words = clip_words(allw, segs, pcm, lo - 3, lead)
    ass = os.path.join(work, f"{cid}.ass")
    srt = os.path.join(ROOT, "subtitles", f"{cid}.srt")
    write_subs(words, ass, srt, VID_Y + VID_H - 170, dur)
    if subs_only:
        print(cid, "->", srt)
        return

    region = clip.get("region")
    # optional crop_h keeps the source's own lower-third graphics out of the window
    ch = clip.get("crop_h", fh)
    cw = int(round(ch * VID_W / VID_H / 2)) * 2
    y0 = clip.get("crop_y", 0)
    plans = clip.get("crop_x") or [facetrack.track(src, sg[2] if len(sg) > 2 else sg[0], sg[1], cw, fw, region,
                                                   clip.get("pick", "largest"), clip.get("max_cx"), clip.get("default_cx"))
                                   for sg in segs]
    json.dump(plans, open(os.path.join(work, f"{cid}.crop.json"), "w"))

    bg = os.path.join(work, f"{cid}.frame.png")
    frame_png(clip, bg)

    vfc, afc = graph(clip, segs, lo, cw, ch, y0, plans, ass, dur, lead)
    base = ["ffmpeg", "-hide_banner", "-y", "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", bg,
            "-ss", f"{lo:.3f}", "-t", f"{hi - lo + 0.5:.3f}", "-i", src]
    # pass 1: measure loudness of the edited audio so pass 2 is a linear gain (even level across clips)
    p = subprocess.run(base[:2] + ["-ss", f"{lo:.3f}", "-t", f"{hi - lo + 0.5:.3f}", "-i", src,
                                   "-filter_complex", afc.replace("[1:a]", "[0:a]") + ";[ac]loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json[an]",
                               "-map", "[an]", "-f", "null", "-"], capture_output=True, text=True)
    m = json.loads(p.stderr[p.stderr.rindex("{"):p.stderr.rindex("}") + 1])
    an = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    delay = f"adelay=delays={round(lead * 1000)}:all=1," if lead else ""
    # asetpts re-times the audio from its sample count: after concat, loudnorm passes on frames whose
    # timestamps bunch up over its 3 s look-ahead, which the AAC encoder wrote as packets of 1 and
    # 215 samples followed by one of 2.4 s (seeking into the first 3 s then found no audio)
    fc = vfc + ";" + afc + (f";[ac]{an},{delay}afade=t=in:d=0.08,afade=t=out:st={dur - 0.25:.3f}:d=0.25,"
                            "aresample=48000,asetpts=N/SR/TB[aout]")
    out = os.path.join(ROOT, "clips", f"{cid}.mp4")
    cmd = base[:2] + ["-v", "error"] + base[2:] + [
        "-filter_complex", fc, "-map", "[out]", "-map", "[aout]", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-maxrate", "7M", "-bufsize", "14M",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
        "-metadata", f"title={clip['hook']}", out]
    subprocess.run(cmd, check=True)
    print(cid, f"{dur:.1f}s ->", out, "crop", plans)


def main():
    src_dir, work = sys.argv[1], sys.argv[2]
    subs_only = "--subs-only" in sys.argv[3:]
    only = set(sys.argv[3:]) - {"--subs-only"}
    clips = json.load(open(os.path.join(ROOT, "clips.json")))
    for c in clips:
        if not only or c["id"] in only:
            render(c, src_dir, work, subs_only)


if __name__ == "__main__":
    main()
