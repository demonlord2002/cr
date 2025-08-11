# config.py
# Loads environment variables for the Crunchyroll downloader bot.

import os
from dotenv import load_dotenv

load_dotenv()

# === Telegram API ===
API_ID = int(os.getenv("API_ID", "23559126"))  # Your Telegram API ID (integer)
API_HASH = os.getenv("API_HASH", "58347a441c011b1b9ee3367ea936dcc4")    # Your Telegram API Hash
BOT_TOKEN = os.getenv("BOT_TOKEN", "8289940670:AAGQ8Z49PV6wZ_sfY5JWl192wPWPWyeBDCk")  # Your bot token from BotFather

# === MongoDB ===
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://drdoom2003p:drdoom2003p@cluster0.fnhjrtn.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")  # MongoDB connection URI

# === Crunchyroll Credentials (optional) ===
CRUNCHYROLL_USER = os.getenv("CRUNCHYROLL_USER", "jg_717@hotmail.com")
CRUNCHYROLL_PASS = os.getenv("CRUNCHYROLL_PASS", "J7173659207g.")

# === yt-dlp settings ===
YTDLP_PATH = os.getenv("YTDLP_PATH", "yt-dlp")  # yt-dlp binary name/path
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")  # Where downloads will be saved

# === Upload/Download settings ===
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(2_000_000_000)))  # 2 GB safety cap (bytes)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
