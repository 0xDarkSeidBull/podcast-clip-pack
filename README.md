# Redbelly Insights Podcast Clip Pack

Six captioned vertical clips (30 to 60 seconds) cut from the latest official Redbelly Insights episodes, each making one point about Redbelly technology, Project Acacia or Tokeniser. They are ready to post on X, YouTube Shorts, and Instagram.

| Deliverable | Where |
|---|---|
| 1. Six vertical clips with burned-in subtitles | [`clips/`](clips) (MP4, 1080×1920, 9:16, 30 fps, H.264 + AAC) |
| Subtitles as separate files | [`subtitles/`](subtitles) (SRT, one per clip) |
| 2. Source episode, timestamps and post caption for each clip | [`CLIPS.md`](CLIPS.md) |
| Measured checks for every clip: specs, loudness, subtitles against the audio, every edit against the source episode, on-screen text and frames, plus a person's watch-through of every clip | [`VERIFICATION.md`](VERIFICATION.md) (data and contact sheets in [`verification/`](verification)) |
| Review page with players, sources, captions and downloads | [`index.html`](index.html) (poster frames in `posters/`) |
| Brand assets: official Redbelly logos from the [Redbelly brand kit](https://redbelly.network/brand) and the brand typeface Readex Pro (SIL OFL, licence in `assets/fonts/OFL.txt`) | [`assets/`](assets) |

## The clips

| # | Hook | Speaker | Source |
|---|------|---------|--------|
| 1 | Why an Aussie dollar stablecoin runs on Redbelly | Effie Dimitropoulos, CEO, AUDD Digital | Episode 29 (9 July 2026) |
| 2 | A tokenised invoice is just a PDF. The workflow is the value. | Vincent Gramoli, Founder, Redbelly Network | Episode 28 (11 June 2026) |
| 3 | Try to double-spend and you get caught | Vincent Gramoli, Founder, Redbelly Network | Episode 28 (11 June 2026) |
| 4 | Every AI agent needs a human who answers for it | Vincent Gramoli, Founder, Redbelly Network | Episode 28 (11 June 2026) |
| 5 | Everyone wants tokenisation. Tokeniser is the how. | Matt Mills, Chief Customer Officer, Tokeniser | Episode 26 (26 March 2026) |
| 6 | Project Acacia: fund units issued the moment you pay | Matt Mills, Chief Customer Officer, Tokeniser | Episode 26 (26 March 2026) |

Exact timestamps, full transcripts and suggested post captions are in [`CLIPS.md`](CLIPS.md).

## How the moments were chosen

- **Latest first.** Episodes 29, 28, 27, 26 and 25 (the five most recent on [redbelly.network/ama](https://redbelly.network/ama)) were transcribed in full. Episode 27 (AUDM stablecoin) is mostly about stablecoins and FX in general, and Episode 25 overlaps Episode 28 on accountability, so the six clips come from Episodes 29, 28 and 26.
- **On brief.** Every clip is about Redbelly technology, Project Acacia or Tokeniser. Each makes one point, and no two make the same point: sovereign AUD stablecoin infrastructure, tokenised workflows, accountable consensus, AI-agent accountability, Tokeniser as the on-ramp, and instant fund subscription in Acacia.
- **Meaning preserved.** Some clips join two to four ranges from the same answer with a straight cut. Only restatements, lists of examples, host interjections or passages where the audio could not be transcribed with confidence were removed. Every range is listed in `CLIPS.md`, together with the words each cut leaves out, so each cut can be checked against the episode.
- **Clean edits.** Every edit point sits in the pause between two words (or, where two words run together, at the quietest point between them), so no word is clipped. The audio of each range is matched back to the episode file by cross-correlation to confirm the listed timestamps. The second edit in clip 1 (0:16) was re-cut by hand by the person reviewing the clips, and its ranges in `clips.json` were updated to match (see Human review in `VERIFICATION.md`).
- **Speaker in frame.** A 4:5 window follows the speaker's face shot by shot. In clip 2 the episode is still on the host when the speaker starts "There is limited use...", so that clip opens on a 0.4 s silent beat on the speaker's first frame and holds that frame until the camera cuts to him (0.6 s in all), so the first words are heard in full after the fade-in. The audio is unchanged. In clip 1 the window stops above the episode's own lower-third, so the speaker's name and role appear once, in the clip's own name card.
- **Names and roles.** Each speaker is named with their role and organisation: Vincent Gramoli, Founder, Redbelly Network ([Redbelly's About page](https://redbelly.network/about-us)); Effie Dimitropoulos, CEO, AUDD Digital ([audd.digital](https://www.audd.digital), home of the AUDD stablecoin); Matt Mills, Chief Customer Officer, Tokeniser ([tokeniser.com/about](https://tokeniser.com/about); Tokeniser was formerly Liquidise). The name card in every clip is read back from the video by OCR as part of the verification.

## Brand

Clips and page follow the [Redbelly brand guidelines](https://redbelly.network/brand): the official horizontal negative logo at its native aspect ratio, the brand palette (`#FF5050`, `#283A46`, `#142530`, `#848B91`, `#D9D9D9`, `#ECEBEC`) and the Readex Pro typeface (Medium for headings, Regular for body). Captions highlight the spoken word in brand red.

## Subtitles

- Transcribed with Whisper `medium.en` word timestamps (faster-whisper). Each window was then checked against the full-episode transcript.
- Redbelly terms are enforced by a glossary pass: Redbelly, Redbelly Network, Tokeniser, Project Acacia, AUDM, AUDD. Australian spelling is used throughout (tokenise, tokenisation).
- Every spoken word is shown: tag questions and fillers such as "right?", "you know", "I mean" and "yeah", audible false starts and restarts ("we could show to via Tokeniser", "for that, for that exact reason") and words said more than once ("how you, you couldn't", "there is a this, this, this person"). Only "um" and "uh" are left out; wherever the independent transcript hears one, it is listed with its verdict in `VERIFICATION.md`.
- Word timing comes from forced alignment, not from Whisper: the final subtitle text of each range is aligned to that range's audio with torchaudio's MMS_FA model, so each word lights up when it is actually spoken, including after pauses and fillers ("blockchain, um, is pretty important"). Whisper's own word times were up to a second off around pauses.
- Burned in as word-by-word highlighted captions. Each clip also has an SRT file in `subtitles/` for platforms that take separate caption files. SRT cues are numbered in order and never overlap (each cue ends no later than the next one starts), which the build checks.
- Checked against the audio: the final audio of every clip is transcribed again with a different, larger model (Whisper `large-v3`) and compared word by word with the SRT. Whether each word is on screen while it is spoken is measured with a third model, wav2vec 2.0, whose word times are tied to 20 ms audio frames. Every remaining difference, and every word more than 0.3 s outside its cue, has a written verdict in `verification/review.json` (see `VERIFICATION.md`).

## Audio

Each clip is normalised with two-pass EBU R128 loudness (linear gain) to -14 LUFS integrated (true peak measured at -1.1 to -1.4 dBTP after AAC encoding), which is the common target for X, YouTube and Instagram. All six measure within 1 LU of each other (see `VERIFICATION.md`). The audio is re-timed from its sample count after the loudness pass, so every AAC frame sits on one continuous timeline, which the build checks frame by frame. No music or third-party audio has been added.

## Deploying the review page

The repository root is a static site: `index.html` plus the `clips/`, `subtitles/`, `posters/`, `assets/` and `verification/` folders. Nothing needs building.

- **GitHub Pages:** go to Settings → Pages, choose deploy from branch, pick this branch and the `/ (root)` folder. The `CNAME` file sets the custom domain `podcast.test-hub.xyz`. At your DNS provider, add a `CNAME` record for `podcast` pointing to `<github-user>.github.io`.
- **Vercel / Netlify / Cloudflare Pages:** import the repository with no build command and output directory `/`, then add `podcast.test-hub.xyz` as a custom domain in the host's dashboard.

## Reproducing the pack

Requirements: Python 3.11+, ffmpeg with libass, tesseract, `pip install faster-whisper "opencv-python-headless<5" pillow` and CPU PyTorch with torchaudio (`pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`) for the forced alignment and the timing check. Fonts and logos are in `assets/`.

```bash
# 1. Download the official episode files listed in CLIPS.md as ep26.mp4, ep28.mp4, ep29.mp4 into SRC/
# 2. Word-level transcripts for each clip window (applies the glossary and the fixes in clips.json)
python3 tools/words.py SRC/ WORK/ medium.en
# 3. Render the clips into clips/ and subtitles/
python3 tools/render.py SRC/ WORK/
# 4. Check subtitles, edits and frames against the audio and the source (writes verification/)
python3 tools/verify_av.py SRC/
# 5. Verify every output and regenerate CLIPS.md, VERIFICATION.md and index.html
python3 tools/build_docs.py
```

`clips.json` is the single source of truth: episode, cut ranges, speaker, role, hook, post caption, crop hints and subtitle corrections for every clip.

| File | Purpose |
|---|---|
| `tools/words.py` | Per-clip transcription with word timestamps, glossary and corrections |
| `tools/facetrack.py` | Shot detection and face tracking for the vertical crop |
| `tools/render.py` | Branded 1080×1920 frame, crop, cuts, forced-aligned captions, loudness, H.264 encode |
| `tools/verify_av.py` | Independent transcript of each clip's audio vs its subtitles and their timing, each range matched to the episode, edit points, OCR of the on-screen text every second, face, black and frozen frame checks, contact sheets |
| `tools/build_docs.py` | Measures every output, fails on any spec, spelling, subtitle, edit or on-screen violation or any unreviewed difference, writes the docs and the page |
| `verification/review.json` | Manual verdicts for every difference the automated checks list, and the contact sheet review |
