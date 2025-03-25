#!/usr/bin/env python3

import asyncio
import logging
import random
import os
import subprocess
import sys
import uuid
import yt_dlp
import re
from collections import defaultdict
from datetime import datetime
from aiogram import Bot, Dispatcher, html, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

# ---------------------------
# CONFIGURATION
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("link2video.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Constants
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(SCRIPT_DIR, "tmp")
os.makedirs(TMP_DIR, exist_ok=True)

# Load API token
with open("api.txt", "r") as f:
    API_TOKEN = f.read().strip()

# Load blocked sites
def load_blocked_sites(filename="blocked_sites.txt"):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

BLOCKED_SITES = load_blocked_sites()

# Initialize bot
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Task queue and worker system
task_queues = defaultdict(list)
worker_lock = asyncio.Lock()

# ---------------------------
# DOWNLOAD UTILITIES
# ---------------------------
def sync_download_media(url, media_type="video"):
    """Synchronous download function to run in threads"""
    random_filename = f"{media_type}_{random.randint(100000, 999999)}"
    ydl_opts = {
        'outtmpl': f'{TMP_DIR}/{random_filename}',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'netrc': True,
        'verbose': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'cookiefile': 'cookies.txt',   
    }

    if media_type == "video":
        ydl_opts.update({
            'format': 'bv*[height<=1080]+ba/b[height<=1080]/bv*[width<=1080]+ba/b[width<=1080]',
            'merge_output_format': 'mp4',

        })
    else:  # audio
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            'audioformat': 'mp3',
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if media_type == "video" and info.get('duration', 0) > 360:
                raise ValueError("Video duration exceeds 3 minutes")
            ydl.download([url])
        return os.path.join(TMP_DIR, random_filename + (".mp4" if media_type == "video" else ".mp3"))
    except Exception as e:
        raise ValueError(f"Download failed: {str(e)}")

async def download_media(url, media_type="video"):
    """Async wrapper for media download"""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, sync_download_media, url, media_type)
    except Exception as e:
        raise ValueError(str(e))

async def safe_remove_file(path):
    """Safely remove file in background"""
    try:
        if os.path.exists(path):
            await asyncio.to_thread(os.remove, path)
    except Exception as e:
        logging.error(f"Error removing file {path}: {e}")

# ---------------------------
# TASK WORKER SYSTEM
# ---------------------------
async def process_task(user_id: int, message: Message, url: str, is_audio: bool = False):
    """Process single download task"""
    print (f'USER ID: {user_id}, Message: {message} URL: {url}, IS AUDIO: {is_audio}')
    try:
        media_type = "audio" if is_audio else "video"
        filename = await download_media(url, media_type)
        if is_audio:
            logging.info(f"Downloading audio from {url}")
            await message.answer("⏳ Downloading Audio...")
            await message.reply_audio(
                audio=types.FSInputFile(filename),
                caption="🎵 Your audio",
            )
        else:
            logging.info(f"Downloading video from {url}")
            await message.answer("⏳ Downloading Viedo...")
            await message.reply_video(
                video=types.FSInputFile(filename),
                caption="🎬 Your video",
            )

            await safe_remove_file(filename)
    except Exception as e:
        await bot.send_message(user_id, f"❌ Error: {str(e)}")
        logging.error(f"Task failed for {user_id}: {str(e)}")

async def task_worker():
    """Process tasks from queues"""
    while True:
        async with worker_lock:
            for user_id in list(task_queues.keys()):
                if task_queues[user_id]:
                    url, is_audio, message = task_queues[user_id].pop(0)
                    asyncio.create_task(process_task(user_id, message, url, is_audio))
        await asyncio.sleep(0.5)  # Prevent CPU overload

# ---------------------------
# MESSAGE HANDLERS
# ---------------------------

def is_blocked(url):
    """Check if URL is blocked"""
    return any(blocked in url for blocked in BLOCKED_SITES)

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        f"Hello, {html.bold(message.from_user.full_name)}!\n"
        "Send me a link to download video/audio.\n"
        "Add '-a' to download audio only."
    )

@dp.message(F.text)
async def message_handler(message: Message):
    url_match = re.search(r'https?://[^\s]+', message.text)                                                         
    if not url_match:                                                                                               
        await message.answer("Please include the URL in the message.")                                                
        return                                                                                                      
    url = url_match.group(0)
    
    if is_blocked(url):
        return await message.answer("❌ Downloads from this site are blocked")
    
    is_audio = "-a" in message.text.lower()
    task_queues[message.from_user.id].append((url, is_audio, message))
    await message.answer("✅ Task added to queue. Processing...")

# ---------------------------
# MAIN APPLICATION
# ---------------------------
async def on_startup():
    # Start background worker
    asyncio.create_task(task_worker())
    logging.info("Bot started with task worker")

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")