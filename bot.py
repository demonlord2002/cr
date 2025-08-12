import os
import re
import asyncio
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
)
import yt_dlp
import motor.motor_asyncio
import config  # your config.py
import json

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
MAX_TELEGRAM_FILESIZE = 2 * 1024 * 1024 * 1024  # 2GB limit for Telegram
CRUNCHYROLL_URL_REGEX = re.compile(r"https?://(www\.)?crunchyroll\.com/watch/\S+")

# MongoDB setup
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGODB_URI)
db = mongo_client['crunchyroll_bot']
files_collection = db['downloaded_files']

# --- Helper Functions ---

async def run_ffprobe(file_path: str):
    proc = await asyncio.create_subprocess_exec(
        'ffprobe', '-v', 'error', '-show_entries', 'stream=index,codec_type:stream_tags=language,title',
        '-of', 'json', file_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return json.loads(stdout.decode()) if stdout else None

async def extract_audio_track(input_file: str, stream_index: int, output_file: str):
    cmd = [
        'ffmpeg', '-y', '-i', input_file,
        '-map', f'0:{stream_index}', '-c', 'copy',
        output_file
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"ffmpeg error: {stderr.decode()}")
        return False
    return True

def get_audio_stream_info(ffprobe_json):
    streams = ffprobe_json.get('streams', [])
    audio_streams = []
    for s in streams:
        if s.get('codec_type') == 'audio':
            idx = s.get('index')
            tags = s.get('tags', {})
            lang = tags.get('language', 'und')
            title = tags.get('title', 'Unknown')
            label = f"{lang} - {title}" if title != 'Unknown' else lang
            audio_streams.append({
                'index': idx,
                'label': label
            })
    return audio_streams

def ytdlp_download_options():
    return {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'merge_output_format': 'mkv',
        'quiet': True,
        'no_warnings': True,
        'cookiefile': config.COOKIES_FILE,
        'external_downloader_args': ['-loglevel', 'panic'],
    }

async def save_file_metadata(user_id, message_id, filename, file_path):
    doc = {
        "user_id": user_id,
        "message_id": message_id,
        "filename": filename,
        "file_path": file_path,
        "downloaded_at": datetime.utcnow()
    }
    await files_collection.insert_one(doc)

async def get_file_by_path(file_path):
    return await files_collection.find_one({"file_path": file_path})

async def delete_file_metadata(file_path):
    await files_collection.delete_one({"file_path": file_path})

# --- Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me a Crunchyroll watch link, and I'll download and upload the video for you with audio track options."
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not CRUNCHYROLL_URL_REGEX.match(text):
        await update.message.reply_text("Please send a valid Crunchyroll watch link.")
        return

    msg = await update.message.reply_text("Starting download, please wait...")

    os.makedirs("downloads", exist_ok=True)

    ydl_opts = ytdlp_download_options()
    ydl_opts['outtmpl'] = 'downloads/%(title)s.%(ext)s'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(text, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mkv'):
                filename = os.path.splitext(filename)[0] + ".mkv"

        filesize = os.path.getsize(filename)
        if filesize > MAX_TELEGRAM_FILESIZE:
            await msg.edit_text("Downloaded file is too large for Telegram upload (over 2GB).")
            return

        await msg.edit_text(f"Downloaded successfully: {os.path.basename(filename)}\nAnalyzing audio tracks...")

        # Save metadata in MongoDB
        await save_file_metadata(update.message.from_user.id, update.message.message_id, os.path.basename(filename), filename)

        ffprobe_json = await run_ffprobe(filename)
        audio_streams = get_audio_stream_info(ffprobe_json)

        if not audio_streams:
            await update.message.reply_document(document=open(filename, 'rb'), filename=os.path.basename(filename))
            await msg.delete()
            os.remove(filename)
            await delete_file_metadata(filename)
            return

        buttons = []
        for stream in audio_streams:
            buttons.append([
                InlineKeyboardButton(
                    text=f"Audio: {stream['label']}",
                    callback_data=f"audio_{stream['index']}|{filename}"
                )
            ])
        buttons.append([InlineKeyboardButton(text="Upload Full Video", callback_data=f"fullvideo|{filename}")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await msg.edit_text(
            "Select an audio track to download as a separate audio file, or upload full video:",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        await msg.edit_text(f"Error downloading video: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("audio_") or data.startswith("fullvideo"):
        action, filename = data.split("|", 1)
        filename = filename.strip()

        # Validate file metadata from DB
        file_doc = await get_file_by_path(filename)
        if not file_doc or not os.path.exists(filename):
            await query.edit_message_text("File no longer exists or was removed.")
            return

        if action == "fullvideo":
            await query.edit_message_text("Uploading full video file, please wait...")
            try:
                with open(filename, "rb") as f:
                    await query.message.reply_document(document=f, filename=os.path.basename(filename))
                await query.edit_message_text("Full video uploaded.")
            except Exception as e:
                await query.edit_message_text(f"Failed to upload full video: {e}")

        else:
            try:
                stream_index = int(action.split("_")[1])
            except:
                await query.edit_message_text("Invalid audio stream index.")
                return

            await query.edit_message_text("Extracting audio track, please wait...")

            out_audio = f"{os.path.splitext(filename)[0]}_audio_{stream_index}.mka"

            if not os.path.exists(out_audio):
                success = await extract_audio_track(filename, stream_index, out_audio)
                if not success:
                    await query.edit_message_text("Failed to extract audio track.")
                    return

            try:
                with open(out_audio, "rb") as f:
                    await query.message.reply_document(document=f, filename=os.path.basename(out_audio))
                await query.edit_message_text("Audio track uploaded.")
            except Exception as e:
                await query.edit_message_text(f"Failed to upload audio track: {e}")

# --- Main ---

async def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot is running...")
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
