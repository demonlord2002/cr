# config.py
# Simple config loader for the bot using environment variables.

from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))            # Telegram API ID (int)
API_HASH = os.getenv("API_HASH", "")              # Telegram API Hash
BOT_TOKEN = os.getenv("BOT_TOKEN", "")            # Bot token (from BotFather)
MONGO_URL = os.getenv("MONGO_URL", "")            # MongoDB connection string (mongodb+srv://... or mongodb://...)
YTDLP_PATH = os.getenv("YTDLP_PATH", "yt-dlp")    # Path to yt-dlp binary (or yt-dlp executable name)
CRUNCHYROLL_USER = os.getenv("CR_USER", "")       # Optional Crunchyroll username
CRUNCHYROLL_PASS = os.getenv("CR_PASS", "")       # Optional Crunchyroll password
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")  # Where downloads are stored
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(2_000_000_000)))  # a safety cap (bytes)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
