#!/usr/bin/env python3
# bot.py — Crunchyroll downloader (DRM-aware placeholder)
# Requirements: pyrogram, tgcrypto, pymongo, yt-dlp
# pip install pyrogram tgcrypto pymongo yt-dlp

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

import config  # your config.py with BOT_TOKEN, API_ID, API_HASH, MONGO_URI, CRUNCHYROLL_USER, CRUNCHYROLL_PASS

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

ytdlp_cmd = [
    "yt-dlp",
    "--cookies", "cookies.txt",
    "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    link
]

# ---------- MongoDB ----------
db = None
try:
    db = MongoClient(config.MONGO_URI).crunchy_bot
    log.info("Connected to MongoDB")
except Exception as e:
    log.warning("MongoDB not configured or connection failed: %s", e)
    db = None

# ---------- In-memory job store ----------
# key: chat_id -> { url: str, info: dict (optional) }
JOBS: dict[int, dict] = {}

# ---------- Helpers ----------
async def run_subprocess(cmd: list[str], check: bool = False, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    """
    Run a blocking subprocess in a thread so event loop doesn't block.
    Returns subprocess.CompletedProcess
    """
    def _run():
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    try:
        return await asyncio.to_thread(_run)
    except subprocess.CalledProcessError as err:
        return err  # returned object has .stderr and .stdout

def detect_drm(stderr_text: str) -> bool:
    if not stderr_text:
        return False
    s = stderr_text.lower()
    # common indicators
    checks = ["drm", "widevine", "encrypted", "cannot download (?:due to|because)", "this video is drm protected"]
    # simple check
    if "drm" in s or "widevine" in s or "encrypted" in s or "this video is drm protected" in s:
        return True
    return False

# ---------- DRM placeholder  ----------
def decrypt_drm_video(url: str, lang: str, output_path: str) -> None:
    """
    Placeholder for DRM decryption logic.
    If you have a legal Widevine decryption backend, implement the call here
    (e.g. spawn an external service or call via subprocess/http).
    Must produce a playable MP4 at output_path.
    """
    # Example idea (not implemented):
    # subprocess.run(["python3", "my_drm_decryptor.py", "--url", url, "--lang", lang, "--out", output_path], check=True)
    raise NotImplementedError("DRM decryption backend not implemented. Plug your legal backend here.")

# ---------- Progress helpers ----------
_last_upload_edit: dict[int, float] = {}

async def upload_progress(current: int, total: int, message):
    try:
        # Throttle edits to once per 2 seconds per chat to avoid API flood
        now = asyncio.get_event_loop().time()
        last = _last_upload_edit.get(message.chat.id, 0)
        if now - last < 2 and current < total:
            return
        _last_upload_edit[message.chat.id] = now
        percent = int(current * 100 / total) if total else 0
        await message.edit_text(f"📤 Uploading... {percent}% ({current//1024} KiB / {total//1024} KiB)")
    except Exception:
        pass

# ---------- Commands & Handlers ----------
@app.on_message(filters.command("start") & filters.private)
async def cmd_start(client, message):
    await message.reply_text(
        "👋 Send me a Crunchyroll link (or use /download <link>).\n"
        "⚠️ This bot does NOT bypass DRM. If DRM is detected I will call a placeholder that you must implement."
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

async def process_link_request(client, chat_id: int, url: str, reply_message):
    log.info("New link from %s: %s", chat_id, url)
    JOBS[chat_id] = {"url": url}
    m = await reply_message.reply_text("🔍 Inspecting link with yt-dlp (fetching available subtitles/audio)...")

    # Build yt-dlp JSON command
    cmd = [
        "yt-dlp",
        "--username", getattr(config, "CRUNCHYROLL_USER", ""),
        "--password", getattr(config, "CRUNCHYROLL_PASS", ""),
        "-J", url
    ]

    proc = await run_subprocess(cmd, check=False)
    # proc may be CompletedProcess or CalledProcessError
    stdout = getattr(proc, "stdout", "") or ""
    stderr = getattr(proc, "stderr", "") or ""

    # If yt-dlp returned non-zero and stderr indicates DRM, notify user
    if proc.returncode != 0:
        if detect_drm(stderr):
            await m.edit_text("🔐 This video appears to be DRM-protected. If you have a legal DRM backend, the bot can call it (placeholder).")
            # store metadata and exit (user can still press button later if you implement backend)
            JOBS[chat_id]["info"] = {"drm": True, "raw_err": stderr}
            return
        else:
            await m.edit_text(f"❌ Failed to inspect link. yt-dlp error:\n```\n{stderr[:1000]}\n```")
            JOBS.pop(chat_id, None)
            return

    # parse JSON
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
    all_subs = list(dict.fromkeys(list(subs.keys()) + list(auto_subs.keys())))  # preserve order

    if not all_subs:
        # If no subtitles listed, still provide a "No subs (best audio)" option
        all_subs = ["none"]

    # make buttons (limit to 10)
    buttons = []
    for lang in all_subs[:10]:
        buttons.append([InlineKeyboardButton(text=str(lang), callback_data=f"cr_lang:{lang}")])
    buttons.append([InlineKeyboardButton("Download without subs", callback_data="cr_lang:none")])

    await m.edit_text(
        f"Title: {title}\nSelect subtitle/audio language (or choose 'Download without subs'):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex(r"^cr_lang:(.+)"))
async def callback_pick_lang(client, callback):
    chat_id = callback.message.chat.id
    user = callback.from_user
    lang = callback.data.split(":", 1)[1]

    if chat_id not in JOBS:
        await callback.answer("No active job found. Send the link again.", show_alert=True)
        return

    url = JOBS[chat_id]["url"]
    info = JOBS[chat_id].get("info", {})
    title = info.get("title", "video")
    await callback.message.edit_text(f"⬇️ Preparing download: {title}\nLanguage: {lang}")

    # Create temp dir and run yt-dlp in a thread
    with tempfile.TemporaryDirectory() as tmpdir:
        # choose output template — yt-dlp will replace extension
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:120] or "video"
        out_template = os.path.join(tmpdir, f"{safe_title}.%(ext)s")
        final_output_mp4 = os.path.join(tmpdir, f"{safe_title}.mp4")

        # Build yt-dlp command (fast options)
        yt_cmd = [
            "yt-dlp",
            "--username", getattr(config, "CRUNCHYROLL_USER", ""),
            "--password", getattr(config, "CRUNCHYROLL_PASS", ""),
            "-f", "bv*+ba/best",
            "--no-part",
            "--retries", "5",
            "--fragment-retries", "5",
            "--concurrent-fragments", "16",
            "--limit-rate", "15M",                 # cap at 15 MB/s (your requested cap)
            "--downloader-args", "ffmpeg:-threads 8",
            url,
            "-o", out_template
        ]
        # add subtitle args if requested
        if lang and lang != "none" and lang != "und":
            yt_cmd[ :0]  # no-op to keep style
            yt_cmd.extend(["--sub-lang", lang, "--embed-subs", "--write-subs", "--write-auto-sub"])

        # Run yt-dlp in background thread
        await callback.message.edit_text("⬇️ Starting yt-dlp (this may take a moment)...")
        proc = await run_subprocess(yt_cmd, check=False)

        stderr = getattr(proc, "stderr", "") or ""
        stdout = getattr(proc, "stdout", "") or ""
        returncode = getattr(proc, "returncode", 1)

        # If yt-dlp failed and looks like DRM -> try DRM placeholder
        if returncode != 0:
            if detect_drm(stderr):
                await callback.message.edit_text("🔐 DRM detected. Attempting DRM backend (placeholder)...")
                try:
                    # Call your DRM decryption. It should create final_output_mp4
                    decrypt_drm_video(url, lang, final_output_mp4)
                except NotImplementedError:
                    await callback.message.edit_text("❌ DRM backend not implemented. Please implement decrypt_drm_video().")
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
            # Find the file produced by yt-dlp (it might be .mp4 or .mkv or other ext)
            produced_files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
            # choose largest file (likely the merged video)
            if not produced_files:
                await callback.message.edit_text("❌ yt-dlp finished but no file was produced.")
                JOBS.pop(chat_id, None)
                return
            produced_files.sort(key=lambda p: os.path.getsize(p), reverse=True)
            produced = produced_files[0]
            # If not mp4, try to remux to mp4 with ffmpeg for compatibility
            if not produced.lower().endswith(".mp4"):
                # use ffmpeg to remux (fast copy)
                remux_cmd = [
                    "ffmpeg", "-y", "-i", produced,
                    "-c", "copy",
                    final_output_mp4
                ]
                remux_proc = await run_subprocess(remux_cmd, check=False)
                if remux_proc.returncode != 0:
                    # remux failed — fallback to uploading produced file
                    final_path = produced
                else:
                    final_path = final_output_mp4
            else:
                final_path = produced

        # Final file ready — upload it
        try:
            upload_msg = await callback.message.reply_text("📤 Uploading to Telegram (this may take a while)...")
            await client.send_document(
                chat_id,
                final_path,
                caption=f"{title} — downloaded with yt-dlp",
                progress=upload_progress,
                progress_args=(upload_msg,)
            )
            # Log to MongoDB if available
            if db:
                try:
                    db.downloads.insert_one({
                        "user_id": chat_id,
                        "title": title,
                        "url": url,
                        "lang": lang,
                        "timestamp": int(asyncio.get_event_loop().time())
                    })
                except Exception:
                    log.exception("Failed to write DB log")
            await upload_msg.edit_text("✅ Upload complete.")
        except Exception as e:
            await callback.message.edit_text(f"❌ Upload failed: {e}")
        finally:
            JOBS.pop(chat_id, None)  # cleanup

# ---------- Run ----------
if __name__ == "__main__":
    log.info("Starting bot...")
    app.run()
