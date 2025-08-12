import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8289940670:AAGQ8Z49PV6wZ_sfY5JWl192wPWPWyeBDCk")
OWNER_ID = int(os.getenv("OWNER_ID", "7813285237"))

# Optional placeholders if you want to add later
API_ID = os.getenv("API_ID", "23559126")
API_HASH = os.getenv("API_HASH", "58347a441c011b1b9ee3367ea936dcc4")

COOKIES_FILE = "cookies/cookies.txt"
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/downloads")
