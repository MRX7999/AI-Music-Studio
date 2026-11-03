"""English names and descriptions for the engine library (the Russian ones live next to the data).

Used by the engine server and the native macOS app: `localized(kind, id, field, lang)`.
"""
from __future__ import annotations

import re

SCENES_EN = {
    "dry": ("Dry (no room)", "Close mics only, no acoustics. Electronic music and further mixing."),
    "booth": ("Vocal booth", "Dead booth: intimate close vocal, almost no reflections."),
    "studio_a": ("Studio A — medium room", "Balanced studio room for tracking a whole band."),
    "live_room": ("Live room (Abbey Road Studio 2 style)",
                  "High ceiling and wood: big live sound for drums and strings."),
    "garage": ("Garage / rehearsal space", "Concrete and dense early reflections: raw garage rock and punk."),
    "club": ("Club, 300 capacity", "Low hall, the audience absorbs the highs, crowd murmur between songs."),
    "concert_hall": ("Concert hall", "Classic shoebox hall: an enveloping ~2 s tail."),
    "cathedral": ("Cathedral", "Stone and a huge volume: choir, organ, ambient. A 4–5 s tail."),
    "arena": ("Arena / stadium", "Huge space, long reflections from the stands, the noise of a big crowd."),
    "open_air": ("Open-air festival", "Almost no reflections: direct sound from the PA, wind and crowd outdoors."),
}

MICS_EN = {
    "ldc_tube": ("Tube LDC (U47 style)", "Dense, warm, expensive-sounding vocal. The tube adds soft harmonics."),
    "ldc_studio": ("Studio LDC (U87 style)", "Universal workhorse: vocals, acoustic, strings, overheads."),
    "ldc_bright": ("Bright LDC (C414 / AT4050 style)", "Detailed top, modern airy pop vocal, acoustic guitar."),
    "sdc_pencil": ("Small condenser (KM184 style)", "Accurate transients: acoustic, hi-hats, overheads, piano."),
    "dyn_vocal": ("Dynamic vocal (SM58 style)", "Stage and live: dense mids, highs roll off above 14 kHz."),
    "dyn_inst": ("Dynamic instrument (SM57 style)", "Snare and guitar cab: aggressive 6 kHz presence."),
    "dyn_broadcast": ("Broadcast dynamic (SM7B style)", "Smooth, dark, little room. Rock vocal, podcast, rap."),
    "dyn_kick": ("Kick mic (D112 / Beta 52 style)", "Weight at 60 Hz, scooped 400 Hz box and beater click."),
    "ribbon": ("Ribbon (R-121 / Coles 4038 style)", "Soft vintage top. Guitar cabs, brass, room pair."),
    "omni_measure": ("Measurement omni (DPA 4006 style)", "Honest response and lots of room: classical, acoustic ensembles."),
    "lofi_phone": ("Lo-fi / telephone", "Narrow 300–3400 Hz band with overdrive. For intros and effects."),
    "di": ("DI / line (no mic)", "Direct signal without coloration or room — synths, bass DI."),
}

PATTERNS_EN = {
    "omni": "Omni", "subcardioid": "Subcardioid", "cardioid": "Cardioid",
    "supercardioid": "Supercardioid", "hypercardioid": "Hypercardioid", "figure8": "Figure-8",
}

INSTRUMENTS_EN = {
    "vocals": "Vocals", "backing": "Backing vocals", "drums": "Drums", "kick": "Kick", "bass": "Bass",
    "guitar": "Guitar", "acoustic": "Acoustic guitar", "piano": "Piano / keys", "synth": "Synth / pad",
    "strings": "Strings", "brass": "Brass", "other": "Other", "mix": "Full mix",
}

PREAMPS_EN = {
    "clean": "Clean (solid state)", "tube": "Tube (1950s style)",
    "transformer": "Transformer (Neve 1073 style)", "opto": "Opto (LA-2A style)",
}

TAPES_EN = {
    "off": "No tape", "tape15": "Tape 15 ips (warm)", "tape30": "Tape 30 ips (clean)",
    "cassette": "Cassette (lo-fi)", "vinyl": "Vinyl (warm, with crackle)",
}

AMBIENCE_EN = {"none": "None", "roomtone": "Room tone", "crowd": "Audience", "outdoor": "Street / wind"}

TECHNIQUES_EN = {
    "ab": "A-B (spaced omnis)", "xy": "X-Y (coincident cardioids, 90°)", "ortf": "ORTF (17 cm, 110°)",
    "nos": "NOS (30 cm, 90°)", "blumlein": "Blumlein (crossed figure-8s, 90°)",
}

STEM_METHODS_EN = {
    "hpss": "Built-in (fast, no models)", "demucs": "Demucs htdemucs_6s (neural, more accurate)",
    "none": "Do not split (one channel)",
}

ENGINES_EN = {
    "acestep": ("ACE-Step 1.5 (local, free)",
                "Open-source song model running on your machine via acestep-api. Vocals in 50+ languages."),
    "gptunnel": ("Suno and others via GPTunneL (cloud)",
                 "Cloud music models through the GPTunneL API. Needs an API key; paid per generation."),
    "demo": ("Demo synthesizer (offline, no AI)",
             "Procedural instrumental with separate tracks — to try the studio without models."),
}

PARAM_LABELS_EN = {
    "inference_steps": "Diffusion steps",
    "guidance_scale": "Guidance (base models only)",
    "thinking": "LM thinking (better structure, slower)",
    "audio_format": "Server audio format",
}

# Progress / status messages: Russian prefix → English prefix (the rest of the message is kept).
MESSAGES_EN = [
    ("Загрузка: ", "Loading: "), ("Канал: ", "Channel: "), ("Комнатные микрофоны: ", "Room mics: "),
    ("Хвост помещения", "Room tail"), ("Дилей", "Delay"), ("Эмбиент помещения", "Room ambience"),
    ("Мастер-шина", "Master bus"), ("Лента", "Tape"), ("Громкость и лимитер", "Loudness and limiter"),
    ("Запись файла", "Writing file"), ("Готово: ", "Done: "), ("Готово", "Done"),
    ("Демо: синтез варианта ", "Demo: synthesizing take "), ("Разделение", "Separating"),
    ("Отменено пользователем", "Cancelled by user"), ("Отменено", "Cancelled"),
    ("ACE-Step: отправка задачи", "ACE-Step: submitting task"), ("ACE-Step: генерация… ", "ACE-Step: generating… "),
    ("GPTunneL: создание задачи ", "GPTunneL: creating task "),
    ("Demucs: ", "Demucs: "), ("Встроенное разделение: центр / края", "Built-in separation: center / sides"),
    ("Встроенное разделение: HPSS, канал ", "Built-in separation: HPSS, channel "),
    ("Встроенное разделение: НЧ", "Built-in separation: lows"),
    ("сервер доступен: ", "server is up: "), ("сервер ответил: ", "server replied: "),
    ("нет соединения с ", "no connection to "), ("встроен, работает без сети", "built in, works offline"),
    ("нет ключа: задайте GPTUNNEL_API_KEY или введите ключ в настройках",
     "no key: set GPTUNNEL_API_KEY or enter the key in Settings"),
    ("ключ принят, но музыкальных моделей в каталоге нет", "key accepted, but the catalog has no music models"),
    ("доступно моделей: ", "models available: "),
    ("Нет активных каналов: добавьте трек или снимите Mute/Solo",
     "No active channels: add a track or clear Mute/Solo"),
    ("Пустой фрагмент: начало превью дальше конца трека", "Empty range: preview start is past the end of the track"),
]

# Fragments inside messages (applied after the prefix table).
FRAGMENTS_EN = [
    (" трек(а)", " track(s)"), ("Запустите acestep-api", "Start acestep-api"),
    ("разделение (может занять несколько минут)", "separating (may take several minutes)"),
    ("ACE-Step: генерация… ", "ACE-Step: generating… "), (" (по умолчанию)", " (default)"),
]

_TABLES = {
    "scene": SCENES_EN, "mic": MICS_EN, "pattern": PATTERNS_EN, "instrument": INSTRUMENTS_EN,
    "preamp": PREAMPS_EN, "tape": TAPES_EN, "ambience": AMBIENCE_EN, "technique": TECHNIQUES_EN,
    "stem_method": STEM_METHODS_EN, "engine": ENGINES_EN, "param": PARAM_LABELS_EN,
}


def localized(kind: str, item_id: str, field: str, ru_value: str, lang: str = "en") -> str:
    """field: "name" | "description". Russian (or unknown) → ru_value as is."""
    if lang != "en":
        return ru_value
    entry = _TABLES.get(kind, {}).get(item_id)
    if entry is None:
        return ru_value
    if isinstance(entry, tuple):
        return entry[0] if field == "name" else (entry[1] if len(entry) > 1 else ru_value)
    return entry if field == "name" else ru_value


def message(msg: str, lang: str = "en") -> str:
    """Translates engine progress messages by prefix; unknown messages pass through."""
    if lang != "en" or not msg:
        return msg
    for ru, en in MESSAGES_EN:
        if msg.startswith(ru):
            msg = en + msg[len(ru):]
            break
    for ru, en in FRAGMENTS_EN:
        msg = msg.replace(ru, en)
    return re.sub(r"(\d+(?:\.\d+)?) с(?=\W|$)", r"\1 s", msg)
