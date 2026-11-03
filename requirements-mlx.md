# Optional local models · Необязательные локальные модели

AI Music Studio 1.2 runs every neural model as a separate command-line tool next to the engine. Nothing here is required: each feature has a built-in fallback or simply stays off. Install only what you need. On Apple Silicon the MLX tool is picked first; if it is missing, the PyTorch tool or the built-in fallback takes over. You can see the status, change the backend per feature, set a custom path or arguments in **Settings → AI Models**.

AI Music Studio 1.2 запускает каждую нейросеть отдельной программой рядом с движком. Ничего из этого не обязательно: у каждой функции есть встроенный запасной вариант, либо она просто выключена. Ставьте только нужное. На Apple Silicon сначала берётся MLX-инструмент; если его нет — PyTorch-версия или встроенный вариант. Статус, выбор бэкенда, свой путь и аргументы — в **Настройки → AI-модели**.

Prerequisites · Что нужно заранее:

```bash
brew install uv ffmpeg            # uv 0.9+ for isolated tools, ffmpeg for MP3/MP4/M4A
```

`uv tool install` puts every tool in its own virtual environment under `~/.local/share/uv/tools` and its command into `~/.local/bin`; the engine looks there and in `PATH`. Remove a tool with `uv tool uninstall <name>`.

## Feature → tool

| Feature | MLX first (Apple Silicon) | Fallback | License |
|---|---|---|---|
| Bandwidth restore to 48 kHz | FlashSR via speech-swift: `brew install speech` | AudioSR 0.0.7 (PyTorch): `uv tool install audiosr==0.0.7`; built-in harmonic extension | Apache-2.0 / MIT weights · MIT |
| Lyrics timing (LRC, SRT) | `uv tool install mlx-whisper==0.4.3` | `uv tool install openai-whisper==20250625` | MIT |
| Stem separation | `uv tool install demucs-mlx==1.6.1` | `uv tool install demucs==4.0.1`; built-in HPSS | MIT |
| Cover art | `uv tool install mflux==0.24.0` (Z-Image Turbo 4-bit, about 6 GB download on first run) | built-in generative art | MIT / Apache-2.0 |
| AI-generation check | built-in fakeprint (MIT, offline, always on) plus `uv tool install "aigm-detector[mlx] @ git+https://github.com/shoegazerstella/ai-music-detector@83db9aca8215db53dc539e217414e18ffdb633ad"` | Sightengine and ACRCloud with your keys | MIT; weights have their own licenses |
| Voice conversion (RVC) | `uv tool install "mlx-rvc @ git+https://github.com/lextoumbourou/mlx-rvc@f26633539f1aa935337d8ca5e96c78784698bd7a"` | — | repo has no license file: personal use |
| Reference mastering | Matchering 2.0.6 in its own venv: `uv venv ~/.ams-tools/matchering && uv pip install -p ~/.ams-tools/matchering matchering==2.0.6` | built-in reference EQ and loudness match | GPL-3.0, runs as a separate process, not bundled |
| Region regeneration, cover, extract | ACE-Step 1.5 server (MLX backend on Apple Silicon), see the README | — | Apache-2.0 / MIT |

## Check

```bash
speech upsample --help                    # FlashSR
mlx_whisper --help
demucs-mlx --help
mflux-generate-z-image-turbo --help
aigm-detector --help
mlx-rvc --help
~/.ams-tools/matchering/bin/python -c "import matchering; print(matchering.__version__)"
```

Then press **Check Again** in Settings → AI Models.

## Notes

- Model weights download on the first run of each tool (Hugging Face cache in `~/.cache/huggingface`).
- The MLX DiT of ACE-Step ignores `cover_noise_strength` in some versions ([ACE-Step issue #1346](https://github.com/ace-step/ACE-Step-1.5/issues/1346)); if cover strength has no effect, run the ACE-Step server with the PyTorch backend for cover jobs.
- FlashSR works on 5.12 s windows of 48 kHz mono; the engine runs each channel twice with a half-window offset and blends the passes, so window seams do not show.
