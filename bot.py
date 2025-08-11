import os
import re
import subprocess
import shutil
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
COOKIES_FILE = "cookies/cookies.txt"
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/downloads")

# Create necessary directories
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
if not os.path.exists(COOKIES_FILE):
    os.makedirs("cookies", exist_ok=True)
    print(f"[ERROR] Please place your cookies.txt file in {COOKIES_FILE}")
    exit()

def clean_filename(name: str) -> str:
    # Remove special chars from filename to avoid OS issues
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
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)

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
        
        # Run yt-dlp as subprocess, capture output and errors
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            await msg.edit_text(f"❌ yt-dlp failed:\n```\n{proc.stderr[:1000]}\n```")
            shutil.rmtree(temp_dir)
            return

        # Look for the downloaded file (mkv preferred)
        downloaded_files = [f for f in os.listdir(temp_dir) if f.endswith(".mkv") or f.endswith(".mp4")]
        if not downloaded_files:
            await msg.edit_text("❌ No video file found after download.")
            shutil.rmtree(temp_dir)
            return

        # Choose largest file (usually the correct video)
        downloaded_files.sort(key=lambda f: os.path.getsize(os.path.join(temp_dir, f)), reverse=True)
        downloaded_file_path = os.path.join(temp_dir, downloaded_files[0])

        final_output = os.path.join(DOWNLOAD_DIR, base_filename + ".mkv")
        if not downloaded_file_path.endswith(".mkv"):
            # Remux to MKV with ffmpeg
            remux_cmd = [
                "ffmpeg",
                "-y",  # overwrite output
                "-i", downloaded_file_path,
                "-c", "copy",
                final_output
            ]
            remux_proc = subprocess.run(remux_cmd, capture_output=True, text=True)
            if remux_proc.returncode != 0:
                await msg.edit_text(f"❌ ffmpeg remux failed:\n```\n{remux_proc.stderr[:1000]}\n```")
                shutil.rmtree(temp_dir)
                return
            os.remove(downloaded_file_path)
        else:
            os.rename(downloaded_file_path, final_output)

        await update.message.reply_document(document=open(final_output, "rb"), caption=f"{base_filename} (with all audio tracks)")
        await msg.edit_text("✅ Download and upload completed!")

        # Cleanup
        os.remove(final_output)
        shutil.rmtree(temp_dir)

    except Exception as e:
        await msg.edit_text(f"⚠ Unexpected error: {e}")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download))
    app.run_polling()

if __name__ == "__main__":
    main()
    
