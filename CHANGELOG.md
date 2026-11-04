# Changelog · Изменения

## 1.2.2 — 2026-11-04

The distributor package now asks for the format, like Export, and writes the cover, lyrics and release data into the audio file.

### Added
- Release → Distributor package: format WAV, FLAC, ALAC or MP3; sample rate 44.1, 48, 88.2 or 96 kHz (MP3: 44.1 or 48); bit depth 16, 24 or 32-bit float (FLAC and ALAC: 16 or 24) with TPDF dither, or MP3 bitrate 128–320 kbps. The choice is remembered and the publish queue rebuilds the package with it.
- Tags inside the audio file: title, artist, album artist, album, genre, release date and year, composer, lyricist, producer, label, copyright, ISRC, UPC, language (ISO 639-2), explicit flag, track 1/1, the AI note as a comment, plain lyrics and the 3000 px front cover. MP3: ID3v2.3; WAV: LIST INFO plus an ID3v2.3 chunk (read by Finder, Music, foobar2000, Mp3tag); FLAC: Vorbis comments and a PICTURE block; ALAC (M4A): iTunes atoms with the cover and lyrics. "Cover in the file" and "Lyrics in the file" switches.
- Fields for album, release date, composer, lyricist, producer, label, copyright, ISRC, UPC and explicit next to the format; they are saved with the release and go to the tags and `metadata.json`.
- `metadata.json` gains `file`, `format`, `mp3_bitrate_kbps`, `dither` and `embedded_tags`; `checks.json` gains `format` (warns about MP3 and 32-bit float, which distributors often refuse) and `tags`.

### Changed
- `lyrics.txt` holds plain lyrics without `[Verse]`-style tags, with a blank line between sections; it falls back to the LRC lines.
- `package.build`, `release.step` (`package`) and the `package` publish job accept `format`, `sample_rate`, `bit_depth`, `mp3_bitrate`, `dither`, `embed_cover`, `embed_lyrics`. Without options the result is the same WAV 44.1 kHz / 24-bit as before, now with tags.
- ALAC and MP3 need ffmpeg (`brew install ffmpeg`); WAV and FLAC are written without it. No new Python dependencies: the tags are written by `studio/tags.py`.

### Добавлено
- «Релиз» → «Пакет для дистрибьютора»: выбор формата как в экспорте — WAV, FLAC, ALAC или MP3, частота 44,1–96 кГц, разрядность 16/24/32-bit float с дизерингом TPDF или битрейт MP3 128–320 кбит/с. Выбор запоминается, очередь публикации собирает пакет с ним же.
- Теги в самом аудиофайле: название, исполнитель, альбом, жанр, дата, композитор, автор текста, продюсер, лейбл, копирайт, ISRC, UPC, язык, explicit, пометка об ИИ, текст без меток разделов и обложка 3000 px. MP3 — ID3v2.3, WAV — LIST INFO и ID3, FLAC — Vorbis comments и PICTURE, ALAC — атомы iTunes.
- Поля альбома, даты релиза, авторов, лейбла, копирайта, ISRC, UPC и explicit рядом с форматом; сохраняются в релизе.

### Изменено
- `lyrics.txt` — чистый текст без меток `[Куплет]`. ALAC и MP3 требуют ffmpeg, WAV и FLAC — нет. Новых зависимостей Python нет.

## 1.2.1 — 2026-11-04

Fixes for three problems reported on 1.2.0.

### Fixed
- Cover, repaint and the other ACE-Step edits finished on the server, but the studio showed "could not convert string to float: 'N/A'" and the variants were missing from the library. In these modes ACE-Step 1.5 runs without its language model and reports BPM, duration and key as `"N/A"`; the engine now reads them as "unknown" and takes the duration from the audio file. Variants already made with 1.2.0 appear in the library again; their files are not changed. Each variant gets its own seed instead of the whole batch string.
- openai-whisper (and other tools) installed with `pip` into a pyenv version, a venv or a conda environment was not found. The search now covers the engine's own Python, `~/.pyenv/versions/*/bin`, `~/.virtualenvs`, `~/.venv`, miniforge/miniconda/anaconda and python.org framework installs; pyenv shims and scripts whose interpreter was removed are skipped. When the tool selected in Settings is missing, another installed tool for the same job is used and the app shows it (Settings → AI Models, Release → Lyrics). openai-whisper uses a checkpoint already in `~/.cache/whisper` (for example `medium`) instead of downloading `turbo`. A bilingual language field ("en / ru") no longer forces a wrong Whisper language.
- Z-Image Turbo covers failed with an incomplete model: the 5.9 GB model was left half-downloaded, because huggingface_hub cannot continue an interrupted file and starts it over, leaving dead `*.incomplete` files. The app now checks the model offline, downloads it itself before the first cover (mflux's own huggingface_hub, network retries, free-space check, progress in GB with speed and time left, cancel removes its partial files), removes unfinished files of earlier attempts, and then runs mflux offline. Errors say what happened: no connection with how much is downloaded, not enough disk space, not enough memory.

### Changed
- `tools.doctor` reports the search directories, the backend that was asked for and whether a fallback is used, and the model state for mflux and openai-whisper.
- `tools.run` accepts extra environment variables and exact `@progress` lines from the bundled scripts.

### Исправлено
- Кавер, перегенерация фрагмента и другие правки ACE-Step: сервер всё делал, а студия показывала «could not convert string to float: 'N/A'», и варианты не появлялись в библиотеке. Теперь «N/A» читается как «неизвестно», длительность берётся из файла; варианты, сделанные в 1.2.0, снова видны.
- Whisper, установленный через `pip` в pyenv, venv или conda, не находился. Теперь поиск охватывает эти окружения, а если выбранный инструмент не установлен, используется другой установленный для той же задачи. openai-whisper берёт уже скачанную модель (например, `medium`).
- Обложка через Z-Image Turbo не создавалась из-за недокачанной модели. Приложение само докачивает модель с прогрессом, удаляет недокачанные файлы прошлых попыток и запускает mflux офлайн; ошибки объясняют причину.

## 1.2.0 — 2026-11-03

From a generated song to a published release, with local models first. Audio Units hosting is not part of this release.

### Added
- Regenerate part of a song (ACE-Step 1.5 repaint) from the library, a generation result or the open session: region on the waveform or by section, new prompt or lyrics, conservative/balanced/aggressive mode, up to four variants. The result is spliced back with equal-power crossfades and an alignment check, so the audio outside the region stays bit-exact, also for Suno/GPTunneL and imported songs. Cover/restyle, extract, add a track (lego) and complete with the base model. `studio/editing.py`, `edit.run`, `edit.splice`.
- Vocal recording into the session: input device and channel, meter with peak hold and clip warning, headphone monitoring, count-in, backing playback from any position, latency compensation from Core Audio plus a manual offset; takes in `takes/`, added as a vocal channel; optional RVC conversion (mlx-rvc).
- Release page (`⌘5`): release folders with AI disclosure; steps bandwidth restore, cover, lyrics timing, AI check, distributor package; publishing to Telegram and YouTube with a confirmation summary, a queue, retries and a log.
- Spectrum analysis and bandwidth restore to the export rate: FlashSR (MLX, speech-swift) with two-pass window blending, AudioSR 0.0.7, or a built-in harmonic bandwidth extension (no model); the original is kept below the cutoff.
- Cover art: Z-Image Turbo through mflux 0.24.0 (MLX) or built-in generative art; 3000×3000 JPEG and a thumbnail.
- Lyrics timing to LRC/SRT with mlx-whisper 0.4.3 or openai-whisper 20250625, aligned to the user's lyrics.
- AI-generation check: built-in fakeprint detector (MIT weights bundled, NumPy port matching the PyTorch reference), aigm-detector (MLX), Sightengine and ACRCloud with your keys; per-detector scores and a disclosure recommendation.
- Reference mastering as a release step: Matchering 2.0.6 as a separate GPLv3 process, or a built-in matcher (linear-phase EQ toward the reference spectrum with strength and range, BS.1770 loudness match, −1 dBTP limiter).
- Stems through demucs-mlx 1.6.1 or Demucs 4.0.1 as external tools.
- Settings → AI Models (tool status, license, install command, backend per feature, custom path and arguments) and Settings → Publishing (Telegram, YouTube sign-in, Sightengine, ACRCloud; secrets in the Keychain).
- `studio/tools.py` registry and `tools.doctor`; `requirements-mlx.md` with pinned install commands.
- New environment variables in `.env.example` for Telegram, YouTube, Sightengine and ACRCloud.

### Changed
- Engine messages are translated to Russian when the interface is Russian.
- The app bundle copies the bundled model weights and their NOTICE files; `Info.plist` declares microphone use.
- README rebuilt around screenshots and charts generated from real engine output (`scripts/readme_charts.py`); reference tables moved into collapsible sections.
- The Render button no longer wraps in narrow windows; the release page fits the window and the step strip scrolls.

### Добавлено
- Перегенерация части песни (ACE-Step repaint) со склейкой: вне фрагмента звук остаётся бит-в-бит; кавер, извлечение, добавление дорожки, дописывание аранжировки.
- Запись вокала в сессию с мониторингом, отсчётом, фонограммой, компенсацией задержки и обработкой RVC.
- Страница «Релиз»: восстановление спектра, обложка, LRC, проверка на ИИ, пакет для дистрибьютора, публикация в Telegram и на YouTube с подтверждением и очередью.
- Настройки «AI-модели» и «Публикация»; локальные модели через MLX с запасными вариантами.

## 1.1.0 — 2026-10-29

Native macOS studio. The Python engine stays the same project, the interface is now SwiftUI.

### Added
- macOS app in `macos/` (SwiftUI, Swift Package, macOS 14+): Generate, Stage, Mixer and Master pages, a library sidebar, a channel/room inspector, a transport bar with an LCD time display, A/B source switch, output meter and a waveform timeline with the loop region.
- Generate page: engine cards with live status, style tags, lyrics editor with section chips, all common and engine-specific parameters from the engine schema, price estimate for GPTunneL, cancel.
- Stage: plan to scale with draggable musicians and listener, critical distance, room pair, zoom, room size.
- Mixer: channel strips with mic, gain, pan (auto from the stage or manual), reverb and delay sends, mute/solo, faders and meters; master strip with LUFS and true peak.
- Channel inspector: preamp drive, gate, HPF/LPF, four-band parametric EQ with a draggable curve, manual compressor with a transfer curve, width, phase.
- Recording and master: room techniques A-B, X-Y, ORTF, NOS, Blumlein; reverb pre-delay and return; delay bus (time, feedback, high cut, ping-pong); master EQ; manual bus compressor; loudness presets, fades, tail length, dither switch; editable room size, HF/LF decay, early-reflection level and ambience.
- Settings window: language (English/Russian), project folder, preview length, live preview, autosave, monitor volume, stem method; ACE-Step URL/key and GPTunneL key in the macOS Keychain; Python interpreter, engine folder, dependency status, automatic venv setup.
- Undo/redo for every session edit (continuous drags are one step), autosave, keyboard shortcuts.
- `studio/engine_server.py`: JSON-lines engine for the app with progress events, cancellation and background previews; `studio/library.py` (project folder scan) and `studio/i18n.py` (English/Russian engine texts).
- `macos/build_app.sh` builds the `.app` with the engine inside and a zip; `--selftest`, `--screenshots`, `--smoke` and `--project` options; CI job on macOS.
- `requirements-engine.txt`: pinned engine packages without PyQt.
- README in English (`README.md`) and Russian (`README.ru.md`) with screenshots of the new app.

### Changed
- Compressor topology: attack and release now smooth the gain reduction after the static curve (detector → curve → smoothing) instead of smoothing the detector level, so the times behave like the knobs say and no longer depend on how quiet the signal was before a transient. Channel and bus compression on existing sessions can sound slightly different from 1.0.
- Session values are coerced to the field types on load and unknown fields are skipped; sessions from 1.0 open with the new fields at their defaults.
- Scene, microphone and instrument names come from the engine in the interface language; channels that still have their default instrument name follow a language switch, names you typed stay.

## 1.0.0 — 2026-10-29

Первый открытый релиз. Проект `Music_downloader` (загрузка плейлиста, мастеринг AudioSR/Whisper) превращён в AI Music Studio.

### Добавлено
- Вкладка «Генерация»: ACE-Step 1.5 (локальный REST API), Suno через GPTunneL Creative Lab API v2, офлайн демо-синтезатор; форма песни с тегами стиля и структуры, BPM, тональностью, размером, языком, seed, вариантами и параметрами движка; оценка цены для GPTunneL; история результатов.
- Вкладка «Студия»: сцена с перетаскиванием музыкантов, 10 помещений, 12 моделей микрофонов, канальная обработка, микшер с Mute/Solo, превью фрагмента, запись микса и обработанных стемов, отчёт по громкости.
- Движок записи: ранние отражения методом мнимых источников, диффузный хвост с RT60, room-пара A-B, преампы, лента/кассета/винил, bus-компрессор, LUFS по BS.1770-4, true-peak лимитер с 4x оверсэмплингом, дизеринг; экспорт WAV/FLAC/ALAC/MP3 с тегами.
- Разделение готовой песни на дорожки: встроенный HPSS или Demucs.
- Сессии `session.studio.json`, CLI `studio_cli.py` (`generate`, `session`, `render`, `list`).
- Хранение ключа GPTunneL в связке ключей macOS.
- Тесты (37), CI на GitHub Actions, скрипты установки и запуска для macOS.

### Изменено
- `download_playlist.py`: адрес плейлиста и название альбома берутся из `GPTUNNEL_PLAYLIST_URL` / `GPTUNNEL_ALBUM_NAME` или аргументов `--album`, в коде больше нет личных значений по умолчанию.
- `gui_pipeline.py` встроен в приложение как вкладка «Мастеринг» без изменений логики.
