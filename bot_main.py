# !/usr/bin/env python3

import asyncio
import logging
import random
import os
import subprocess
import sys
import uuid
import yt_dlp
import re
import instaloader
import base64
from collections import defaultdict
from datetime import datetime
from aiogram import Bot, Dispatcher, html, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

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

# ---------------------------
# DOWNLOAD UTILITIES
# ---------------------------
def sync_download_media(url, media_type="video"):
    """Synchronous download function to run in threads"""
    random_filename = f"{media_type}_{random.randint(100000, 999999)}"
    ydl_opts = {
        'outtmpl': f'{TMP_DIR}/{random_filename}.%(ext)s',
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
            'extract_audio': True,
            'audio_format': 'mp3',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
            
        })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            duration = 360
            info = ydl.extract_info(url, download=False)
            if media_type == "video" and info.get('duration', 0) > duration:
                raise ValueError(f"Video duration exceeds {duration/60} minutes")
            ydl.download([url])
        return os.path.join(TMP_DIR, random_filename + (".mp4" if media_type == "video" else ".mp3"))
    except Exception as e:
        # If it's Instagram and video-related error, try to extract image
        if "instagram" in url.lower() and any(error_text in str(e) for error_text in [
            "There is no video in this post",
            "No video formats found",
            "Unable to download webpage",
            "Private account",
            "Post not found",
            "rate-limit reached",
            "login required",
            "Requested content is not available"
        ]):
            return sync_download_instagram_image(url)
        raise ValueError(f"Download failed: {str(e)}")

def sync_download_instagram_image(url):
    """Download first image from Instagram post when no video is available"""
    try:
        logging.info(f"Attempting to download Instagram image using instaloader: {url}")
        
        # Extract post ID from URL
        post_id_match = re.search(r'/p/([^/]+)', url)
        if not post_id_match:
            post_id_match = re.search(r'/reel/([^/]+)', url)
        
        if not post_id_match:
            raise ValueError("Cannot extract post ID from URL")
            
        post_id = post_id_match.group(1)
        
        # Configure instaloader to download only images to our tmp directory
        L = instaloader.Instaloader(
            dirname_pattern=TMP_DIR,
            filename_pattern=f"image_{random.randint(100000, 999999)}",
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            quiet=True
        )
        
        # Download the post
        post = instaloader.Post.from_shortcode(L.context, post_id)
        L.download_post(post, target="")
        
        # Find the downloaded image file
        for file in os.listdir(TMP_DIR):
            if file.startswith(f"image_{post_id}") and file.endswith(('.jpg', '.jpeg', '.png')):
                return os.path.join(TMP_DIR, file)
        
        # If no file found with post_id, look for any recent image file
        image_files = [f for f in os.listdir(TMP_DIR) if f.startswith("image_") and f.endswith(('.jpg', '.jpeg', '.png'))]
        if image_files:
            # Return the most recently created image file
            image_files.sort(key=lambda x: os.path.getctime(os.path.join(TMP_DIR, x)), reverse=True)
            return os.path.join(TMP_DIR, image_files[0])
            
        raise ValueError("No image file was downloaded")
                
    except Exception as e:
        # If instaloader fails, try playwright stealth method
        logging.warning(f"Instaloader failed: {str(e)}")
        if PLAYWRIGHT_AVAILABLE:
            try:
                logging.info(f"Attempting Instagram download using Playwright Stealth: {url}")
                # Run async stealth function in the current event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(sync_download_instagram_stealth(url))
                finally:
                    loop.close()
            except Exception as stealth_error:
                logging.warning(f"Playwright stealth also failed: {stealth_error}")
        raise ValueError(f"Failed to extract Instagram image: {str(e)}")

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

async def sync_download_instagram_stealth(url):
    """Download Instagram image using Playwright stealth mode"""
    try:
        logging.info(f"Starting Playwright stealth download for: {url}")
        
        # Extract post ID from URL
        post_id_match = re.search(r'/p/([^/]+)', url)
        if not post_id_match:
            post_id_match = re.search(r'/reel/([^/]+)', url)
        
        if not post_id_match:
            raise ValueError("Cannot extract post ID from URL")
            
        post_id = post_id_match.group(1)
        logging.info(f"Extracted post ID: {post_id}")
        
        async with async_playwright() as p:
            # Launch browser with stealth settings
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--disable-extensions',
                    '--disable-gpu',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--disable-default-apps',
                    '--disable-features=TranslateUI',
                    '--disable-ipc-flooding-protection',
                ]
            )
            
            # Create context with user agent
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1'
            )
            
            page = await context.new_page()
            
            # Apply stealth settings
            stealth = Stealth()
            await stealth.apply_stealth_async(page)
            
            # Load cookies if available
            try:
                cookies_path = os.path.join(SCRIPT_DIR, 'cookies.txt')
                if os.path.exists(cookies_path):
                    logging.info("Loading cookies for Instagram access")
                    # Parse Netscape cookies format and add to context
                    cookies = parse_netscape_cookies(cookies_path)
                    if cookies:
                        await context.add_cookies(cookies)
            except Exception as cookie_error:
                logging.warning(f"Could not load cookies: {cookie_error}")
            
            # Navigate to Instagram post
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for images to load
            await page.wait_for_timeout(3000)
            
            # Find image elements
            image_selectors = [
                'img[style*="object-fit"]',
                'article img',
                '[role="button"] img',
                'img[src*="scontent"]'
            ]
            
            image_url = None
            for selector in image_selectors:
                try:
                    img_element = await page.query_selector(selector)
                    if img_element:
                        src = await img_element.get_attribute('src')
                        if src and 'scontent' in src:
                            image_url = src
                            break
                except:
                    continue
            
            if not image_url:
                raise ValueError("No image found on the page")
            
            # Download the image
            response = await page.goto(image_url)
            if response.status != 200:
                raise ValueError(f"Failed to download image: HTTP {response.status}")
            
            image_content = await response.body()
            
            # Save image to tmp directory
            random_filename = f"stealth_image_{random.randint(100000, 999999)}.jpg"
            filepath = os.path.join(TMP_DIR, random_filename)
            
            with open(filepath, 'wb') as f:
                f.write(image_content)
            
            await context.close()
            await browser.close()
            return filepath
            
    except Exception as e:
        raise ValueError(f"Playwright stealth download failed: {str(e)}")

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

        # Determine file type by extension
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
                
        await process_msg.delete()
        await safe_remove_file(filename)
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
