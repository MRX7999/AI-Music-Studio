"""Publishing on export: distributor package, Telegram, YouTube; persistent queue with retries.

Nothing is posted without an explicit confirmation from the user interface: every upload
call requires `confirmed=True`, and public visibility on YouTube needs `confirm_public=True`.
"""
SERVICES = {
    "package": "Distributor package (WAV 24-bit, 3000 px cover, metadata, AI credits)",
    "telegram": "Telegram channel or chat (Bot API sendAudio)",
    "youtube": "YouTube (video from cover + waveform, AI disclosure)",
}
