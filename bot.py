#!/usr/bin/env python3
# bot.py — Crunchyroll downloader (DRM-aware placeholder)
# Requirements: pyrogram, tgcrypto, pymongo, yt-dlp[impersonate]
# pip install pyrogram tgcrypto pymongo "yt-dlp[impersonate]"

import os
import json
import tempfile
import subprocess
import asyncio
import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

import config  # config.py with BOT_TOKEN, API_ID, API_HASH, MONGO_URI

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("crunchy_bot")

# ---------- Pyrogram client ----------
app = Client(
    "crunchy_dl_bot",
    bot_token=config.BOT_TOKEN,
    api_id=config.API_ID,
    api_hash=config.API_HASH,
)

# ---------- MongoDB ----------
try:
    db = MongoClient(config.MONGO_URI).crunchy_bot
    log.info("Connected to MongoDB")
except Exception as e:
    log.warning("MongoDB not configured or connection failed: %s", e)
    db = None

# ---------- In-memory job store ----------
JOBS: dict[int, dict] = {}

# ---------- Helpers ----------
async def run_subprocess(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    def _run():
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    try:
        return await asyncio.to_thread(_run)
    except subprocess.CalledProcessError as err:
        return err

def detect_drm(stderr_text: str) -> bool:
    if not stderr_text:
        return False
    s = stderr_text.lower()
    return any(k in s for k in ["drm", "widevine", "encrypted", "this video is drm protected"])

def decrypt_drm_video(url: str, lang: str, output_path: str) -> None:
    raise NotImplementedError("DRM backend not implemented.")

_last_upload_edit: dict[int, float] = {}

async def upload_progress(current: int, total: int, message):
    try:
        now = asyncio.get_event_loop().time()
        last = _last_upload_edit.get(message.chat.id, 0)
        if now - last < 2 and current < total:
            return
        _last_upload_edit[message.chat.id] = now
        percent = int(current * 100 / total) if total else 0
        await message.edit_text(f"📤 Uploading... {percent}% ({current//1024} KiB / {total//1024} KiB)")
    except Exception:
        pass

# ---------- Commands ----------
@app.on_message(filters.command("start") & filters.private)
async def cmd_start(_, message):
    await message.reply_text(
        "👋 Send me a Crunchyroll link (or use /download <link>).\n"
        "⚠️ DRM-protected videos require a legal DRM backend."
    )

@app.on_message(filters.command("download") & filters.private)
async def cmd_download(client, message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: /download <url>")
    url = message.command[1].strip()
    await process_link_request(client, message.chat.id, url, reply_message=message)

@app.on_message(filters.regex(r"https?://[^\s]+") & filters.private)
async def link_message(client, message):
    url = message.text.strip().split()[0]
    await process_link_request(client, message.chat.id, url, reply_message=message)

# ---------- Link Processing ----------
async def process_link_request(client, chat_id: int, url: str, reply_message):
    log.info("New link from %s: %s", chat_id, url)
    JOBS[chat_id] = {"url": url}
    m = await reply_message.reply_text("🔍 Inspecting link with yt-dlp...")

    cmd = [
        "yt-dlp",
        "--cookies", "cookies/cookies.txt",
        "--impersonate", "chrome110",
        "-J", url
    ]

    proc = await run_subprocess(cmd, check=False)
    stdout = getattr(proc, "stdout", "") or ""
    stderr = getattr(proc, "stderr", "") or ""

    if proc.returncode != 0:
        if detect_drm(stderr):
            await m.edit_text("🔐 DRM detected. Implement decrypt_drm_video() to handle it.")
            JOBS[chat_id]["info"] = {"drm": True}
            return
        else:
            await m.edit_text(f"❌ yt-dlp error:\n```\n{stderr[:1000]}\n```")
            JOBS.pop(chat_id, None)
            return

    try:
        info = json.loads(stdout)
    except Exception as e:
        await m.edit_text(f"❌ Failed to parse yt-dlp output: {e}")
        JOBS.pop(chat_id, None)
        return

    JOBS[chat_id]["info"] = info
    title = info.get("title", "video")
    subs = info.get("subtitles", {}) or {}
    auto_subs = info.get("automatic_captions", {}) or {}
    all_subs = list(dict.fromkeys(list(subs.keys()) + list(auto_subs.keys()))) or ["none"]

    buttons = [[InlineKeyboardButton(text=lang, callback_data=f"cr_lang:{lang}")]
               for lang in all_subs[:10]]
    buttons.append([InlineKeyboardButton("Download without subs", callback_data="cr_lang:none")])

    await m.edit_text(
        f"Title: {title}\nSelect subtitle/audio language:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ---------- Callback ----------
@app.on_callback_query(filters.regex(r"^cr_lang:(.+)"))
async def callback_pick_lang(client, callback):
    chat_id = callback.message.chat.id
    lang = callback.data.split(":", 1)[1]

    if chat_id not in JOBS:
        await callback.answer("No active job found.", show_alert=True)
        return

    url = JOBS[chat_id]["url"]
    info = JOBS[chat_id].get("info", {})
    title = info.get("title", "video")
    await callback.message.edit_text(f"⬇️ Preparing download: {title}\nLanguage: {lang}")

    with tempfile.TemporaryDirectory() as tmpdir:
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:120] or "video"
        out_template = os.path.join(tmpdir, f"{safe_title}.%(ext)s")
        final_output_mp4 = os.path.join(tmpdir, f"{safe_title}.mp4")

        yt_cmd = [
            "yt-dlp",
            "--cookies", "cookies/cookies.txt",
            "--impersonate", "chrome110",
            "-f", "bv*+ba/best",
            "--no-part",
            "--retries", "5",
            "--fragment-retries", "5",
            "--concurrent-fragments", "16",
            "--limit-rate", "15M",
            "--downloader-args", "ffmpeg:-threads 8",
            url,
            "-o", out_template
        ]
        if lang not in ("none", "und"):
            yt_cmd.extend(["--sub-lang", lang, "--embed-subs", "--write-subs", "--write-auto-sub"])

        await callback.message.edit_text("⬇️ Starting yt-dlp...")
        proc = await run_subprocess(yt_cmd, check=False)
        stderr = getattr(proc, "stderr", "") or ""
        returncode = getattr(proc, "returncode", 1)

        if returncode != 0:
            if detect_drm(stderr):
                await callback.message.edit_text("🔐 DRM detected. Attempting DRM backend...")
                try:
                    decrypt_drm_video(url, lang, final_output_mp4)
                except NotImplementedError:
                    await callback.message.edit_text("❌ DRM backend not implemented.")
                    JOBS.pop(chat_id, None)
                    return
                except Exception as e:
                    await callback.message.edit_text(f"❌ DRM backend failed: {e}")
                    JOBS.pop(chat_id, None)
                    return
            else:
                await callback.message.edit_text(f"❌ yt-dlp failed:\n```\n{stderr[:1000]}\n```")
                JOBS.pop(chat_id, None)
                return
        else:
            produced_files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
            if not produced_files:
                await callback.message.edit_text("❌ No file produced.")
                JOBS.pop(chat_id, None)
                return
            produced_files.sort(key=lambda p: os.path.getsize(p), reverse=True)
            produced = produced_files[0]
            if not produced.lower().endswith(".mp4"):
                remux_cmd = ["ffmpeg", "-y", "-i", produced, "-c", "copy", final_output_mp4]
                remux_proc = await run_subprocess(remux_cmd, check=False)
                final_path = final_output_mp4 if remux_proc.returncode == 0 else produced
            else:
                final_path = produced

        try:
            upload_msg = await callback.message.reply_text("📤 Uploading to Telegram...")
            await client.send_document(
                chat_id,
                final_path,
                caption=f"{title} — downloaded with yt-dlp",
                progress=upload_progress,
                progress_args=(upload_msg,)
            )
            if db:
                db.downloads.insert_one({
                    "user_id": chat_id,
                    "title": title,
                    "url": url,
                    "lang": lang,
                    "timestamp": int(asyncio.get_event_loop().time())
                })
            await upload_msg.edit_text("✅ Upload complete.")
        except Exception as e:
            await callback.message.edit_text(f"❌ Upload failed: {e}")
        finally:
            JOBS.pop(chat_id, None)

# ---------- Run ----------
if __name__ == "__main__":
    log.info("Starting bot...")
    app.run()
