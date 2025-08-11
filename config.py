# config.py
# Loads environment variables for the Crunchyroll downloader bot.

import os
from dotenv import load_dotenv

load_dotenv()

# === Telegram API ===
API_ID = int(os.getenv("API_ID", "0"))  # Your Telegram API ID (integer)
API_HASH = os.getenv("API_HASH", "")    # Your Telegram API Hash
BOT_TOKEN = os.getenv("BOT_TOKEN", "")  # Your bot token from BotFather

# === MongoDB ===
MONGO_URI = os.getenv("MONGO_URI", "")  # MongoDB connection URI

# === Crunchyroll Credentials (optional) ===
CRUNCHYROLL_USER = os.getenv("CRUNCHYROLL_USER", "")
CRUNCHYROLL_PASS = os.getenv("CRUNCHYROLL_PASS", "")

# === yt-dlp settings ===
YTDLP_PATH = os.getenv("YTDLP_PATH", "yt-dlp")  # yt-dlp binary name/path
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")  # Where downloads will be saved

# === Upload/Download settings ===
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(2_000_000_000)))  # 2 GB safety cap (bytes)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
