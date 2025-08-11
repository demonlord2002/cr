# config.py
# Loads environment variables for the Crunchyroll downloader bo
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram bot token from BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "8289940670:AAGQ8Z49PV6wZ_sfY5JWl192wPWPWyeBDCk").strip()

# Your numeric Telegram user ID to restrict usage
OWNER_ID = int(os.getenv("OWNER_ID", "7813285237"))

# Cookies file path for Crunchyroll auth (place your cookies.txt here)
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies/cookies.txt")

# Directory to save temp downloads
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/downloads")

# Validate critical vars (optional)
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required in environment variables")

if OWNER_ID == 0:
    raise ValueError("OWNER_ID must be set to your Telegram numeric user ID")

if not os.path.exists(COOKIES_FILE):
    print(f"[WARNING] Cookies file {COOKIES_FILE} does not exist. Please add your Crunchyroll cookies.")
