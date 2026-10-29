# ACE-Step 1.5: локальная генерация

[ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) — открытая модель генерации песен под лицензией MIT. Она работает на Mac (MPS), CUDA, ROCm, Intel XPU и CPU, генерирует от 10 секунд до 10 минут и поддерживает тексты на 50+ языках. AI Music Studio не встраивает модель, а обращается к её REST-серверу, поэтому ACE-Step ставится в отдельную папку со своим окружением.

## Установка (macOS Apple Silicon)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/ACE-Step/ACE-Step-1.5.git
cd ACE-Step-1.5
uv sync
```

Авторы рекомендуют Python 3.11–3.12. Первый запуск скачивает веса модели, это займёт время и место на диске.

## Запуск сервера

```bash
cd ACE-Step-1.5
uv run acestep-api        # http://localhost:8001
```

Проверка из терминала:

```bash
curl -s http://127.0.0.1:8001/health
```

Если сервер запущен на другой машине или порту, укажите адрес в поле «Адрес ACE-Step» или в переменной `ACESTEP_API_URL`. Если сервер требует ключ, задайте `ACESTEP_API_KEY` — приложение отправит его как `Authorization: Bearer …`.

## Как приложение использует API

Протокол описан в [docs/en/API.md](https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md) репозитория ACE-Step.

| Шаг | Запрос |
|---|---|
| Проверка сервера | `GET /health` |
| Список моделей | `GET /v1/models` |
| Запуск генерации | `POST /release_task` |
| Статус | `POST /query_result` (0 — в работе, 1 — готово, 2 — ошибка) |
| Скачивание | `GET /v1/audio?path=…` |

Поля формы переходят в запрос так:

| Форма | Поле API |
|---|---|
| Стиль | `prompt` |
| Текст (или `[Instrumental]`) | `lyrics` |
| Длительность, с (10–600) | `audio_duration` |
| Язык | `vocal_language` |
| Варианты (1–8) | `batch_size` |
| BPM, тональность, размер | `bpm`, `key_scale`, `time_signature` |
| Seed (−1 — случайный) | `seed`, `use_random_seed` |
| Шаги диффузии (turbo: 8) | `inference_steps` |
| Guidance (base-модели) | `guidance_scale` |
| LM-«размышление» | `thinking` |
| Формат с сервера | `audio_format` |

Готовые файлы сохраняются в `<папка проекта>/generated/<дата>/` (по умолчанию `~/Music/AI Music Studio/generated/…`) вместе с `<название>.json`: параметры, текст, сид. Кнопка «→ В студию» открывает трек в студии; ACE-Step отдаёт готовую песню одним файлом, поэтому приложение предложит разделить её на дорожки (HPSS встроен, Demucs — из `requirements-ml.txt`).

## Частые проблемы

| Симптом | Что сделать |
|---|---|
| «нет соединения с http://127.0.0.1:8001» | сервер не запущен или слушает другой порт — запустите `uv run acestep-api` |
| Генерация идёт очень долго | на base-моделях уменьшите `inference_steps`, отключите «размышление» или используйте turbo |
| Не хватает памяти | уменьшите число вариантов и длительность; закройте другие ML-процессы |
