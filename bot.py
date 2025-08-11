# bot.py
# Pyrogram-based Telegram bot that:
# - Accepts a URL
# - Shows available audio/subtitle options (as provided by yt-dlp)
# - Downloads the chosen format (using yt-dlp)
# - Uploads video as a Telegram document
#
# IMPORTANT: This bot does NOT bypass DRM. DRM-protected Crunchyroll content will fail to download.
# If you have pre-decrypted files, place them where DOWNLOAD_DIR points and use the /upload_local command.
#
# Dependencies:
# pip install pyrogram tgcrypto python-dotenv motor aiofiles

import os
import shutil
import asyncio
import json
import logging
import uuid
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from config import *
import subprocess

# ---------- Setup logging ----------
logging.basicConfig(level=LOG_LEVEL)
log = logging.getLogger(__name__)

# ---------- Ensure download dir ----------
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ---------- MongoDB ----------
mongo = AsyncIOMotorClient(MONGO_URL) if MONGO_URL else None
db = mongo.cr_bot if mongo else None
jobs_coll = db.jobs if db else None

# ---------- Pyrogram Client ----------
app = Client(
    "crunchy_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="."
)

# ---------- Helpers ----------
async def run_yt_dlp_json(url: str, extra_args=None):
    """
    Run yt-dlp -J (json) and return parsed JSON.
    This is used to list formats, subtitles, etc.
    """
    args = [YTDLP_PATH, "-J", url]
    if CRUNCHYROLL_USER and CRUNCHYROLL_PASS:
        args += ["-u", CRUNCHYROLL_USER, "-p", CRUNCHYROLL_PASS]
    if extra_args:
        args += extra_args
    log.info("Running yt-dlp JSON: %s", " ".join(args))
    proc = await asyncio.create_subprocess_exec(*args,
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.error("yt-dlp -J failed: %s", stderr.decode(errors="ignore"))
        raise RuntimeError("yt-dlp failed: " + stderr.decode(errors="ignore"))
    return json.loads(stdout.decode())

async def yt_dlp_download(url: str, output_path: str, format_selector: str=None, subs_lang: str=None):
    """
    Download using yt-dlp. Returns path to downloaded file.
    format_selector: a yt-dlp -f value or None (best)
    subs_lang: language code for subtitles to embed/download
    """
    args = [YTDLP_PATH, url, "-o", output_path]
    # login if present
    if CRUNCHYROLL_USER and CRUNCHYROLL_PASS:
        args += ["-u", CRUNCHYROLL_USER, "-p", CRUNCHYROLL_PASS]
    # embed subtitles if requested
    if subs_lang:
        args += ["--sub-lang", subs_lang, "--embed-subs", "--write-subs", "--write-auto-sub"]
    # choose format
    if format_selector:
        args += ["-f", format_selector]
    else:
        args += ["-f", "best"]
    # ensure ffmpeg usage for merges is allowed (yt-dlp uses ffmpeg if installed)
    log.info("Running yt-dlp download: %s", " ".join(args))
    proc = await asyncio.create_subprocess_exec(*args,
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        log.error("yt-dlp download failed: %s", err.decode(errors="ignore"))
        raise RuntimeError("yt-dlp download failed: " + err.decode(errors="ignore"))
    # yt-dlp writes files according to template; return matching files
    # We assume output_path contains %(title)s or unique id; to keep simple, return the first file in download dir newer than start time
    return True

def human_size(n):
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024.0:
            return f"{n:.2f}{unit}"
        n /= 1024.0
    return f"{n:.2f}PB"

async def create_job_record(url, user_id):
    if not jobs_coll:
        return None
    job = {
        "url": url,
        "user_id": user_id,
        "status": "queued",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    res = await jobs_coll.insert_one(job)
    job['_id'] = res.inserted_id
    return job

async def update_job(job_id, **fields):
    if not jobs_coll:
        return
    fields['updated_at'] = datetime.utcnow()
    await jobs_coll.update_one({"_id": job_id}, {"$set": fields})

# ---------- Commands ----------
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await message.reply_text(
        "👋 Send me a Crunchyroll (or any yt-dlp supported) URL with /download <link>\n\n"
        "⚠️ IMPORTANT: This bot does NOT bypass DRM. DRM-protected premium Crunchyroll episodes will NOT download.\n"
        "If you already have a decrypted file, use /upload_local to upload it.\n\n"
        "Examples:\n/download https://www.crunchyroll.com/some-episode\n/upload_local filename.mp4"
    )

@app.on_message(filters.command("download") & filters.private)
async def download_cmd(client, message):
    # Usage: /download <url>
    if len(message.command) < 2:
        return await message.reply_text("Usage: /download <url>")
    url = message.command[1].strip()
    m = await message.reply_text("🔎 Inspecting URL with yt-dlp...")
    job = await create_job_record(url, message.from_user.id)
    try:
        info = await run_yt_dlp_json(url)
    except Exception as e:
        await m.edit(f"❌ Failed to inspect the URL:\n{e}")
        if job: await update_job(job['_id'], status="failed", error=str(e))
        return

    title = info.get("title", "video")
    # Collect audio-only formats & subtitles (if available)
    formats = info.get("formats", [])
    audio_formats = []
    video_formats = []
    for f in formats:
        # f may contain 'vcodec', 'acodec', 'format_id', 'format', 'filesize', 'language'
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        fmt_id = f.get("format_id")
        filesize = f.get("filesize") or f.get("filesize_approx")
        # audio-only
        if vcodec == "none" and acodec and acodec != "none":
            audio_formats.append({
                "format_id": fmt_id,
                "format_note": f.get("format_note"),
                "ext": f.get("ext"),
                "filesize": filesize,
                "language": f.get("language") or f.get("lang") or None
            })
        # video (has video)
        if vcodec and vcodec != "none":
            video_formats.append({
                "format_id": fmt_id,
                "format_note": f.get("format_note"),
                "ext": f.get("ext"),
                "filesize": filesize,
                "resolution": f.get("height") or f.get("format_note")
            })
    # subtitles (captions)
    subs = info.get("subtitles", {}) or {}
    auto_subs = info.get("automatic_captions", {}) or {}

    # Build reply buttons: audio choices (if any) and subtitles
    buttons = []
    # audio buttons
    if audio_formats:
        btns = []
        # show top 4 audio formats
        shown = 0
        for a in audio_formats:
            txt = a["format_id"]
            if a.get("language"):
                txt += f" [{a['language']}]"
            if a.get("filesize"):
                txt += f" ({human_size(a['filesize'])})"
            btns.append(InlineKeyboardButton(txt, callback_data=json.dumps({
                "action": "pick_audio",
                "url": url,
                "title": title,
                "format_id": a["format_id"]
            })))
            shown += 1
            if shown >= 6:
                break
        buttons.append(btns)
    else:
        # fallback: pick best
        buttons.append([InlineKeyboardButton("Use best available", callback_data=json.dumps({
            "action": "pick_audio",
            "url": url,
            "title": title,
            "format_id": None
        }))])

    # subtitle buttons if available
    sub_buttons = []
    all_subs = set(list(subs.keys()) + list(auto_subs.keys()))
    if all_subs:
        for lang in list(all_subs)[:6]:
            sub_buttons.append(InlineKeyboardButton(f"Sub: {lang}", callback_data=json.dumps({
                "action": "pick_sub",
                "url": url,
                "title": title,
                "subtitle": lang
            })))
        # add a "no subs" button
        sub_buttons.append(InlineKeyboardButton("No subs", callback_data=json.dumps({
            "action": "pick_sub",
            "url": url,
            "title": title,
            "subtitle": ""
        })))
        buttons.append(sub_buttons)
    else:
        buttons.append([InlineKeyboardButton("No subtitles available", callback_data=json.dumps({
            "action": "pick_sub",
            "url": url,
            "title": title,
            "subtitle": ""
        }))])

    # Put a final "Start download" button to proceed with chosen defaults (best)
    buttons.append([InlineKeyboardButton("Start download (best/defaults)", callback_data=json.dumps({
        "action": "start_download",
        "url": url,
        "title": title
    }))])

    await m.edit(f"Title: {title}\nChoose audio/subtitle options:", reply_markup=InlineKeyboardMarkup(buttons))
    await update_job(job['_id'], status="inspected", metadata={"title": title})

# track user choices in memory (very small store)
CHOICES = {}

@app.on_callback_query()
async def cb_handler(client, cq):
    data = json.loads(cq.data)
    action = data.get("action")
    user = cq.from_user
    key = f"{user.id}"
    if action == "pick_audio":
        CHOICES[key] = CHOICES.get(key, {})
        CHOICES[key]['format_id'] = data.get("format_id")
        await cq.answer(f"Selected audio format: {data.get('format_id') or 'best'}", show_alert=False)
    elif action == "pick_sub":
        CHOICES[key] = CHOICES.get(key, {})
        CHOICES[key]['subtitle'] = data.get("subtitle")
        await cq.answer(f"Subtitle set: {data.get('subtitle') or 'None'}", show_alert=False)
    elif action == "start_download":
        url = data.get("url")
        title = data.get("title")
        choices = CHOICES.get(key, {})
        fmt = choices.get('format_id')
        sub = choices.get('subtitle')
        # create unique download target filename template
        uid = str(uuid.uuid4())[:8]
        safe_title = "".join(c for c in (title or "video") if c.isalnum() or c in " -_")[:120]
        output_template = os.path.join(DOWNLOAD_DIR, f"{safe_title}_{uid}.%(ext)s")
        msg = await cq.message.reply_text(f"⬇️ Starting download for **{title}**\nFormat: {fmt or 'best'}\nSubs: {sub or 'None'}", parse_mode="markdown")
        # set job record if available
        job = await create_job_record(url, user.id)
        await update_job(job['_id'], status="downloading", metadata={"format": fmt, "subtitle": sub, "title": title})
        try:
            # DOWNLOAD (this will fail on DRM-protected streams)
            await yt_dlp_download(url, output_template, format_selector=fmt, subs_lang=sub if sub else None)
        except Exception as e:
            await msg.edit(f"❌ Download failed:\n{e}")
            await update_job(job['_id'], status="failed", error=str(e))
            return
        # Find the downloaded file: choose newest file in DOWNLOAD_DIR matching uid
        files = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR) if uid in f]
        if not files:
            await msg.edit("❌ Download finished but file not found.")
            await update_job(job['_id'], status="failed", error="file not found")
            return
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        filepath = files[0]
        fsize = os.path.getsize(filepath)
        if fsize > MAX_UPLOAD_SIZE:
            await msg.edit(f"⚠️ File is too large to upload to Telegram ({human_size(fsize)}). Max allowed: {human_size(MAX_UPLOAD_SIZE)}")
            await update_job(job['_id'], status="failed", error="file too large")
            return
        await msg.edit(f"⬆️ Uploading {os.path.basename(filepath)} ({human_size(fsize)}) to Telegram...")
        try:
            await client.send_document(chat_id=user.id, document=filepath, caption=f"{title} — downloaded with yt-dlp")
            await msg.edit("✅ Uploaded successfully. Cleaning up...")
            await update_job(job['_id'], status="completed", file=filepath)
        except Exception as e:
            await msg.edit(f"❌ Upload failed: {e}")
            await update_job(job['_id'], status="failed", error=str(e))
            return
        finally:
            # remove the downloaded file
            try:
                os.remove(filepath)
            except:
                pass

@app.on_message(filters.command("upload_local") & filters.private)
async def upload_local(client, message):
    # usage: /upload_local filename.ext  (file placed in DOWNLOAD_DIR)
    if len(message.command) < 2:
        return await message.reply_text("Usage: /upload_local <filename>")
    filename = message.command[1]
    path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(path):
        return await message.reply_text("File not found in download directory.")
    fsize = os.path.getsize(path)
    if fsize > MAX_UPLOAD_SIZE:
        return await message.reply_text(f"File too big to upload: {human_size(fsize)}")
    await message.reply_text("Uploading...")
    await client.send_document(message.from_user.id, path)
    await message.reply_text("Done.")

@app.on_message(filters.command("status") & filters.private)
async def status_cmd(client, message):
    if not jobs_coll:
        return await message.reply_text("Jobs DB not configured.")
    rows = []
    cur = jobs_coll.find({"user_id": message.from_user.id}).sort("created_at", -1).limit(10)
    async for r in cur:
        rows.append(f"{r.get('_id')}: {r.get('status')} — {r.get('metadata', {}).get('title','')}")
    if not rows:
        return await message.reply_text("No recent jobs.")
    await message.reply_text("\n".join(rows))

# ---------- Placeholder: DRM Decryption Hook ----------
# If you legally own a way to decrypt Widevine content (for example, you have rights and a licensed decryption service),
# implement a function that takes the url or downloaded segments and outputs a single MP4 file path.
# DO NOT implement or request instructions on how to extract Widevine keys or crack DRM.
async def apply_drm_decryption_if_available(segments_dir_or_url):
    """
    Placeholder: returns path to decrypted file if available.
    Implementing DRM bypass is disallowed. Only use this if you have a legal decryption
    process you run on your own infrastructure.
    """
    return None

# ---------- Run ----------
if __name__ == "__main__":
    app.run()
