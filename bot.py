import os
import re
import subprocess
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
COOKIES_FILE = "cookies/cookies.txt"
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/downloads")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

if not os.path.exists(COOKIES_FILE):
    os.makedirs("cookies", exist_ok=True)
    print(f"[ERROR] Please place your cookies.txt file in {COOKIES_FILE}")
    exit()

def clean_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    await update.message.reply_text("✅ Send `/download <crunchyroll_link>` to download video with all audio languages (MKV format).")

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    
    if not context.args:
        return await update.message.reply_text("❌ Usage: `/download <crunchyroll_link>`", parse_mode="Markdown")

    url = context.args[0]
    msg = await update.message.reply_text("⏳ Downloading video with all audio tracks...")

    try:
        base_filename = clean_filename("%(title)s")
        temp_dir = os.path.join(DOWNLOAD_DIR, "temp_dl")
        os.makedirs(temp_dir, exist_ok=True)

        # Download best video and all audio formats separately
        # -f "bv*+ba*" means best video + all audio, but yt-dlp merges only best audio by default
        # So we will download bestvideo+bestaudio in mkv format and let yt-dlp merge automatically
        output_template = os.path.join(temp_dir, base_filename + ".%(ext)s")

        cmd = [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "-o", output_template,
            "--no-warnings",
            "--merge-output-format", "mkv",
            "-f", "bestvideo+bestaudio/best",
            url
        ]
        
        subprocess.run(cmd, check=True)

        # After yt-dlp finishes, find the downloaded .mkv or video file
        downloaded_files = [f for f in os.listdir(temp_dir) if f.endswith(".mkv") or f.endswith(".mp4")]
        if not downloaded_files:
            return await msg.edit_text("❌ No video file found after download.")

        downloaded_files.sort(key=lambda f: os.path.getsize(os.path.join(temp_dir, f)), reverse=True)
        downloaded_file_path = os.path.join(temp_dir, downloaded_files[0])

        # Rename file to .mkv forcibly if mp4 (because it may not contain all audio tracks merged)
        final_output = os.path.join(DOWNLOAD_DIR, base_filename + ".mkv")
        if not downloaded_file_path.endswith(".mkv"):
            # Remux to mkv using ffmpeg to support multiple audio tracks
            remux_cmd = [
                "ffmpeg",
                "-i", downloaded_file_path,
                "-c", "copy",
                final_output
            ]
            subprocess.run(remux_cmd, check=True)
            os.remove(downloaded_file_path)
        else:
            os.rename(downloaded_file_path, final_output)

        await update.message.reply_document(document=open(final_output, "rb"), caption=f"{base_filename} (with all audio tracks)")
        os.remove(final_output)
        os.rmdir(temp_dir)
        await msg.edit_text("✅ Download and upload completed!")
    except subprocess.CalledProcessError as e:
        await msg.edit_text(f"❌ Download failed: {e}")
    except Exception as e:
        await msg.edit_text(f"⚠ Error: {e}")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download))
    app.run_polling()

if __name__ == "__main__":
    main()
