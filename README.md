# Redbelly Insights Podcast Clip Pack

Six captioned vertical clips (30 to 60 seconds) cut from the latest official Redbelly Insights episodes, each making one point about Redbelly technology, Project Acacia or Tokeniser. They are ready to post on X, YouTube Shorts and Instagram.

| Deliverable | Where |
|---|---|
| 1. Six vertical clips with burned-in subtitles | [`clips/`](clips) (MP4, 1080×1920, 9:16, 30 fps, H.264 + AAC) |
| Subtitles as separate files | [`subtitles/`](subtitles) (SRT, one per clip) |
| 2. Source episode, timestamps and post caption for each clip | [`CLIPS.md`](CLIPS.md) |
| Measured checks for every clip (specs, loudness, spelling) | [`VERIFICATION.md`](VERIFICATION.md) |
| Review page with players, sources, captions and downloads | [`index.html`](index.html) (poster frames in `posters/`) |
| Brand assets: official Redbelly logos from the [Redbelly brand kit](https://redbelly.network/brand) and the brand typeface Readex Pro (SIL OFL, licence in `assets/fonts/OFL.txt`) | [`assets/`](assets) |

## The clips

| # | Hook | Speaker | Source |
|---|------|---------|--------|
| 1 | Why an Aussie dollar stablecoin runs on Redbelly | Effie Dimitropoulos, CEO, AUDD Stablecoin | Episode 29 (9 July 2026) |
| 2 | A tokenised invoice is just a PDF. The workflow is the value. | Vincent Gramoli, Founder, Redbelly Network | Episode 28 (11 June 2026) |
| 3 | Try to double-spend and you get caught | Vincent Gramoli, Founder, Redbelly Network | Episode 28 (11 June 2026) |
| 4 | Every AI agent needs a human who answers for it | Vincent Gramoli, Founder, Redbelly Network | Episode 28 (11 June 2026) |
| 5 | Everyone wants tokenisation. Tokeniser is the how. | Matt Mills, Tokeniser (formerly Liquidise) | Episode 26 (26 March 2026) |
| 6 | Project Acacia: fund units issued the moment you pay | Matt Mills, Tokeniser (formerly Liquidise) | Episode 26 (26 March 2026) |

Exact timestamps, full transcripts and suggested post captions are in [`CLIPS.md`](CLIPS.md).

## How the moments were chosen

- **Latest first.** Episodes 29, 28, 27, 26 and 25 (the five most recent on [redbelly.network/ama](https://redbelly.network/ama)) were transcribed in full. Episode 27 (AUDM stablecoin) is mostly about stablecoins and FX in general, and Episode 25 overlaps Episode 28 on accountability, so the six clips come from Episodes 29, 28 and 26.
- **On brief.** Every clip is about Redbelly technology, Project Acacia or Tokeniser. Each makes one point, and no two make the same point: sovereign AUD stablecoin infrastructure, tokenised workflows, accountable consensus, AI-agent accountability, Tokeniser as the on-ramp, and instant fund subscription in Acacia.
- **Meaning preserved.** Some clips join two to four ranges from the same answer with a straight cut. Only restatements, lists of examples, host interjections or passages where the audio could not be transcribed with confidence were removed. Every range is listed in `CLIPS.md` so each cut can be checked against the episode.
- **Speaker in frame.** A 4:5 window follows the speaker's face shot by shot. In clip 2 the episode cuts to the host for the first 0.3 s, so that clip starts on "There is limited use..." and holds the first frame of the speaker until the camera cuts back. The audio is unchanged.
- **Names and roles.** Roles come from Redbelly's About page (Vincent Gramoli), the on-screen title in Episode 29 (Effie Dimitropoulos) and the episode itself (Matt Mills, who introduces Liquidise as becoming Tokeniser).

## Brand

Clips and page follow the [Redbelly brand guidelines](https://redbelly.network/brand): the official horizontal negative logo at its native aspect ratio, the brand palette (`#FF5050`, `#283A46`, `#142530`, `#848B91`, `#D9D9D9`, `#ECEBEC`) and the Readex Pro typeface (Medium for headings, Regular for body). Captions highlight the spoken word in brand red.

## Subtitles

- Transcribed with Whisper `medium.en` word timestamps (faster-whisper). Each window was then checked against the full-episode transcript.
- Redbelly terms are enforced by a glossary pass: Redbelly, Redbelly Network, Tokeniser, Project Acacia, AUDM, AUDD. Australian spelling is used throughout (tokenise, tokenisation).
- Burned in as word-by-word highlighted captions. Each clip also has an SRT file in `subtitles/` for platforms that take separate caption files.

## Audio

Each clip is normalised with two-pass EBU R128 loudness (linear gain) to -14 LUFS integrated (true peak measured at -1.0 to -1.3 dBTP after AAC encoding), which is the common target for X, YouTube and Instagram. All six measure within 1 LU of each other (see `VERIFICATION.md`). No music or third-party audio has been added.

## Deploying the review page

The repository root is a static site: `index.html` plus the `clips/` and `subtitles/` folders. Nothing needs building.

- **GitHub Pages:** go to Settings → Pages, choose deploy from branch, pick this branch and the `/ (root)` folder. The `CNAME` file sets the custom domain `podcast.test-hub.xyz`. At your DNS provider, add a `CNAME` record for `podcast` pointing to `<github-user>.github.io`.
- **Vercel / Netlify / Cloudflare Pages:** import the repository with no build command and output directory `/`, then add `podcast.test-hub.xyz` as a custom domain in the host's dashboard.

## Reproducing the pack

Requirements: Python 3.11+, ffmpeg with libass, `pip install faster-whisper "opencv-python-headless<5" pillow`. Fonts and logos are in `assets/`.

```bash
# 1. Download the official episode files listed in CLIPS.md as ep26.mp4, ep28.mp4, ep29.mp4 into SRC/
# 2. Word-level transcripts for each clip window (applies the glossary and the fixes in clips.json)
python3 tools/words.py SRC/ WORK/ medium.en
# 3. Render the clips into clips/ and subtitles/
python3 tools/render.py SRC/ WORK/
# 4. Verify every output and regenerate CLIPS.md, VERIFICATION.md and index.html
python3 tools/build_docs.py
```

`clips.json` is the single source of truth: episode, cut ranges, speaker, role, hook, post caption, crop hints and subtitle corrections for every clip.

| File | Purpose |
|---|---|
| `tools/words.py` | Per-clip transcription with word timestamps, glossary and corrections |
| `tools/facetrack.py` | Shot detection and face tracking for the vertical crop |
| `tools/render.py` | Branded 1080×1920 frame, crop, cuts, captions, loudness, H.264 encode |
| `tools/build_docs.py` | Measures every output, fails on any spec, spelling or credit violation, writes the docs and the page |
