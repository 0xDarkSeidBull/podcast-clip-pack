"""Verify the rendered clips and generate CLIPS.md, VERIFICATION.md and index.html.

Usage:
  python3 tools/build_docs.py

Measures the specs of every MP4 and SRT itself, and reads the audio, edit and frame checks
from verification/report.json (written by tools/verify_av.py, which needs the source
episodes) plus the manual verdicts in verification/review.json. A report that does not
match the current MP4 or SRT, or a difference nobody has reviewed, fails the build.

Exits non-zero if any check fails, so it can gate a deploy.
"""
import hashlib
import html
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VER = os.path.join(ROOT, "verification")

AMA = "https://redbelly.network/ama"
EPISODES = {
    29: {"title": "Redbelly Insights - Episode 29", "date": "9 July 2026", "guest": "Effie Dimitropoulos (AUDD Digital)",
         "url": "https://storage.googleapis.com/redbelly-website.firebasestorage.app/Video/rb_ep_29_final_fde9f2a3d6/rb_ep_29_final_fde9f2a3d6.mp4"},
    28: {"title": "Redbelly Insights - Episode 28", "date": "11 June 2026", "guest": "Vincent Gramoli",
         "url": "https://storage.googleapis.com/redbelly-website.firebasestorage.app/Video/rb_ep_28_final_745719acdb/rb_ep_28_final_745719acdb.mp4"},
    26: {"title": "Redbelly Insights - Episode 26", "date": "26 March 2026", "guest": "Alan Burt & Matt Mills",
         "url": "https://firebasestorage.googleapis.com/v0/b/redbelly-website.firebasestorage.app/o/RBI_EP26.mp4?alt=media&token=ce10a8dd-1721-4272-bd43-f3e6be081d94"},
}
TOPIC = {
    "01-audd-sovereignty": "Redbelly technology (Australian-built chain for a sovereign AUD stablecoin)",
    "02-tokenised-workflows": "Project Acacia / Redbelly technology (tokenised workflows)",
    "03-accountable-consensus": "Redbelly technology (accountable consensus)",
    "04-ai-agent-accountability": "Redbelly technology (application-layer accountability)",
    "05-tokeniser-gateway": "Tokeniser",
    "06-acacia-instant-subscription": "Project Acacia / Tokeniser",
}
# Spellings that must never appear in a subtitle file.
BANNED = [r"\bRed ?[Bb]elly\b(?<!Redbelly)", r"\bRed Belly\b", r"\bRedBelly\b", r"\bred belly\b",
          r"\bTokeni[sz]er\b(?<!Tokeniser)", r"\bTokenizer\b", r"\btokeniz", r"\bAkasha\b", r"\bArcacia\b",
          r"\bRBMT\b", r"\bRevenue [Nn]etwork\b"]
CREDIT = [r"made by", r"edited by", r"created by", r"@\w{3,}"]


def probe(path):
    out = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                                              "-of", "json", path]))
    v = next(s for s in out["streams"] if s["codec_type"] == "video")
    a = next((s for s in out["streams"] if s["codec_type"] == "audio"), None)
    num, den = map(int, v["r_frame_rate"].split("/"))
    return {"w": v["width"], "h": v["height"], "fps": num / den, "vcodec": v["codec_name"],
            "acodec": a and a["codec_name"], "dur": float(out["format"]["duration"]),
            "size": int(out["format"]["size"]), "tags": out["format"].get("tags", {})}


def audio_frames(path):
    """Number of AAC packets, and how many are not one 1024-sample frame starting where the previous
    one ended (the last packet aside): any such packet is a gap or overlap in the audio timeline."""
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                   "packet=pts,duration", "-of", "csv=p=0", path], text=True)
    pk = [tuple(int(x) for x in line.split(",")[:2]) for line in out.split()]
    odd = sum(1 for k, (pts, d) in enumerate(pk)
              if (d != 1024 and k < len(pk) - 1) or (k and pts != pk[k - 1][0] + pk[k - 1][1]))
    return len(pk), odd


def timing_verdict(entries, x):
    """Verdict on a word the timing check found outside its cue (same word, within 0.3 s)."""
    return next((e["verdict"] for e in entries if e["word"] == x["word"] and abs(e["t"] - x["t"]) <= 0.3), None)


def loudness(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    summ = p.stderr[p.stderr.rindex("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summ).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ).group(1))
    return i, peak


def srt_text(path):
    return " ".join(l for l in open(path).read().splitlines()
                    if l.strip() and not l.strip().isdigit() and "-->" not in l)


def srt_cues(path):
    def sec(x):
        h, m, s = x.strip().replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    cues = []
    for block in open(path).read().strip().split("\n\n"):
        lines = block.strip().splitlines()
        a, b = lines[1].split(" --> ")
        cues.append((int(lines[0]), sec(a), sec(b)))
    return cues


def cue_problems(cues, dur):
    bad = []
    for i, (n, s, e) in enumerate(cues):
        if n != i + 1:
            bad.append(f"cue {n} out of sequence")
        if e <= s:
            bad.append(f"cue {n} has no duration")
        if i and s < cues[i - 1][2]:
            bad.append(f"cue {n} overlaps cue {cues[i - 1][0]}")
        if e > dur + 0.05:
            bad.append(f"cue {n} ends after the clip")
    return bad


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def clock(t):
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}"


def verdict(entries, **want):
    """Manual verdict recorded in verification/review.json for a difference, or None."""
    for e in entries:
        if all(e.get(k) == v or (k == "text" and "pattern" in e and re.fullmatch(e["pattern"], v))
               for k, v in want.items()):
            return e["verdict"]
    return None


def main():
    clips = json.load(open(os.path.join(ROOT, "clips.json")))
    rpath, vpath = os.path.join(VER, "report.json"), os.path.join(VER, "review.json")
    hpath = os.path.join(VER, "human_review.json")
    report = json.load(open(rpath)) if os.path.exists(rpath) else {"clips": {}}
    review = json.load(open(vpath)) if os.path.exists(vpath) else {"clips": {}}
    human = json.load(open(hpath)) if os.path.exists(hpath) else None
    rows, checks, ok = [], [], True

    def check(cid, name, passed, detail):
        nonlocal ok
        ok &= passed
        checks.append((cid, name, "PASS" if passed else "FAIL", detail))

    points = set()
    for c in clips:
        cid = c["id"]
        mp4 = os.path.join(ROOT, "clips", f"{cid}.mp4")
        srt = os.path.join(ROOT, "subtitles", f"{cid}.srt")
        p = probe(mp4)
        os.makedirs(os.path.join(ROOT, "posters"), exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2.5", "-i", mp4, "-frames:v", "1", "-vf", "scale=540:-1",
                        "-q:v", "4", os.path.join(ROOT, "posters", f"{cid}.jpg")], check=True)
        lufs, peak = loudness(mp4)
        text = srt_text(srt)
        check(cid, "9:16, 1080p or higher", p["w"] == 1080 and p["h"] == 1920, f"{p['w']}x{p['h']}")
        check(cid, "24 fps or higher", p["fps"] >= 24, f"{p['fps']:.2f} fps")
        check(cid, "MP4 / H.264 + AAC", p["vcodec"] == "h264" and p["acodec"] == "aac", f"{p['vcodec']} + {p['acodec']}")
        check(cid, "30-60 s", 30 <= p["dur"] <= 60.5, f"{p['dur']:.1f} s")
        check(cid, "Loudness -14 LUFS +/-1", abs(lufs + 14) <= 1.0, f"{lufs:.1f} LUFS, peak {peak:.1f} dBFS")
        n, odd = audio_frames(mp4)
        check(cid, "Audio frames evenly timed (no gaps or overlaps)", not odd,
              f"{n} AAC frames of 1024 samples" if not odd else f"{odd} of {n} AAC frames off the timeline")
        bad = [b for b in BANNED if re.search(b, text)]
        check(cid, "Subtitle spelling (Redbelly, Tokeniser, Acacia...)", not bad, "clean" if not bad else ", ".join(bad))
        meta = " ".join(str(v) for v in p["tags"].values()).lower()
        cred = [x for x in CREDIT if re.search(x, meta + " " + text.lower())]
        check(cid, "No personal credit in file or subtitles", not cred, "none" if not cred else ", ".join(cred))
        check(cid, "Distinct point", c["hook"] not in points, c["hook"])
        points.add(c["hook"])
        cues = srt_cues(srt)
        bad = cue_problems(cues, p["dur"])
        check(cid, "SRT cues in sequence, no overlaps", not bad, f"{len(cues)} cues" if not bad else "; ".join(bad[:3]))

        # audio, edit and frame checks measured by tools/verify_av.py
        r = report["clips"].get(cid)
        rv = review["clips"].get(cid, {})
        fresh = bool(r) and r["sha256"] == sha256(mp4) and r["srt_sha256"] == sha256(srt)
        check(cid, "Audio/visual report is for this MP4 and SRT", fresh, "sha256 match" if fresh else "re-run tools/verify_av.py")
        if r:
            s = r["subs"]
            check(cid, "Subtitles vs independent transcript of the clip audio", s["match"] >= 0.95,
                  f"{s['match']:.1%} word match ({report['model']}), {len(s['diffs'])} differences")
            open_diffs = [d for d in s["diffs"] if not verdict(rv.get("subtitle_diffs", []), srt=d["srt"], asr=d["asr"])]
            check(cid, "Every subtitle difference reviewed against the audio", not open_diffs,
                  f"{len(s['diffs'])} of {len(s['diffs'])} reviewed" if not open_diffs
                  else "unreviewed: " + "; ".join(f"{d['srt']!r} vs {d['asr']!r}" for d in open_diffs[:3]))
            late = [x for x in s["timing_off"] if not timing_verdict(rv.get("timing", []), x)]
            check(cid, "Subtitle timing (word spoken while its cue is on screen)", s["timing_in_cue"] >= 0.95 and not late,
                  f"{s['timing_in_cue']:.1%} of {s['timing_words']} words within 0.3 s"
                  + (f", {len(s['timing_off'])} outside reviewed" if s["timing_off"] else "") if not late
                  else "unreviewed: " + "; ".join(f"{x['word']!r} at {clock(x['t'])}" for x in late[:3]))
            err = max(max(abs(x["head_ms"]), abs(x["tail_ms"])) for x in r["sync"])
            corr = min(min(x["head_corr"], x["tail_corr"]) for x in r["sync"])
            check(cid, "Clip audio is exactly the listed source ranges", err <= 40 and corr >= 0.8,
                  f"{len(r['sync'])} ranges, start/end within {err:.0f} ms (correlation {corr:.2f})")
            # an edit point is clean when it sits in a pause; one in connected speech needs a reviewed verdict
            loud = [b for b in r["bounds"] if b["level_db"] > -20]
            open_pts = [b for b in loud if not verdict(rv.get("edit_points", []), src=b["src"])]
            check(cid, "Every edit point in a pause between words", not open_pts,
                  f"{len(r['bounds']) - len(loud)} of {len(r['bounds'])} in a pause (-20 dB or quieter)"
                  + (f", {len(loud)} in connected speech reviewed" if loud else "") if not open_pts
                  else "; ".join(f"{clock(b['src'])} at {b['level_db']:.0f} dB" for b in open_pts))
            edges = [b for b in r["bounds"] if b["heard"] != b["expect"]
                     and not verdict(rv.get("edit_points", []), src=b["src"])]
            same = sum(1 for b in r["bounds"] if b["heard"] == b["expect"])
            check(cid, "First and last word of every range heard whole", not edges,
                  f"{same} of {len(r['bounds'])} edit points match the subtitles"
                  + (f", {len(r['bounds']) - same} reviewed" if same < len(r["bounds"]) else "") if not edges
                  else "; ".join(f"{clock(b['src'])} heard {b['heard']!r}, subtitles {b['expect']!r}" for b in edges))
            v = r["visual"]
            check(cid, "Branded frame unchanged in every frame", v["static_max_diff"] <= 3.0,
                  f"{v['frames']} frames, max difference {v['static_max_diff']:.1f}/255")
            onscreen = v["name_ok"] and v["role_ok"] and v["hook_ok"] and v["episode_ok"]
            check(cid, "On-screen name, role, hook and episode (OCR)", onscreen, v["footer_ocr"])
            check(cid, "No credits, handles or URLs on screen (OCR every second)", not v["credits"],
                  "none" if not v["credits"] else ", ".join(f"{x['text']} at {clock(x['t'])}" for x in v["credits"][:4]))
            other = [x for x in v["other_text"] if not verdict(rv.get("other_text", []), text=x["text"])]
            check(cid, "Any other on-screen text reviewed", not other,
                  "none" if not v["other_text"] else f"{len(v['other_text'])} reviewed" if not other
                  else "unreviewed: " + ", ".join(f"{x['text']} at {clock(x['t'])}" for x in other[:4]))
            check(cid, "Speaker's face in frame", v["face_pct"] >= 0.9, f"{v['face_pct']:.0%} of frames")
            check(cid, "No black or frozen video", not v["black"] and not v["freeze"],
                  "none" if not v["black"] and not v["freeze"] else f"black {v['black']}, frozen {v['freeze']}")
            check(cid, "Contact sheet reviewed", bool(rv.get("frames")),
                  "reviewed (see review notes)" if rv.get("frames") else "not reviewed")
        if human:
            # a person's sign-off counts only for the exact MP4 and SRT that person watched
            h = human["clips"].get(cid, {})
            signed = h.get("result") == "PASS" and h.get("sha256") == sha256(mp4) and h.get("srt_sha256") == sha256(srt)
            check(cid, "Watched and listened in full by a person", signed,
                  f"{human['reviewer']}, {h.get('date', '')}" if signed else "not signed off for these files")

        segs = c["segments"]
        stamps = ", ".join(f"{clock(s[0])}-{clock(s[1])}" for s in segs)
        ep = EPISODES[c["episode"]]
        rows.append({**c, "stamps": stamps, "ep": ep, "dur": p["dur"], "size": p["size"], "lufs": lufs, "w": p["w"], "h": p["h"], "fps": p["fps"],
                     "topic": TOPIC[cid], "transcript": text, "report": r, "review": rv})
    check("pack", "6 clips", len(clips) == 6, str(len(clips)))

    write_clips_md(rows)
    write_verification_md(checks, rows, report, review)
    write_index(rows, checks)
    print("\n".join(f"{c:32} {s:4} {n}: {d}" for c, n, s, d in checks))
    print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


def write_clips_md(rows):
    out = ["# Clip list", "",
           "Six vertical clips cut from the latest official Redbelly Insights episodes "
           f"([redbelly.network/ama]({AMA})). Timestamps are `mm:ss.s` in the official episode file. "
           "Where a clip has more than one range, the ranges are joined with a straight cut; "
           "only restatements or asides were removed, never words that change the point being made.", ""]
    out += ["| # | Clip | Source episode | Timestamps | Speaker | Length |",
            "|---|------|----------------|------------|---------|--------|"]
    for i, r in enumerate(rows, 1):
        out.append(f"| {i} | [{r['id']}](clips/{r['id']}.mp4) | {r['ep']['title']} ({r['ep']['date']}) | "
                   f"{r['stamps']} | {r['speaker']}, {r['role']} | {r['dur']:.0f} s |")
    out.append("")
    for i, r in enumerate(rows, 1):
        out += [f"## {i}. {r['hook']}", "",
                f"- **File:** [`clips/{r['id']}.mp4`](clips/{r['id']}.mp4) "
                f"(subtitles also as [`subtitles/{r['id']}.srt`](subtitles/{r['id']}.srt))",
                f"- **Source:** {r['ep']['title']}, {r['ep']['date']}, [official episode file]({r['ep']['url']})",
                f"- **Timestamps:** {r['stamps']}",
                f"- **Speaker:** {r['speaker']}, {r['role']}",
                f"- **Topic:** {r['topic']}",
                f"- **Suggested post caption:** {r['caption']}", "",
                f"> {r['transcript']}", ""]
        if r["report"] and r["report"]["cuts"]:
            out += ["**What each cut leaves out** (the removed audio transcribed on its own with Whisper large-v3):", ""]
            for k, cut in enumerate(r["report"]["cuts"], 1):
                out.append(f"- Cut {k} at {clock(cut['clip'])} in the clip, {clock(cut['from'])} to {clock(cut['to'])} in the episode "
                           f"({cut['removed_s']:.1f} s): “{cut['removed'] or '(no speech)'}”")
            out.append("")
    open(os.path.join(ROOT, "CLIPS.md"), "w").write("\n".join(out))


def write_verification_md(checks, rows, report, review):
    md = lambda s: str(s).replace("|", "\\|")
    passed = sum(1 for c in checks if c[2] == "PASS")
    model = report.get("model", "")
    out = ["# Verification", "",
           "Generated by `python3 tools/build_docs.py`. Specs, loudness and subtitle files are measured from the "
           "MP4/SRT in this repository. The audio, edit and frame checks come from `tools/verify_av.py`, which "
           "compares each clip with the official episode file and its own audio "
           f"([`verification/report.json`](verification/report.json), tied to each MP4 and SRT by SHA-256). "
           "Every difference those checks find has to carry a manual verdict in "
           "[`verification/review.json`](verification/review.json) or the build fails.", "",
           f"**{passed} of {len(checks)} checks pass.**", "",
           "- [All checks](#all-checks)", "- [Subtitles against the audio](#subtitles-against-the-audio)",
           "- [Edits against the source episode](#edits-against-the-source-episode)",
           "- [What is on screen](#what-is-on-screen)"]
    if os.path.exists(os.path.join(VER, "human_review.json")):
        out.append("- [Human review](#human-review)")
    out += ["- [Review notes on the automated findings](#review-notes-on-the-automated-findings)", "",
           "## All checks", "",
           "| Clip | Check | Result | Measured |", "|------|-------|--------|----------|"]
    out += [f"| {c} | {n} | {s} | {md(d)} |" for c, n, s, d in checks]
    lufs = [r["lufs"] for r in rows]
    out += ["", f"Loudness spread across the pack: {max(lufs) - min(lufs):.1f} LU "
            f"({min(lufs):.1f} to {max(lufs):.1f} LUFS integrated).", ""]

    out += ["## Subtitles against the audio", "",
            f"The final audio of each clip was transcribed again with Whisper `{model}`, a different and larger model than "
            "the `medium.en` used for the subtitles, and compared word by word with the SRT (case, punctuation, "
            "hyphens, fillers and British/American spelling ignored). Every remaining difference is listed with the "
            "verdict after checking that moment of the audio.", "",
            "Timing is measured with a third model, wav2vec 2.0 (a CTC speech model, run through torchaudio), because "
            "Whisper's word times drift by up to a second around pauses and fillers while a CTC model's words are tied "
            "to 20 ms frames. It is also a different model from the MMS_FA aligner that timed the subtitles. A word "
            "counts as on time when the midpoint of the word as wav2vec 2.0 hears it is within 0.3 s of its cue being "
            "on screen; every word outside that is listed with a verdict.", ""]
    for r in rows:
        rep = r["report"]
        if not rep:
            continue
        s = rep["subs"]
        out += [f"### {r['id']}", "",
                f"{s['match']:.1%} word match ({s['srt_words']} subtitle words, {s['asr_words']} transcript words); "
                f"{s['timing_in_cue']:.1%} of {s['timing_words']} words on time.", ""]
        if s["timing_off"]:
            out += ["| Heard at | Word | Cue on screen | Verdict |", "|---|---|---|---|"]
            for x in s["timing_off"]:
                v = timing_verdict(r["review"].get("timing", []), x) or "NOT REVIEWED"
                out.append(f"| {clock(x['t'])} | {md(x['word'])} | {clock(x['cue'][0])}-{clock(x['cue'][1])} | {md(v)} |")
            out.append("")
        if s["diffs"]:
            out += ["| Clip time | Subtitles | Independent transcript | Verdict |", "|---|---|---|---|"]
            for d in s["diffs"]:
                v = verdict(r["review"].get("subtitle_diffs", []), srt=d["srt"], asr=d["asr"]) or "NOT REVIEWED"
                out.append(f"| {clock(d['t'])} | {md(d['srt']) or '(nothing)'} | {md(d['asr']) or '(nothing)'} | {md(v)} |")
            out.append("")

    out += ["## Edits against the source episode", "",
            "**Ranges.** The start and end of every range in the clip were found in the official episode file by "
            "cross-correlating the audio. The error is the distance between where the audio actually comes from and "
            "the timestamp listed in `clips.json` and `CLIPS.md`.", "",
            "**Edit points.** For every point where a range starts or ends, the table gives the word on each side "
            "(the subtitles on the side that is kept, a transcript of the removed audio on the side that is dropped) "
            "and the level of the episode audio at that point relative to the speaker's loud passages. An edit point "
            "passes when it sits in a pause (-20 dB or quieter). Where two words run together with no pause, the edit "
            "is placed at the quietest point between them and carries a verdict. As a check that no word is clipped, "
            "the kept side of every edit point is also transcribed on its own (2.5 s, with the clip's 40 ms fade and a "
            "second of silence around it): the first word heard after a range starts and the last word heard before "
            "it ends must be the subtitles' first and last word.", "",
            "**Cuts.** The words left out at each cut are listed under each clip in [`CLIPS.md`](CLIPS.md).", ""]
    for r in rows:
        rep = r["report"]
        if not rep:
            continue
        out += [f"### {r['id']}", "", "| Range | Listed | Start error | End error | Correlation |", "|---|---|---|---|---|"]
        for x in rep["sync"]:
            out.append(f"| {x['seg']} | {clock(x['from'])}-{clock(x['to'])} | {x['head_ms']:+.0f} ms | {x['tail_ms']:+.0f} ms | "
                       f"{min(x['head_corr'], x['tail_corr']):.2f} |")
        out += ["", "| Edit point | Episode | Clip | Word before | Word after | Heard on its own | Level | Verdict |",
                "|---|---|---|---|---|---|---|---|"]
        for b in rep["bounds"]:
            clean = b["level_db"] <= -20 and b["heard"] == b["expect"]
            v = "clean" if clean else verdict(r["review"].get("edit_points", []), src=b["src"]) or "NOT REVIEWED"
            out.append(f"| range {b['seg']} {b['kind']} | {clock(b['src'])} | {clock(b['clip'])} | {md(b['prev'])} | "
                       f"{md(b['next'])} | {md(b['heard'])} | {b['level_db']:.0f} dB | {md(v)} |")
        out.append("")

    out += ["## What is on screen", "",
            "Every frame of each clip was decoded at 2 fps. The branded header and footer were compared with the "
            "middle frame (any overlay, watermark or credit would change them), the on-screen name, role, hook and "
            "episode were read back with OCR, the 4:5 video window was OCR'd once a second for credits, handles, "
            "URLs or any other text, and a face detector checked that the speaker is in frame. The contact sheets "
            "show one frame every 2 seconds.", ""]
    for r in rows:
        rep = r["report"]
        if not rep:
            continue
        v = rep["visual"]
        out += [f"### {r['id']}", "",
                f"- **Name and role read from the video:** {v['footer_ocr']}",
                f"- **Hook read from the video:** {v['header_ocr']}",
                f"- **Speaker's face found in:** {v['face_pct']:.0%} of {v['frames']} frames",
                f"- **Credits, handles or URLs:** {'none' if not v['credits'] else ', '.join(x['text'] for x in v['credits'])}"]
        if v["other_text"]:
            out.append("- **Other text in the video window:**")
            for x in v["other_text"]:
                vd = verdict(r["review"].get("other_text", []), text=x["text"]) or "NOT REVIEWED"
                out.append(f"  - `{x['text']}` at {clock(x['t'])}: {vd}")
        out += ["", f"![Contact sheet for {r['id']}](verification/{r['id']}.jpg)", ""]

    hpath = os.path.join(VER, "human_review.json")
    if os.path.exists(hpath):
        human = json.load(open(hpath))
        out += ["## Human review", "", f"**Reviewer:** {human['reviewer']}", "", human["how"], ""]
        for rd in human["rounds"]:
            out += [f"### Round {rd['round']} ({rd['date']}): {rd['result']}", ""]
            if rd.get("findings"):
                out += ["| Clip | At | Found | Fix |", "|---|---|---|---|"]
                out += [f"| {f['clip']} | {f['at']} | {md(f['found'])} | {md(f['fix'])} |" for f in rd["findings"]]
                out.append("")
        out += ["Each clip's sign-off is recorded against the SHA-256 of its MP4 and SRT in "
                "[`verification/human_review.json`](verification/human_review.json), so any later change to a clip "
                "voids it until it is watched again.", ""]
    out += ["## Review notes on the automated findings", ""]
    out += [review.get("note", ""), ""] if review.get("note") else []
    for r in rows:
        if r["review"].get("frames"):
            out.append(f"- **{r['id']}:** {r['review']['frames']}")
    out.append("")
    open(os.path.join(ROOT, "VERIFICATION.md"), "w").write("\n".join(out))


def write_index(rows, checks):
    e = html.escape
    passed = sum(1 for c in checks if c[2] == "PASS")
    lufs = [r["lufs"] for r in rows]
    play_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>'
    copy_icon = ('<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/>'
                 '<path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg>')
    dl_icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m0 0-4.5-4.5M12 15l4.5-4.5M5 19h14"/></svg>'
    cards, spec_rows = [], []
    for i, r in enumerate(rows, 1):
        cid = e(r["id"])
        ep_no = r["episode"]
        stamps = "".join(f"<li>{e(x.strip())}</li>" for x in r["stamps"].split(","))
        cards.append(f"""
      <article class="card" id="{cid}">
        <div class="player">
          <video preload="none" playsinline controls poster="posters/{cid}.jpg" src="clips/{cid}.mp4"
                 aria-label="Clip {i}: {e(r['hook'])}"></video>
          <button class="play" type="button" aria-label="Play clip {i}">{play_icon}</button>
        </div>
        <div class="body">
          <p class="ep">Clip {i:02d} &middot; Episode {ep_no} &middot; {r['dur']:.0f}s</p>
          <h2>{e(r['hook'])}</h2>
          <p class="who"><span class="name">{e(r['speaker'])}</span><span class="role">{e(r['role'])}</span></p>
          <p class="topic">{e(r['topic'])}</p>
          <div class="caption">
            <p>{e(r['caption'])}</p>
            <button class="copy" type="button" data-copy="{e(r['caption'])}">{copy_icon}<span>Copy caption</span></button>
          </div>
          <div class="stamps"><span>Source timestamps</span><ul>{stamps}</ul></div>
          <div class="actions">
            <a class="btn primary" href="clips/{cid}.mp4" download>{dl_icon}MP4</a>
            <a class="btn" href="subtitles/{cid}.srt" download>{dl_icon}SRT</a>
            <a class="btn ghost" href="verification/{cid}.jpg" target="_blank" rel="noopener">Frames</a>
            <a class="btn ghost" href="{e(r['ep']['url'])}" target="_blank" rel="noopener" title="Full episode {ep_no}">Episode</a>
          </div>
        </div>
      </article>""")
        mine = [c for c in checks if c[0] == r["id"]]
        fails = sum(1 for c in mine if c[2] != "PASS")
        verdict_cell = (f'<span class="ok"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'
                        f'{len(mine)}/{len(mine)} pass</span>' if not fails else f'<span class="bad">{fails} failing</span>')
        spec_rows.append(f"""
          <tr><td><a href="#{cid}">{i:02d}</a></td><td>{e(r['hook'])}</td><td>{r['w']}&times;{r['h']}</td>
            <td>{r['fps']:.0f} fps</td><td>{r['dur']:.1f} s</td><td>{r['lufs']:.1f} LUFS</td>
            <td>{verdict_cell}</td></tr>""")

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Redbelly Insights Clips</title>
<meta name="description" content="Six captioned vertical clips from the latest Redbelly Insights episodes on Redbelly technology, Project Acacia and Tokeniser.">
<meta name="theme-color" content="#142530">
<link rel="icon" type="image/svg+xml" href="assets/redbelly-mark.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Readex+Pro:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    /* Redbelly brand palette (redbelly.network/brand) */
    --navy-d: #142530; --navy: #283A46; --grey: #848B91; --grey-l: #D9D9D9; --off: #ECEBEC;
    --red: #FF5050; --red-2: #FA423C;
    --bg: #0e1b23; --bg-2: var(--navy-d); --card: var(--navy-d); --card-2: #1b303d;
    --line: rgba(236,235,236,.09); --line-2: rgba(236,235,236,.18);
    --text: #FFFFFF; --muted: var(--grey-l); --dim: var(--grey);
    --glow: rgba(255,80,80,.18);
    --radius: 6px; --r-sm: 4px;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; scroll-padding-top: 84px; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.6 "Readex Pro", system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased; overflow-x: hidden;
  }}
  body::before {{
    content: ""; position: fixed; inset: -20vh -10vw auto; height: 90vh; z-index: -1; pointer-events: none;
    background: radial-gradient(60% 60% at 20% 0%, rgba(255,80,80,.14), transparent 70%),
                radial-gradient(55% 55% at 90% 5%, rgba(40,58,70,.9), transparent 70%);
  }}
  a {{ color: inherit; }}
  .wrap {{ max-width: 1240px; margin: 0 auto; padding: 0 16px; }}
  @media (min-width: 720px) {{ .wrap {{ padding: 0 32px; }} }}

  /* nav */
  .nav {{ position: sticky; top: 0; z-index: 20; backdrop-filter: saturate(160%) blur(14px);
         -webkit-backdrop-filter: saturate(160%) blur(14px); background: rgba(20,37,48,.78); border-bottom: 1px solid var(--line); }}
  .nav .wrap {{ display: flex; align-items: center; justify-content: space-between; height: 68px; gap: 16px; }}
  .logo {{ display: block; height: 30px; width: auto; }}
  .nav ul {{ display: flex; gap: 6px; list-style: none; margin: 0; padding: 0; }}
  .nav li a {{ display: block; padding: 8px 14px; border-radius: var(--r-sm); text-decoration: none; color: var(--muted);
              font-size: 14px; font-weight: 500; transition: color .2s, background .2s; }}
  .nav li a:hover {{ color: var(--text); background: rgba(255,255,255,.06); }}
  @media (max-width: 640px) {{ .nav li:not(:first-child) {{ display: none; }} .logo {{ height: 24px; }} }}

  /* hero */
  .hero {{ padding: 72px 0 40px; }}
  .eyebrow {{ display: inline-flex; align-items: center; gap: 10px; padding: 6px 14px 6px 8px; border: 1px solid var(--line-2);
             border-radius: var(--r-sm); font-size: 13px; color: var(--muted); background: rgba(255,255,255,.03); }}
  .eyebrow img {{ height: 18px; width: auto; }}
  .hero h1 {{ font-size: clamp(36px, 6.4vw, 76px); line-height: 1.02; letter-spacing: -.03em; font-weight: 500;
             margin: 22px 0 18px; max-width: 15ch; }}
  .grad {{ color: var(--red); }}
  .hero p.lede {{ color: var(--muted); font-size: clamp(16px, 1.6vw, 19px); max-width: 62ch; margin: 0 0 32px; }}
  .cta {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 48px; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); border: 1px solid var(--line); border-radius: var(--radius);
           background: linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.01)); overflow: hidden; }}
  .stat {{ padding: 22px 24px; border-left: 1px solid var(--line); }}
  .stat:first-child {{ border-left: 0; }}
  .stat b {{ display: block; font-size: clamp(22px, 2.6vw, 30px); letter-spacing: -.02em; font-weight: 500; }}
  .stat span {{ color: var(--muted); font-size: 13px; }}
  @media (max-width: 720px) {{ .stats {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
    .stat:nth-child(3) {{ border-left: 0; }} .stat:nth-child(n+3) {{ border-top: 1px solid var(--line); }} }}

  /* buttons */
  .btn {{ display: inline-flex; align-items: center; gap: 8px; height: 40px; padding: 0 16px; border-radius: var(--r-sm);
         border: 1px solid var(--line-2); background: rgba(255,255,255,.04); color: var(--text); font: 500 14px/1 "Readex Pro", sans-serif;
         text-decoration: none; cursor: pointer; transition: transform .15s, background .2s, border-color .2s; }}
  .btn:hover {{ background: rgba(255,255,255,.09); border-color: rgba(255,255,255,.24); }}
  .btn:active {{ transform: scale(.97); }}
  .btn.primary {{ background: var(--red); border-color: var(--red); color: #fff; box-shadow: 0 8px 28px -10px var(--red); }}
  .btn.primary:hover {{ background: var(--red-2); border-color: var(--red-2); }}
  .btn.ghost {{ background: transparent; }}
  .btn.lg {{ height: 48px; padding: 0 22px; font-size: 15px; }}
  .to-top {{ position: fixed; right: 16px; bottom: 16px; z-index: 30; width: 48px; height: 48px; display: grid; place-items: center;
            border-radius: var(--r-sm); border: 1px solid var(--line-2); background: rgba(20,37,48,.88); color: #fff; cursor: pointer;
            backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
            opacity: 0; visibility: hidden; transform: translateY(12px); transition: opacity .2s, transform .2s, visibility .2s, background .2s, border-color .2s; }}
  .to-top.show {{ opacity: 1; visibility: visible; transform: none; }}
  .to-top:hover {{ background: var(--red); border-color: var(--red); }}
  .to-top:focus-visible {{ outline: 2px solid var(--red); outline-offset: 3px; }}
  .to-top svg {{ width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }}
  @media (min-width: 720px) {{ .to-top {{ right: 24px; bottom: 24px; }} }}
  .btn svg, .copy svg {{ width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex: none; }}

  /* section heads */
  .head {{ display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 40px 0 24px; flex-wrap: wrap; }}
  .head h2 {{ font-size: clamp(24px, 3vw, 34px); letter-spacing: -.02em; margin: 0; font-weight: 500; }}
  .head p {{ margin: 0; color: var(--muted); font-size: 14px; }}

  /* cards */
  .grid {{ display: grid; gap: 24px; grid-template-columns: repeat(3, minmax(0,1fr)); }}
  @media (max-width: 1080px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0,1fr)); }} }}
  @media (max-width: 680px) {{ .grid {{ grid-template-columns: minmax(0,1fr); }} }}
  .card {{ display: flex; flex-direction: column; background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
          overflow: hidden; transition: border-color .25s, transform .25s, box-shadow .25s; }}
  .card:hover {{ border-color: var(--line-2); transform: translateY(-3px); box-shadow: 0 24px 60px -30px rgba(0,0,0,.8); }}
  .card.is-playing {{ border-color: rgba(255,80,80,.55); box-shadow: 0 0 0 1px rgba(255,80,80,.3), 0 30px 80px -30px var(--glow); }}
  .player {{ position: relative; aspect-ratio: 9 / 16; background: #000; }}
  .player video {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }}
  .play {{ position: absolute; inset: 0; margin: auto; width: 76px; height: 76px; border-radius: 50%; border: 1px solid rgba(255,255,255,.35);
          background: rgba(255,80,80,.92); color: #fff; display: grid; place-items: center; cursor: pointer;
          box-shadow: 0 12px 40px -8px rgba(255,80,80,.7); transition: transform .2s, opacity .2s; }}
  .play svg {{ width: 30px; height: 30px; fill: currentColor; margin-left: 4px; }}
  .play:hover {{ transform: scale(1.07); }}
  .player.started .play {{ opacity: 0; pointer-events: none; }}
  .badge {{ position: absolute; top: 12px; right: 12px; padding: 4px 10px; border-radius: var(--r-sm); font-size: 12px; font-weight: 500;
           background: rgba(20,37,48,.75); border: 1px solid rgba(255,255,255,.15); backdrop-filter: blur(6px); pointer-events: none;
           transition: opacity .2s; }}
  .player.started .badge {{ opacity: 0; }}
  .body {{ padding: 22px 22px 24px; display: flex; flex-direction: column; gap: 14px; flex: 1; }}
  .ep {{ margin: 0; color: var(--red); font-size: 12px; font-weight: 500; letter-spacing: .08em; text-transform: uppercase; }}
  .body h2 {{ margin: -6px 0 0; font-size: 21px; line-height: 1.3; letter-spacing: -.01em; font-weight: 500; }}
  .who {{ margin: 0; display: flex; flex-direction: column; }}
  .who .name {{ font-weight: 500; }}
  .who .role {{ color: var(--muted); font-size: 14px; }}
  .topic {{ margin: 0; color: var(--dim); font-size: 13px; }}
  .caption {{ background: var(--card-2); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 14px 16px; }}
  .caption p {{ margin: 0 0 10px; font-size: 14.5px; color: var(--off); font-weight: 300; }}
  .copy {{ display: inline-flex; align-items: center; gap: 7px; border: 0; background: none; padding: 0; color: var(--red);
          font: 500 13px/1 "Readex Pro", sans-serif; cursor: pointer; }}
  .copy:hover span {{ text-decoration: underline; }}
  .stamps span {{ display: block; font-size: 12px; color: var(--dim); margin-bottom: 6px; }}
  .stamps ul {{ list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }}
  .stamps li {{ font: 500 12px/1 ui-monospace, SFMono-Regular, Menlo, monospace; padding: 6px 8px; border-radius: var(--r-sm);
               background: rgba(255,255,255,.05); border: 1px solid var(--line); color: var(--grey-l); }}
  .actions {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; padding-top: 4px; }}
  .actions .btn {{ padding: 0 10px; gap: 6px; }}

  /* specs */
  .table {{ border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; background: var(--card); }}
  .scroll {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; min-width: 720px; }}
  th, td {{ text-align: left; padding: 14px 18px; border-bottom: 1px solid var(--line); white-space: nowrap; }}
  td:nth-child(2) {{ white-space: normal; }}
  th {{ color: var(--muted); font-weight: 500; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; background: var(--bg-2); }}
  tr:last-child td {{ border-bottom: 0; }}
  td a {{ color: var(--red); text-decoration: none; font-weight: 500; }}
  .ok {{ display: inline-flex; align-items: center; gap: 8px; color: var(--off); font-weight: 500; }}
  .ok svg {{ width: 18px; height: 18px; padding: 3px; border-radius: var(--r-sm); background: rgba(236,235,236,.12);
            border: 1px solid rgba(236,235,236,.28); fill: none; stroke: var(--off); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }}
  .bad {{ color: var(--red); font-weight: 500; }}
  .note {{ color: var(--muted); font-size: 14px; margin: 16px 0 0; }}
  .note a {{ color: var(--text); }}

  footer {{ margin-top: 80px; border-top: 1px solid var(--line); padding: 32px 0 48px; color: var(--muted); font-size: 14px; }}
  footer .wrap {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }}
  footer img {{ height: 22px; width: auto; }}
  :focus-visible {{ outline: 2px solid var(--red); outline-offset: 3px; }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; scroll-behavior: auto !important; }} }}
</style>
</head>
<body>
<nav class="nav" aria-label="Main">
  <div class="wrap">
    <a href="#top" aria-label="Redbelly Insights clips, back to top"><img class="logo" src="assets/redbelly-logo.svg" alt="Redbelly"></a>
    <ul>
      <li><a href="#clips">Clips</a></li>
      <li><a href="#specs">Specs</a></li>
      <li><a href="CLIPS.md">Clip list</a></li>
    </ul>
  </div>
</nav>

<header class="hero" id="top">
  <div class="wrap">
    <span class="eyebrow"><img src="assets/redbelly-mark.svg" alt="">Redbelly Insights &middot; Podcast Clip Pack</span>
    <h1>Six moments on Redbelly tech, <span class="grad">Project Acacia</span> &amp; <span class="grad">Tokeniser</span></h1>
    <p class="lede">Captioned vertical clips cut from the latest official Redbelly Insights episodes, ready for X, YouTube Shorts and
      Instagram. Every clip makes one point, shows the speaker's name and role, and comes with its source timestamps and a post caption.</p>
    <div class="cta">
      <a class="btn primary lg" href="#clips">{play_icon.replace('aria-hidden="true"', 'aria-hidden="true" style="fill:currentColor;stroke:none"')}Watch the clips</a>
      <a class="btn lg" href="CLIPS.md">Clip list &amp; captions</a>
    </div>
    <div class="stats">
      <div class="stat"><b>{len(rows)}</b><span>vertical clips</span></div>
      <div class="stat"><b>1080&times;1920</b><span>9:16 &middot; 30 fps &middot; MP4</span></div>
      <div class="stat"><b>{sum(lufs) / len(lufs):.0f} LUFS</b><span>even audio across all clips</span></div>
      <div class="stat"><b>{passed}/{len(checks)}</b><span>automated checks passed</span></div>
    </div>
  </div>
</header>

<main class="wrap">
  <section id="clips" aria-labelledby="clips-h">
    <div class="head"><h2 id="clips-h">The clips</h2><p>Subtitles burned in &middot; SRT files included</p></div>
    <div class="grid">{''.join(cards)}
    </div>
  </section>

  <section id="specs" aria-labelledby="specs-h">
    <div class="head"><h2 id="specs-h">Delivery specs</h2><p>Measured from the files, not typed by hand</p></div>
    <div class="table"><div class="scroll">
      <table>
        <thead><tr><th>#</th><th>Clip</th><th>Resolution</th><th>Frame rate</th><th>Length</th><th>Loudness</th><th>Checks</th></tr></thead>
        <tbody>{''.join(spec_rows)}
        </tbody>
      </table>
    </div></div>
    <p class="note">Full results, including subtitles checked against an independent transcript of each clip's audio,
      every edit point checked against the source episode, and on-screen text read back from the frames, are in the
      <a href="VERIFICATION.md">verification report</a>.</p>
  </section>
</main>

<footer>
  <div class="wrap">
    <img src="assets/redbelly-logo.svg" alt="Redbelly">
    <p>All footage and audio from official Redbelly Insights episodes at
      <a href="{AMA}" target="_blank" rel="noopener">redbelly.network/ama</a>. No music or third-party material added.</p>
  </div>
</footer>

<button class="to-top" type="button" aria-label="Back to top" tabindex="-1"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/></svg></button>

<script>
  (function () {{
    var videos = Array.prototype.slice.call(document.querySelectorAll(".player video"));

    function card(v) {{ return v.closest(".card"); }}

    // Only one clip plays at a time.
    // Native controls appear once a clip has started, so the poster stays clean.
    // Without JavaScript the controls stay on and the clips still play.
    videos.forEach(function (v) {{ v.controls = false; }});

    videos.forEach(function (v) {{
      v.addEventListener("click", function () {{ if (!v.controls) v.play(); }});
      v.addEventListener("play", function () {{
        v.controls = true;
        videos.forEach(function (o) {{ if (o !== v && !o.paused) o.pause(); }});
        v.parentNode.classList.add("started");
        card(v).classList.add("is-playing");
      }});
      v.addEventListener("pause", function () {{ card(v).classList.remove("is-playing"); }});
      v.addEventListener("ended", function () {{ card(v).classList.remove("is-playing"); }});
    }});

    document.querySelectorAll(".play").forEach(function (b) {{
      b.addEventListener("click", function () {{
        var v = b.parentNode.querySelector("video");
        var p = v.play();
        // If the browser refuses to start playback, show the native controls so the clip is not stuck on its poster.
        if (p && p.catch) p.catch(function () {{ v.controls = true; v.parentNode.classList.add("started"); }});
      }});
    }});

    // Pause a clip once it is scrolled mostly out of view.
    if ("IntersectionObserver" in window) {{
      var io = new IntersectionObserver(function (entries) {{
        entries.forEach(function (en) {{ if (en.intersectionRatio < 0.25 && !en.target.paused) en.target.pause(); }});
      }}, {{ threshold: [0, 0.25] }});
      videos.forEach(function (v) {{ io.observe(v); }});
    }}

    document.querySelectorAll(".copy").forEach(function (b) {{
      var label = b.querySelector("span");
      b.addEventListener("click", function () {{
        var t = b.getAttribute("data-copy");
        var done = function (msg) {{ label.textContent = msg; setTimeout(function () {{ label.textContent = "Copy caption"; }}, 1800); }};
        // Older browsers and pages served without HTTPS have no clipboard API, so fall back to a hidden text area.
        var legacy = function () {{
          var ta = document.createElement("textarea");
          ta.value = t; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
          document.body.appendChild(ta); ta.select();
          var ok = false;
          try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
          document.body.removeChild(ta);
          done(ok ? "Copied" : "Copy failed");
        }};
        if (navigator.clipboard && window.isSecureContext) {{
          navigator.clipboard.writeText(t).then(function () {{ done("Copied"); }}, legacy);
        }} else {{ legacy(); }}
      }});
    }});

    // Back to top button, shown once the page has scrolled past the hero.
    var toTop = document.querySelector(".to-top");
    if (toTop) {{
      var ticking = false;
      var update = function () {{
        var show = window.scrollY > 600;
        toTop.classList.toggle("show", show);
        toTop.tabIndex = show ? 0 : -1;
        ticking = false;
      }};
      window.addEventListener("scroll", function () {{
        if (!ticking) {{ ticking = true; window.requestAnimationFrame(update); }}
      }}, {{ passive: true }});
      update();
      toTop.addEventListener("click", function () {{
        var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.scrollTo({{ top: 0, behavior: reduce ? "auto" : "smooth" }});
        var top = document.getElementById("top");
        if (top) {{ top.setAttribute("tabindex", "-1"); top.focus({{ preventScroll: true }}); }}
      }});
    }}
  }})();
</script>
</body>
</html>
"""
    open(os.path.join(ROOT, "index.html"), "w").write(page)

if __name__ == "__main__":
    main()
