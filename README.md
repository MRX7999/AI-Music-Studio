<p align="center">
  <img src="docs/banner.svg" alt="AI Music Studio" width="100%">
</p>

<p align="center">
  <a href="https://github.com/MRX7999/AI-Music-Studio/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/MRX7999/AI-Music-Studio/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/MRX7999/AI-Music-Studio/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/MRX7999/AI-Music-Studio?color=ff9f43"></a>
  <img alt="macOS 14+" src="https://img.shields.io/badge/macOS-14%2B%20%C2%B7%20Apple%20Silicon-4fd1c5">
  <img alt="SwiftUI" src="https://img.shields.io/badge/SwiftUI-native-6ca0ff">
  <img alt="Python" src="https://img.shields.io/badge/engine-Python%203.10%E2%80%933.12-b794f6">
  <img alt="MLX" src="https://img.shields.io/badge/local%20models-MLX%20first-4ade80">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-facc15"></a>
</p>

<p align="center">
  <b>Generate a song, put the band on a stage, record it like a real studio, and ship the release.</b><br>
  English · <a href="README.ru.md">Русский</a>
</p>

<p align="center">
  <a href="https://github.com/MRX7999/AI-Music-Studio/releases/latest"><img alt="Download for macOS" src="https://img.shields.io/badge/Download-macOS%20(Apple%20Silicon)-ff9f43?style=for-the-badge&logo=apple&logoColor=white"></a>
</p>

<p align="center">
  <img src="docs/screenshots/app-stage.png" alt="Stage: the band on a scaled room plan" width="100%">
</p>

## From prompt to release

<p align="center"><img src="docs/charts/workflow.png" alt="Generate → Stage → Record and edit → Mix and master → Release → Publish" width="100%"></p>

## Generate

ACE-Step 1.5 on your Mac, Suno through GPTunneL, or the offline demo synth. Every engine option is in the form; the price shows before a paid run.

<p align="center"><img src="docs/screenshots/app-generate.png" alt="Generate page" width="100%"></p>

## Rooms and microphones

Ten rooms from a vocal booth to an arena, twelve microphone models, and the decay of each room is frequency-dependent, as in a real space.

<p align="center"><img src="docs/charts/rooms.png" alt="RT60 of every room at 125 Hz, 1 kHz and 8 kHz" width="100%"></p>

## Mix and master

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/app-mixer.png" alt="Mixer"></td>
    <td width="50%"><img src="docs/screenshots/app-master.png" alt="Master"></td>
  </tr>
  <tr>
    <td align="center">Console strip per musician, sends, meters</td>
    <td align="center">Bus EQ, glue, tape, BS.1770 loudness, true-peak limiter</td>
  </tr>
</table>

## Regenerate any part

Drag over the waveform or click a section chip, write a new prompt or lyrics, and only that range changes. Outside the region the song stays bit-exact.

<p align="center"><img src="docs/screenshots/app-regenerate.png" alt="Regenerate part of a song" width="80%"></p>

## Release

One page from the mix to a publishable release: bandwidth restore, reference mastering, cover, synced lyrics, AI check, distributor package, publishing.

<p align="center"><img src="docs/screenshots/app-release.png" alt="Release page" width="100%"></p>

<p align="center"><img src="docs/screenshots/app-release-steps.png" alt="Reference mastering and AI check" width="80%"></p>

### Bandwidth restore, measured

An MP3-like copy of a demo song, cut at 11 kHz, through the built-in extension (no model installed). FlashSR (MLX) or AudioSR take over when installed.

<p align="center"><img src="docs/charts/bandwidth.png" alt="Spectrum before and after the built-in bandwidth extension" width="100%"></p>

### Reference mastering, measured

The same song matched to another one mastered to −11 LUFS: a linear-phase EQ toward the reference spectrum, then the reference loudness.

<p align="center"><img src="docs/charts/reference.png" alt="Tonal balance and loudness before and after reference matching" width="100%"></p>

<sub>Both charts are computed by the engine: <code>python scripts/readme_charts.py</code>.</sub>

## Local models and publishing

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/app-ai-models.png" alt="Settings: AI Models"></td>
    <td width="50%"><img src="docs/screenshots/app-publishing.png" alt="Settings: Publishing"></td>
  </tr>
  <tr>
    <td align="center">MLX first, then PyTorch, then built-in. Nothing installs without your click</td>
    <td align="center">Telegram, YouTube, AI-check services. Keys live in the Keychain</td>
  </tr>
</table>

## Russian interface

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/app-stage-ru.png" alt="Stage in Russian"></td>
    <td width="50%"><img src="docs/screenshots/app-mixer-ru.png" alt="Mixer in Russian"></td>
  </tr>
</table>

## Under the hood

<p align="center"><img src="docs/charts/architecture.png" alt="SwiftUI app, Python engine, local tools and opt-in network services" width="100%"></p>

## Quick start

1. Get `AI-Music-Studio-1.2.1-macOS-arm64.zip` from the [latest release](https://github.com/MRX7999/AI-Music-Studio/releases/latest), unzip it and move **AI Music Studio.app** to Applications.
2. The app is signed ad hoc, not notarized, so the first launch needs one of these:
   - right-click the app → **Open** → **Open**, or
   - `xattr -dr com.apple.quarantine "/Applications/AI Music Studio.app"`
3. On first launch the app looks for Python 3.10–3.12 with `numpy`, `scipy`, `soundfile` and `requests` (pyenv, Homebrew, python.org, a project `.venv`). If none is found, **Set Up Automatically** creates a private venv in `~/Library/Application Support/AI Music Studio/venv` and installs the pinned [`requirements-engine.txt`](requirements-engine.txt); this needs internet once. You can also point the app at any interpreter with **Choose Python…**.

Requirements: macOS 14 Sonoma or newer, Apple Silicon (Intel Macs can build from source), Python 3.10–3.12, optional `ffmpeg` for ALAC/MP3 export (`brew install ffmpeg`).

<details>
<summary><b>Build from source</b></summary>

```bash
git clone https://github.com/MRX7999/AI-Music-Studio.git
cd AI-Music-Studio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-engine.txt
macos/build_app.sh                 # → dist/AI Music Studio.app and a zip
open "dist/AI Music Studio.app"
```

Xcode 15+ or only the Command Line Tools are enough. With the Command Line Tools alone the script builds against a macOS 26.x/15.x SDK: with the macOS 27 SDK of the Command Line Tools the build fails on SwiftUI's `@State`, which is a macro there. For development, `swift run` from `macos/` starts the app straight from the checkout and finds the engine in the repository (set `SDKROOT` the same way when you only have the Command Line Tools).

The executable also has headless modes that CI and the release process use:

```bash
APP="dist/AI Music Studio.app/Contents/MacOS/AIMusicStudio"
"$APP" --selftest --python .venv/bin/python     # engine workflow, DSP and localization checks, exit code 0/1
"$APP" --screenshots docs/screenshots           # renders the README screenshots from a demo session
"$APP" --smoke 8 /tmp/ams-smoke.json            # opens the window, writes a JSON report, quits
"$APP" --project ~/Music/Demo                   # uses this project folder for one launch, settings stay as they are
```

</details>

## Reference

<details>
<summary><b>All features</b></summary>

| Area | What you get |
|---|---|
| Generate | ACE-Step 1.5 locally (recommended), Suno through GPTunneL Creative Lab (cloud), or the offline demo synth. Title, style with one-click tags, lyrics editor with `[Verse]`/`[Chorus]` section chips, instrumental switch, duration, BPM or auto, key, time signature, vocal language, seed, number of variations, model picker and every engine-specific option read from the engine's schema. GPTunneL shows the price before you start. |
| Stage | Ten rooms from a vocal booth to a stadium. A top-down plan to scale: drag musicians and the listener, see the critical distance and the room pair, zoom into the stage of big rooms, resize the room. |
| Microphones | Twelve microphone models with frequency response, polar pattern, proximity effect and self-noise; distance and off-axis angle per channel. |
| Mixer | A console strip per musician: mic, gain, pan that follows the stage or is set by hand, reverb and delay sends, mute and solo, fader with meters, plus a master strip with loudness and true-peak readouts. |
| Channel inspector | Preamp drive and gate, HPF/LPF and a four-band parametric EQ with a draggable curve, compressor (auto or manual: threshold, ratio, attack, release, knee, make-up) with a transfer curve, stereo width, output. |
| Recording | 44.1/48/96 kHz, 16/24/32-bit, preamps (clean, tube, transformer, opto), A-B, X-Y, ORTF, NOS or Blumlein room pair with height, spacing and time alignment, reverb pre-delay, return and tail, a delay bus (time, feedback, high cut, ping-pong), room ambience. |
| Master | Bus EQ, bus compressor (glue or manual), tape/cassette/vinyl, stereo width, ITU-R BS.1770-4 loudness normalization with presets (Spotify, Apple Music, YouTube, club, EBU R128), 4× oversampled true-peak limiter, fades, TPDF dither. |
| Export | WAV, FLAC, ALAC, MP3 with title/artist/album/genre/year tags and cover art; processed stems on request; loudness report after every render. |
| Listening | Loop preview rendered in the background from any point of the song, A/B between the original and the studio mix, live re-render after every change, level meters per channel. |
| Library | Songs, sessions and renders of the project folder with search; open a song as a fresh session, listen, reveal in Finder; import any audio file and split it into stems (built-in HPSS or Demucs). |
| Workflow | Undo/redo for every change, autosave, sessions as `session.studio.json` with relative paths, English and Russian interface (switch in Settings, engine texts follow). |
| Settings | Language, project folder, preview length, live preview, autosave, monitor volume, stem method; ACE-Step URL and key, GPTunneL key stored in the macOS Keychain; Python interpreter, engine folder, dependency status and engine restart. |

| Area | What you get |
|---|---|
| Regenerate a part | Pick any song in the library (ACE-Step, Suno through GPTunneL, or an imported file), drag over the waveform or click a section chip (`[Verse 2]`, `[Chorus]`) and regenerate only that range with a new prompt or lyrics. ACE-Step re-decodes the whole song, so the app splices the result back with equal-power crossfades: everything outside the region stays bit-exact. Cover/restyle with a closeness slider, extract one instrument, add a track or complete the arrangement (the last three need the ACE-Step base model). |
| Record vocals | Record a take into the open session: input device and channel, level meter with peak hold and clip warning, headphone monitoring, count-in click, the song plays as a backing track from any position. The take is placed on the timeline with the measured input + output latency removed (plus a manual offset), saved to `takes/vocals-take-N.wav` and added as a vocal channel. Optional voice conversion with a local RVC model (mlx-rvc). |
| Release page | A release is a folder built from a song or a render, with an AI disclosure (generated, vocals, lyrics, tools) and steps you run one by one or all at once: bandwidth restore to 48 kHz, reference mastering, cover art 3000×3000, lyrics timing to LRC/SRT, AI-generation check, distributor package. |
| Bandwidth restore | MP3 and 32 kHz generations lose everything above 11–16 kHz. The spectrum view shows the cutoff; FlashSR (MLX) or AudioSR rebuild the top end, and without a model a built-in harmonic exciter regenerates the missing octave from the octave below the cutoff, level-matched to the spectrum just under it. The result keeps the original below the cutoff. |
| Cover art | Z-Image Turbo through mflux (MLX) from a prompt built from the title, genre and mood, or built-in generative art without a model; 3000×3000 JPEG plus a thumbnail. |
| Lyrics timing | Whisper (mlx-whisper first, openai-whisper as fallback) aligns your lyrics word by word and writes `.lrc` and `.srt`; the LRC opens in an editor so you can fix times by hand. |
| AI-generation check | Before publishing, the master runs through independent detectors and you get a per-detector score and a disclosure recommendation. Details are in the AI-generation check section below. |
| Publishing | Telegram channel (audio with cover and caption), YouTube (video from the cover and audio, `containsSyntheticMedia` set when the song is AI-generated, private, unlisted, public or scheduled) and a distributor folder for Spotify, Apple Music, Yandex Music. Nothing is sent until you confirm a summary; failed uploads go to a queue with retry. |
| Reference mastering | Pick a commercial track you like: Matchering 2.0.6 as a separate GPLv3 process, or the built-in matcher (long-term spectrum difference as a linear-phase EQ, ±1–12 dB, adjustable strength, then BS.1770 loudness of the reference and a −1 dBTP true-peak limiter). |
| Settings | **AI Models**: status, license and install command of every local tool, backend per feature (Auto = MLX first), custom path and arguments. **Publishing**: Telegram, YouTube sign-in, Sightengine and ACRCloud keys in the Keychain. |

</details>

<details>
<summary><b>Local models, MLX first</b></summary>

Every neural model runs as a separate command-line tool next to the engine, installed only when you choose to ([requirements-mlx.md](requirements-mlx.md) has the pinned commands). On Apple Silicon the MLX tool is used first, then the PyTorch tool, then a built-in fallback.

| Feature | MLX (Apple Silicon) | Fallback |
|---|---|---|
| Bandwidth restore | [FlashSR in speech-swift](https://github.com/soniqo/speech-swift/blob/main/docs/models/flashsr.md) | AudioSR 0.0.7, built-in |
| Lyrics timing | [mlx-whisper 0.4.3](https://pypi.org/project/mlx-whisper/) | openai-whisper 20250625 |
| Stems | [demucs-mlx 1.6.1](https://pypi.org/project/demucs-mlx/) | Demucs 4.0.1, built-in HPSS |
| Cover art | [mflux 0.24.0](https://github.com/filipstrand/mflux), Z-Image Turbo 4-bit | built-in |
| AI check | [aigm-detector](https://github.com/shoegazerstella/ai-music-detector) (SpecTTTra) | built-in fakeprint |
| Voice conversion | [mlx-rvc](https://github.com/lextoumbourou/mlx-rvc) | — |
| Region regeneration | [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) MLX backend | ACE-Step PyTorch backend |

This is not a rewrite of the app: the engine calls each tool as an adapter with a fixed input/output contract, so a new backend is one entry in `studio/tools.py`.

Tools are found in `PATH`, `~/.local/bin` (uv, pipx), Homebrew, the engine's own Python and every pyenv version, venv (`~/.virtualenvs`, `~/.venv`) and conda/miniforge environment, so a `pip install openai-whisper` into your pyenv Python works without extra setup. If the tool selected in Settings is missing but another one for the same job is installed, the app uses that one and says so. The Z-Image Turbo model (5.9 GB) is downloaded by the app with progress on the first cover; unfinished files of interrupted downloads are removed before it starts.

</details>

<details>
<summary><b>AI-generation check</b></summary>

| Detector | Where it runs | Notes |
|---|---|---|
| fakeprint, built in | offline, NumPy | [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector) (MIT), method from [arXiv:2506.19108](https://arxiv.org/abs/2506.19108); weights ship with the app, results match the reference PyTorch model within 1e-6 |
| aigm-detector | offline, MLX | [shoegazerstella/ai-music-detector](https://github.com/shoegazerstella/ai-music-detector), SpecTTTra ensemble, pinned commit |
| Sightengine | cloud, your key | [AI music detection](https://sightengine.com/docs/ai-generated-music-detection), on the Pro plan ([pricing](https://sightengine.com/pricing)) |
| ACRCloud | cloud, your key | [AI detection in File Scanning](https://docs.acrcloud.com/reference/console-api/file-scanning/metadata/ai-detection) |

Detectors disagree and none is a proof; an [independent comparison of 8 detectors](https://dev.to/han_lou_493c3fecccc66c1f0/i-tested-8-ai-song-detectors-on-the-same-songs-heres-what-actually-works-4lpg) shows how much. The app uses the check to recommend a disclosure, not to hide one: when the song is AI-generated, the release always carries the AI note.

</details>

<details>
<summary><b>Publishing limits</b></summary>

- Telegram bots send audio up to 50 MB ([Bot API](https://core.telegram.org/bots/api)), so the app sends an MP3 320 kbps with tags and the cover.
- A YouTube upload costs quota ([quota costs](https://developers.google.com/youtube/data/determine_quota_cost)); the AI flag is the `status.containsSyntheticMedia` field ([revision history](https://developers.google.com/youtube/data/revision_history)). OAuth clients in Testing mode expire the sign-in after 7 days.
- Spotify, Apple Music and Yandex Music take releases only through a distributor ([Yandex Music terms](https://yandex.ru/support/music/ru/performers-and-copyright-holders/terms), [Apple Music](https://artists.apple.com/support/1108-get-your-next-release-on-apple-music)); the package folder has WAV 24-bit, the cover, lyrics, LRC, `metadata.json` with the AI disclosure, the AI-check report and SHA-256 sums.

</details>

<details>
<summary><b>Generation engines: ACE-Step, GPTunneL, demo</b></summary>

### ACE-Step 1.5, local (recommended)

An open model under the MIT license that runs locally on Mac (MPS), CUDA, ROCm and CPU, generates from 10 seconds to 10 minutes and supports lyrics in 50+ languages ([ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)). The app talks to its REST API, which listens on port 8001 by default ([ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/ACE-Step/ACE-Step-1.5.git
cd ACE-Step-1.5 && uv sync
uv run acestep-api            # server on :8001
```

In the app choose **ACE-Step 1.5** on the Generate page; its card shows the connection status, and the server address and key are in **Settings → Generators**. Details are in [docs/ACE_STEP.md](docs/ACE_STEP.md) and in the [ACE-Step API reference](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md).

### Suno through GPTunneL, cloud (fallback)

A paid option that needs no local GPU. The app uses [Creative Lab API v2](https://docs.gptunnel.ru/creative-lab/create-task/): a task is created with `POST /api/v2/media/tasks` and polled until it is done; Suno returns two variants with cover art and lyrics ([GPTunneL: get task](https://docs.gptunnel.ru/creative-lab/get-task/)). The price is shown before you start through the [price endpoint](https://docs.gptunnel.ru/creative-lab/price/), and the model list comes from the [models endpoint](https://docs.gptunnel.ru/creative-lab/models/).

Paste the key in **Settings → Generators** (it goes to the macOS Keychain) or set `GPTUNNEL_API_KEY`.

### Demo, offline

A procedural synth without AI and without network: drums, bass, keys and a melody at the chosen BPM and key, delivered as stems. It lets you try the whole studio right after installing, and the tests use it.

</details>

<details>
<summary><b>Rooms</b></summary>

| ID | Room | Size | RT60 |
|---|---|---|---|
| `dry` | Dry (no room) | 6×6×3 m | 0 s |
| `booth` | Vocal booth | 2.2×2×2.4 m | 0.18 s |
| `studio_a` | Studio A, mid-size room | 9×7×3.6 m | 0.45 s |
| `live_room` | Live room (in the spirit of Abbey Road Studio 2) | 18×12×7.5 m | 1.2 s |
| `garage` | Garage / rehearsal space | 6×5×2.7 m | 0.55 s |
| `club` | Club for 300 people | 16×14×5 m | 0.9 s |
| `concert_hall` | Concert hall | 40×30×16 m | 2.0 s |
| `cathedral` | Cathedral | 28×70×30 m | 4.5 s |
| `arena` | Arena / stadium | 140×110×35 m | 2.6 s |
| `open_air` | Open air / festival | 80×80×40 m | 0.35 s |
</details>

<details>
<summary><b>Microphones</b></summary>

| ID | Model | Pattern |
|---|---|---|
| `ldc_tube` | Tube LDC (U47 style) | cardioid |
| `ldc_studio` | Studio LDC (U87 style) | cardioid |
| `ldc_bright` | Bright LDC (C414 / AT4050 style) | cardioid |
| `sdc_pencil` | Small-diaphragm condenser (KM184 style) | cardioid |
| `dyn_vocal` | Dynamic vocal (SM58 style) | cardioid |
| `dyn_inst` | Dynamic instrument (SM57 style) | cardioid |
| `dyn_broadcast` | Broadcast dynamic (SM7B style) | cardioid |
| `dyn_kick` | Kick drum mic (D112 / Beta 52 style) | supercardioid |
| `ribbon` | Ribbon (R-121 / Coles 4038 style) | figure-8 |
| `omni_measure` | Measurement omni (DPA 4006 style) | omni |
| `lofi_phone` | Lo-fi / telephone | omni |
| `di` | DI / line (no microphone) | — |

The models are generic curves of microphone classes, not measured profiles of specific units; brand names only hint at the character. Thirteen instrument types (vocals, backing vocals, drums, kick, bass, electric and acoustic guitar, keys, synth, strings, brass, other, full mix) come with starting presets for mic, distance and processing.

</details>

<details>
<summary><b>Signal chain</b></summary>

The app starts the engine as a child process and talks to it with one JSON object per line: requests carry an id, long jobs (generation, rendering, stem separation) stream progress events and can be cancelled. API keys live in the macOS Keychain and reach the engine only over this pipe (`config.set`); they are never written to sessions or settings files.

Signal chain of a channel and of the master bus (`studio/render.py`):

```text
stem → microphone (response, pattern, proximity, noise) → preamp → gate → HPF/LPF/EQ → compressor → width → fader
     ├─► close mic: pan from the stage position (or manual)      → dry bus
     ├─► room pair: direct sound + early reflections of the room → room bus
     ├─► reverb send: diffuse tail of the room (RT60, pre-delay) → reverb bus
     └─► delay send: delay with feedback, high cut, ping-pong    → delay bus
master: dry + room + reverb + delay + ambience → width → EQ → bus compressor → tape
        → LUFS normalization + true-peak limiter → fades → dither → file
```

The position of a musician relative to the listener sets the delay, distance attenuation, air absorption, pan and the direct-to-reverberant ratio. Early reflections use the image-source method for the room dimensions; the tail is a diffuse reverb with the room's RT60.

</details>

<details>
<summary><b>Keyboard shortcuts</b></summary>

| Keys | Action |
|---|---|
| `⌘1` … `⌘5` | Generate · Stage · Mixer · Master · Release |
| `Space` | play / pause the preview |
| `⌘.` | stop |
| `⌘↩` | generate |
| `⌘R` | render the mix |
| `⇧⌘R` | record vocals into the session |
| `⇧⌘E` | regenerate part of the song |
| `⌘O` | import a song |
| `⇧⌘N` | new session from stems |
| `⌘S` | save the session |
| `⌘Z` / `⇧⌘Z` | undo / redo |
| `⌥⌘L` / `⌥⌘I` | show or hide the library / inspector |
| `⌘,` | settings |

</details>

<details>
<summary><b>Python app and CLI</b></summary>

The cross-platform PyQt5 studio from 1.0 and the command line are still here and use the same engine.

<details>
<summary>PyQt interface (Russian)</summary>

![PyQt studio](docs/screenshots/studio.png)

</details>

```bash
pip install -r requirements.txt          # adds PyQt5 and the playlist tools
python studio_app.py                     # PyQt interface (Russian)

python studio_cli.py generate --engine demo --title "North Wind" --duration 60 --bpm 104 --key "A minor" --out out
python studio_cli.py session "out/North Wind/North Wind.wav" --scene concert_hall -o out/session
python studio_cli.py render out/session/session.studio.json --format flac --stems
python studio_cli.py list scenes | mics | instruments
```

`generate` also takes `--style`, `--lyrics`/`--lyrics-file`, `--instrumental`, `--lang`, `--seed`, `--variations`, `--model` and `--extra '{"inference_steps": 8}'` for engine-specific parameters. Optional heavy models (Demucs, and AudioSR/Whisper/librosa for the legacy mastering tab) are in `requirements-ml.txt`.

</details>

<details>
<summary><b>Environment variables</b></summary>

Settings in the app cover everything below; the variables are for the CLI, the PyQt app and CI. Copy `.env.example` to `.env`; `run_studio.command` reads it, in a terminal use `set -a; source .env; set +a`.

| Variable | Purpose |
|---|---|
| `ACESTEP_API_URL` | ACE-Step server, default `http://127.0.0.1:8001` |
| `ACESTEP_API_KEY` | key, if the server runs with authentication |
| `GPTUNNEL_API_KEY` | GPTunneL key for Suno |
| `GPTUNNEL_PLAYLIST_URL` | playlist link for the PyQt "Playlist" tab |
| `GPTUNNEL_ALBUM_NAME` | album name in the tags of downloaded tracks |
| `AMS_PYTHON` | interpreter for the macOS app engine (same as Settings → Engine) |
| `AMS_ENGINE_DIR` | engine folder for the macOS app, if not the bundled one |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram publishing |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | YouTube publishing (the app gets the refresh token through **Connect Account**) |
| `SIGHTENGINE_API_USER`, `SIGHTENGINE_API_SECRET` | Sightengine AI-music check |
| `ACRCLOUD_TOKEN`, `ACRCLOUD_CONTAINER_ID`, `ACRCLOUD_REGION` | ACRCloud AI detection |

</details>

<details>
<summary><b>Tests</b></summary>

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen pytest -q
```

93 Python tests cover DSP and loudness, the v1.2 tools (spectrum cutoff, bandwidth restore, splice bit-exactness, LRC alignment, fakeprint detector, release steps, built-in bandwidth extension and reference matcher, Telegram/YouTube request building against mocks, the publish confirmation guard), rendering in all ten rooms (LUFS within ±1.5, true peak ≤ −0.5 dBTP), pan from position, mute/solo, sessions, the engine server protocol, the ACE-Step and GPTunneL protocols against local mock servers, and the PyQt workflow from generation to recording. The macOS job builds the app bundle and runs `--selftest`, which drives the real engine through generate → session → scene → channel edit → undo → preview → meters → final render → save → library → release (built-in bandwidth extension, reference master, cover, fakeprint check, distributor package) → publish guard → splice → recorder timing math → Russian localization. CI runs both on every push.

</details>

<details>
<summary><b>Project layout</b></summary>

```text
AI-Music-Studio/
├── macos/                     # native app (SwiftUI, Swift Package)
│   ├── Package.swift
│   ├── build_app.sh           # .app bundle + zip
│   ├── Resources/             # app icon
│   └── Sources/AIMusicStudio/ # views, store, engine client, player, DSP previews
├── studio/
│   ├── engine_server.py       # JSON-lines engine for the macOS app
│   ├── dsp.py  loudness.py  mics.py  scenes.py  session.py  render.py  stems.py  audio_io.py
│   ├── library.py  i18n.py    # project folder scan, English/Russian texts
│   ├── generators/            # acestep (generate + repaint/cover/extract), gptunnel, demo
│   ├── tools.py               # registry of external MLX/PyTorch tools, doctor
│   ├── spectrum.py  superres.py  lyrics.py  cover.py  detect.py  refmaster.py  voice.py  editing.py
│   ├── models/fakeprint/      # built-in AI detector weights (MIT)
│   ├── publish/               # release folders, Telegram, YouTube, distributor package, queue
│   └── ui/                    # PyQt5 interface
├── studio_app.py  studio_cli.py
├── full_pipeline.py  gui_pipeline.py  humanize.py  download_playlist.py   # tools from the original project
├── tests/  scripts/  docs/
└── requirements*.txt  requirements-mlx.md
```

</details>

<details>
<summary><b>Limitations</b></summary>

- This is modeling, not ray tracing: reflections are image sources in a rectangular room, the tail is a statistical reverb.
- The built-in HPSS splits a mixed song into four pseudo-stems (bass, percussion, center, sides); clean vocal separation needs Demucs (`requirements-ml.txt`).
- ACE-Step is installed and started separately; Suno through GPTunneL is paid and needs a key.
- The release build is for Apple Silicon and not notarized; Intel Macs can build it from source with `macos/build_app.sh`.
- Plugins (Audio Units) are not hosted: the render runs in the Python engine.
- Live recording latency comes from what Core Audio reports; Bluetooth headphones add more than they report, so use wired ones or the offset slider.
- When you publish generated music, follow the model license and the platform rules, including AI-content disclosure requirements.

</details>

## License

[MIT](LICENSE). ACE-Step, Suno, GPTunneL, Demucs, AudioSR, Whisper, FlashSR, mflux, Z-Image, Matchering (GPL-3.0, not bundled), mlx-rvc and the detector models are covered by their own licenses and terms. The bundled fakeprint weights are MIT, see `studio/models/fakeprint/NOTICE`.

