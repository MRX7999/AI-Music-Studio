# Changelog · Изменения

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
