# !/usr/bin/env python3

import asyncio
import logging
import random
import os
import requests
import subprocess
import sys
import uuid
import yt_dlp
import re
import base64
from instagrapi import Client
from collections import defaultdict
from datetime import datetime
from aiogram import Bot, Dispatcher, html, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile, InputMediaPhoto, InputMediaVideo

# Playwright imports (optional, only if needed)
try:
    from playwright.async_api import async_playwright
    from playwright_stealth.stealth import Stealth
    PLAYWRIGHT_AVAILABLE = True
    logging.info("Playwright successfully loaded")
except ImportError as e:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning(f"Playwright not available: {e}. Instagram stealth fallback disabled.")


# ---------------------------
# LOGGING CONFIGURATION
# ---------------------------
logdir = os.getenv("LOGDIR", "./logs")
log_file = os.path.join(logdir, "Link2video.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, mode="a", encoding="utf-8"),
        # logging.StreamHandler(),
    ],
)

# Constants
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(SCRIPT_DIR, "tmp")
os.makedirs(TMP_DIR, exist_ok=True)

# Load API token
with open("api.txt", "r") as f:
    API_TOKEN = f.read().strip()

IG_SESSION_PATH = os.path.join(SCRIPT_DIR, "ig_session.json")

# Load blocked sites
def load_blocked_sites(filename="blocked_sites.txt"):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

# Load allowed sites
def load_allowed_sites(filename="allowed_sites.txt"):
    try:
        with open(filename, "r") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

BLOCKED_SITES = load_blocked_sites()
ALLOWED_SITES = load_allowed_sites()

# Initialize bot
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Task queue and worker system
task_queues = defaultdict(list)
worker_lock = asyncio.Lock()


def get_ig_client():
    """Initialize Instagram client with session support"""
    cl = Client()    
    # if os.path.exists(IG_SESSION_PATH):
    #     cl.load_settings(IG_SESSION_PATH)
    # return cl

    if os.path.exists(IG_SESSION_PATH):
        try:
            cl.load_settings(IG_SESSION_PATH)
            cl.get_timeline_feed()  # Check if session is still alive
            logging.info("Instagram session loaded successfully")
        except Exception:
            logging.warning("Session expired, need to re-login via auth_insta.py")
    else:
        logging.warning("No ig_session.json found!")
    return cl

# ---------------------------
# DOWNLOAD UTILITIES
# ---------------------------
def sync_download_media(url, media_type="video"):
    """Диспетчер: распределяет задачи между API и yt-dlp"""
    
    url_lower = url.lower()
    
    # 1. Instagram (через instagrapi)
    if "instagram.com" in url_lower:
        return sync_download_instagram_all_types(url, media_type)

    # 2. TikTok (via new API)
    if "tiktok.com" in url_lower:
        return sync_download_tiktok_all_types(url)

    # 3. Все остальное (YouTube, Pinterest и т.д. через yt-dlp)
    random_filename = f"{media_type}_{random.randint(100000, 999999)}"
    ydl_opts = {
        'outtmpl': f'{TMP_DIR}/{random_filename}.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'cookiefile': 'cookies.txt',
        'format': 'bv*[height<=720][vcodec^=avc1]+ba/b[height<=720][vcodec^=avc1]/best',
        'merge_output_format': 'mp4',
        'postprocessor_args': ['-c', 'copy', '-movflags', '+faststart'],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
        return os.path.join(TMP_DIR, random_filename + ".mp4")

def sync_download_instagram_all_types(url, media_type="video"):
    """Universal and fastest Instagram downloader"""
    try:
        cl = get_ig_client()
        # media_pk_from_url works instantly
        media_pk = cl.media_pk_from_url(url)
        
        # Using v1 - faster and more reliable for validation errors
        media_info = cl.media_info_v1(media_pk)
        
        random_id = random.randint(100000, 999999)

        # Type 1: Single photo
        if media_info.media_type == 1:
            # Download directly by URL from info (fastest method)
            path = cl.photo_download(media_pk, folder=TMP_DIR)
            new_path = os.path.join(TMP_DIR, f"ig_{random_id}.jpg")
            if os.path.exists(path):
                os.rename(path, new_path)
            return new_path

        # Type 8: Album (Carousel)
        elif media_info.media_type == 8:
            # Download all carousel elements
            logging.info(f"Downloading carousel album from {url}")
            paths = cl.album_download(media_pk, folder=TMP_DIR)
            
            if not paths:
                raise ValueError("No files downloaded from carousel")
            
            # Rename files for convenience and return list
            renamed_paths = []
            for i, path in enumerate(paths):
                if os.path.exists(path):
                    ext = os.path.splitext(path)[1] or '.jpg'
                    new_path = os.path.join(TMP_DIR, f"ig_carousel_{random_id}_{i+1}{ext}")
                    os.rename(path, new_path)
                    renamed_paths.append(new_path)
            
            # Return list of files instead of single file
            return renamed_paths if renamed_paths else paths[0]  # fallback to first file if renaming failed

        # Type 2: Video / Reels
        elif media_info.media_type == 2:
            path = cl.video_download(media_pk, folder=TMP_DIR)
            new_path = os.path.join(TMP_DIR, f"ig_{random_id}.mp4")
            if os.path.exists(path):
                os.rename(path, new_path)
            return new_path

    except Exception as e:
        logging.error(f"Instagrapi error: {e}")
        # If API failed, try the good old yt-dlp as a fallback
        return fallback_download_yt_dlp(url, media_type)

def fallback_download_yt_dlp(url, media_type):
    """Fallback method if Instagram API is acting up"""
    random_filename = f"fallback_{random.randint(100000, 999999)}"
    ydl_opts = {
        'outtmpl': f'{TMP_DIR}/{random_filename}.%(ext)s',
        'quiet': True,
        'cookiefile': 'cookies.txt',
        'format': 'best', 
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
        # Searching for any downloaded file with known extensions, which yt-dlp might have used
        for ext in ['mp4', 'jpg', 'webp']:
            path = os.path.join(TMP_DIR, f"{random_filename}.{ext}")
            if os.path.exists(path):
                return path
    raise ValueError("All download methods failed")


def sync_download_tiktok_all_types(url):
    """Download carousels with audio from TikTok via TikWM API (audio only for carousels)"""
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        response = requests.get(api_url).json()
        
        if response.get("code") != 0:
            raise ValueError(f"TikTok API error: {response.get('msg')}")
            
        data = response.get("data")
        random_id = random.randint(100000, 999999)
        result_data = {"images": [], "audio": None, "video": None}
        
        # Check if it's carousel or video first
        is_carousel = "images" in data and data["images"]
        
        # Download audio only for carousels
        if is_carousel:
            music_url = data.get("music")
            if music_url:
                audio_path = os.path.join(TMP_DIR, f"tt_audio_{random_id}.mp3")
                with open(audio_path, "wb") as f:
                    f.write(requests.get(music_url).content)
                result_data["audio"] = audio_path

        # Download carousel images or single video
        if is_carousel:
            # Carousel: download all images
            for i, img_url in enumerate(data["images"]):
                path = os.path.join(TMP_DIR, f"tt_carousel_{random_id}_{i+1}.jpg")
                with open(path, "wb") as f:
                    f.write(requests.get(img_url).content)
                result_data["images"].append(path)
        else:
            # Single video: download only video (no audio)
            video_url = data.get("play")
            path = os.path.join(TMP_DIR, f"tt_video_{random_id}.mp4")
            with open(path, "wb") as f:
                f.write(requests.get(video_url).content)
            result_data["video"] = path
            
        return result_data

    except Exception as e:
        logging.error(f"TikTok API error: {e}")
        raise e
    
def parse_netscape_cookies(cookies_file_path):
    """Parse Netscape cookies file format for Playwright"""
    cookies = []
    try:
        with open(cookies_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        domain = parts[0]
                        domain_initial_dot = parts[1].lower() == 'true'
                        path = parts[2]
                        secure = parts[3].lower() == 'true'
                        expires = parts[4]
                        name = parts[5]
                        value = parts[6]
                        
                        cookie = {
                            'name': name,
                            'value': value,
                            'domain': domain.lstrip('.'),
                            'path': path,
                            'secure': secure
                        }
                        
                        # Add expiry if it's not a session cookie
                        if expires and expires != '0':
                            try:
                                cookie['expires'] = int(expires)
                            except ValueError:
                                pass
                        
                        cookies.append(cookie)
        logging.info(f"Parsed {len(cookies)} cookies from {cookies_file_path}")
        return cookies
    except Exception as e:
        logging.warning(f"Failed to parse cookies: {e}")
        return []

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
async def process_task(
        user_id: int, message: Message, url: str, 
        is_audio: bool = False, default_processing: Message = None):
    """Process single download task"""
    try:
        if default_processing:
            await default_processing.delete()
        process_msg = await message.answer(
            "⏳ Downloading Audio..." if is_audio else "⏳ Downloading Media..."
        )
        
        media_type = "audio" if is_audio else "video"
        filename = await download_media(url, media_type)

        # Check if it's a TikTok result dict (with images, audio, video)
        if isinstance(filename, dict):
            # If there's video - send video
            if filename.get("video"):
                await message.reply_video(video=types.FSInputFile(filename["video"]))
                await safe_remove_file(filename["video"])
            
            # If there are images - send album
            if filename.get("images"):
                media_group = [types.InputMediaPhoto(media=types.FSInputFile(p)) for p in filename["images"][:10]]
                await message.reply_media_group(media=media_group)
                for p in filename["images"]:
                    await safe_remove_file(p)
            
            # If there's audio - send audio file
            if filename.get("audio"):
                await message.reply_audio(audio=types.FSInputFile(filename["audio"]), caption="🎵 Music from post")
                await safe_remove_file(filename["audio"])
        
        # Check if it's a list (carousel from Instagram) or single file
        elif isinstance(filename, list):
            # Processing carousel - sending all files
            logging.info(f"Sending carousel with {len(filename)} items from {url}")
            media_group = []
            
            for i, file_path in enumerate(filename):
                file_ext = os.path.splitext(file_path)[1].lower()
                
                if file_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    media_group.append(types.InputMediaPhoto(
                        media=types.FSInputFile(file_path),
                    ))
                elif file_ext in ['.mp4', '.mov', '.avi']:
                    media_group.append(types.InputMediaVideo(
                        media=types.FSInputFile(file_path),
                    ))
            
            if media_group:
                # Send media as group (up to 10 items at once)
                for i in range(0, len(media_group), 10):
                    batch = media_group[i:i+10]
                    await message.reply_media_group(media=batch)
            
            # Delete all carousel files
            for file_path in filename:
                await safe_remove_file(file_path)
                
        else:
            # Process single file (as before)
            file_ext = os.path.splitext(filename)[1].lower()
            
            if is_audio or file_ext in ['.mp3', '.wav', '.m4a']:
                logging.info(f"Downloading audio from {url}")
                await message.reply_audio(
                    audio=types.FSInputFile(filename),
                    )
            elif file_ext in ['.jpg', '.jpeg', '.png', '.webp']:
                logging.info(f"Downloading image from {url}")
                await message.reply_photo(
                    photo=types.FSInputFile(filename),
                    )
            else:
                logging.info(f"Downloading video from {url}")
                await message.reply_video(
                    video=types.FSInputFile(filename),
                    )
                    
            await safe_remove_file(filename)
                
        await process_msg.delete()
    except Exception as e:
        if message.chat.type == "private":
            await bot.send_message(user_id, f"❌ Error: {str(e)}")
        else:
            await bot.send_message(message.chat.id, f"❌ Error when processing your request. Please try again or contact support.")
        
        logging.error(f"Task failed for {user_id}: {str(e)}")

async def task_worker():
    """Process tasks from queues"""
    while True:
        async with worker_lock:
            for user_id in list(task_queues.keys()):
                if task_queues[user_id]:
                    url, is_audio, message, default_processing = task_queues[user_id].pop(0)
                    asyncio.create_task(process_task(user_id, message, url, is_audio, default_processing))
        await asyncio.sleep(0.5)  # Prevent CPU overload

# ---------------------------
# MESSAGE HANDLERS
# ---------------------------

def is_blocked(url):
    """Check if URL is blocked"""
    return any(blocked in url for blocked in BLOCKED_SITES)

def is_allowed(url):
    """Check if URL is from allowed site"""
    return any(allowed in url for allowed in ALLOWED_SITES)

def has_url(text):
    """Check if text contains URL"""
    return bool(re.search(r'https?://[^\s]+', text))

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        f"Hello, {html.bold(message.from_user.full_name)}!\n"
        "Send me a link to download video/audio.\n"
        "Add ' -a' to download audio only.\n\n"
        "🌐 Supported sites:\n"
        "• YouTube\n"
        "• Instagram\n"
        "• TikTok\n"
        "• Facebook\n"
        "• Twitter/X\n"
        "• Twitch\n"
        "• SoundCloud\n"
    )

# Handler for messages with URLs
@dp.message(F.text)
async def message_handler(message: Message):
    url_match = re.search(r'https?://[^\s]+', message.text)
    
    # If message is from a group chat and does not contain URL, ignore it
    if message.chat.type != "private" and not url_match:
        return
    
    # If message is from a group chat and contains URL, process it
    if not url_match:
        await message.answer("Please include the URL in the message.")
        return
    
    url = url_match.group(0)
    
    # Check if site is allowed - if not, simply ignore
    if not is_allowed(url):
        return
    
    # Additional check for blocked sites (if needed)
    if is_blocked(url):
        return
    
    is_audio = " -a" in message.text.lower()
    default_processing = await message.answer("✅ Task added to queue. Processing...")
    task_queues[message.from_user.id].append((url, is_audio, message, default_processing))

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
