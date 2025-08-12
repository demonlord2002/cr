import os
import re
import subprocess
import shutil
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import config  # your config.py with BOT_TOKEN, OWNER_ID, COOKIES_FILE, DOWNLOAD_DIR


# Ensure download directory exists
os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)

# Check cookies file presence at startup, raise error if missing
if not os.path.exists(config.COOKIES_FILE):
    raise FileNotFoundError(f"[ERROR] Please place your cookies.txt file in {config.COOKIES_FILE}")


def clean_filename(name: str) -> str:
    # Remove characters not allowed in filenames for Windows/Linux/Mac
    return re.sub(r'[\\/*?:"<>|]', "", name)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.OWNER_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    await update.message.reply_text(
        "✅ Send `/download <crunchyroll_link>` to download video with all audio languages (MKV format).",
        parse_mode="Markdown"
    )


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.OWNER_ID:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")

    if not context.args:
        return await update.message.reply_text("❌ Usage: `/download <crunchyroll_link>`", parse_mode="Markdown")

    url = context.args[0]
    msg = await update.message.reply_text("⏳ Downloading video with all audio tracks...")

    try:
        temp_dir = os.path.join(config.DOWNLOAD_DIR, "temp_dl")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)

        output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")

        cmd = [
            "yt-dlp",
            "--cookies", config.COOKIES_FILE,
            "-o", output_template,
            "--no-warnings",
            "--merge-output-format", "mkv",
            "--all-audio",
            "-f", "bestvideo+bestaudio/best",
            url
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            await msg.edit_text(f"❌ yt-dlp failed:\n```\n{proc.stderr[:1000]}\n```")
            shutil.rmtree(temp_dir)
            return

        # Find downloaded mkv file
        downloaded_files = [f for f in os.listdir(temp_dir) if f.endswith(".mkv")]
        if not downloaded_files:
            await msg.edit_text("❌ No MKV video file found after download.")
            shutil.rmtree(temp_dir)
            return

        downloaded_file_path = os.path.join(temp_dir, downloaded_files[0])
        final_output_name = clean_filename(downloaded_files[0])
        final_output_path = os.path.join(config.DOWNLOAD_DIR, final_output_name)

        shutil.move(downloaded_file_path, final_output_path)

        # Send the video as document
        with open(final_output_path, "rb") as video_file:
            await update.message.reply_document(
                document=video_file,
                filename=final_output_name,
                caption=f"{final_output_name} (all audio tracks)"
            )

        await msg.edit_text("✅ Download and upload completed!")

        # Cleanup temp files
        os.remove(final_output_path)
        shutil.rmtree(temp_dir)

    except Exception as e:
        await msg.edit_text(f"⚠ Unexpected error: {e}")


def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download))
    app.run_polling()


if __name__ == "__main__":
    main()
