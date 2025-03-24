#!/usr/bin/env python3

import asyncio
import logging
import random
import os
import subprocess
import sys
import uuid
import instaloader
import yt_dlp
import re

from datetime import datetime
from aiogram import Bot, Dispatcher, html, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

# ---------------------------
# LOGGING CONFIGURATION
# ---------------------------
logdir = os.getenv("LOGDIR", "./logs")
os.makedirs(logdir, exist_ok=True)
log_file_path = os.path.join(logdir, "LINK2VIDEO.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Function to load blocked sites from file
def load_blocked_sites(filename):
    with open(filename, "r") as f:
        blocked_sites = [line.strip() for line in f]
    return blocked_sites

# Initialize blocked sites list
BLOCKED_SITES_FILE = "blocked_sites.txt"
BLOCKED_SITES = load_blocked_sites(BLOCKED_SITES_FILE)

# Get the directory of the Python script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(SCRIPT_DIR, "tmp")

# Create /tmp/ directory if it does not exist
if not os.path.exists(TMP_DIR):
    os.makedirs(TMP_DIR)

# Read API token from 'api.txt' file
with open("api.txt", "r") as f:
    API_TOKEN = f.read().strip()

# Initialize bot and dispatcher
dp = Dispatcher()
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Function to download video from a URL
async def download_video(url):
    random_filename = f"yt-dlp_{random.randint(100000, 999999)}.mp4"

    ydl_opts = {
        'outtmpl': f'{TMP_DIR}/{random_filename}',
        'format': 'bv*[height<=1080]+ba/b[height<=1080]/bv*[width<=1080]+ba/b[width<=1080]',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'netrc': True,
        'verbose': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'cookiefile': 'cookies.txt',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0)
        if duration > 360:  # Check if video duration exceeds 3 minutes
            raise ValueError("Video duration exceeds 3 minutes.")
        ydl.download([url])  # Download the video
        filename = os.path.join(TMP_DIR, random_filename)
    return filename

async def download_audio(url):
    random_filename = f"audio_{random.randint(100000, 999999)}"
    ydl_opts = {
        'outtmpl': f'{TMP_DIR}/{random_filename}',
        'format': 'bestaudio/best',
        'extract_audio': True,
        'audio_format': 'mp3',
        # 'postprocessors': [{
        #     'key': 'FFmpegExtractAudio',
        #     'preferredcodec': 'mp3',
        #     'preferredquality': '320',
        # }],
        'noplaylist': True,
        'netrc': True,
        'verbose': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'cookiefile': 'cookies.txt',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return os.path.join(TMP_DIR, random_filename)

# Function to check if a message is a valid URL
def is_valid_url(message_text):
    return message_text.startswith("http")

# Function to rename the file
def rename_file(filename):
    now = datetime.now().strftime("%Y-%m-%d-%H-%M")
    randname = uuid.uuid4().hex[:8]  # Take only the first 8 characters of the random name
    new_filename = f"{now}_{randname}"
    file_ext = os.path.splitext(filename)[-1]  # Get file extension
    new_filename_with_ext = os.path.join(TMP_DIR, f"{new_filename}{file_ext}")
    os.rename(filename, new_filename_with_ext)
    return new_filename_with_ext

# Function to check if URL is from blocked site
def is_blocked_site(url):
    for blocked_site in BLOCKED_SITES:
        if blocked_site in url:
            return True
    return False

# Function to convert video to MP4 using ffmpeg
def convert_to_mp4(filename):
    mp4_filename = os.path.splitext(filename)[0] + ".mp4"
    if os.path.splitext(filename)[-1] == ".mp4":
        return filename  # No need to convert if already in MP4 format
    else:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                filename,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "320k",
                "-movflags",
                "faststart",
                mp4_filename,
            ]
        )
        return mp4_filename

# Handler for '/start' command
@dp.message(CommandStart())
async def command_start_handler(message: Message) :
    await message.answer(
        f"Hello, {html.bold(message.from_user.full_name)}! "
        "Send me a link to the video you want to download."
    )

# Handler for text messages
@dp.message(F.text)                                                                                 
async def download_and_send_video(message: Message):                                                                    
    try:                                                                                                                
        url_match = re.search(r'https?://[^\s]+', message.text)                                                         
        if not url_match:                                                                                               
            await message.answer("Please include the URL in the message.")                                                
            return                                                                                                      
        url = url_match.group(0)

        # Check if the URL is from a blocked site                                                                   
        if is_blocked_site(url):                                                                                    
            await message.answer(                                                                                   
                "Sorry, downloading from this site is not supported."                                               
            )                                                                                                       
            return
        download_audio_check = "-a" in message.text.lower() 
        if download_audio_check:
                logging.info(f"Downloading audio from {url}")                                                                                                
                await message.answer("Downloading the audio...")
                filename = await download_audio(url)
                print(filename)
                await message.reply_audio(audio=types.FSInputFile(filename))
                logging.info(f"Removing file {filename}")
                os.remove(filename)                                                            
        else:
            logging.info(f"Downloading video from {url}")                                                                                                
            await message.answer("Downloading the video...") 
            filename = await download_video(url)                                                                        
            renamed_filename = rename_file(filename)                                                                    
            mp4_filename = convert_to_mp4(renamed_filename)
            await message.reply_video(video=types.FSInputFile(mp4_filename))                                                                                                                                      
            logging.info(f"Removing file {renamed_filename}")                                                                        
            os.remove(renamed_filename)
            logging                                                                             
            os.remove(mp4_filename)                                                                                                         
    except ValueError as ve:                                                                                            
        logging.error(f"Error downloading or sending video: {ve}")                                                      
        await message.answer(f"Video cannot be downloaded: {ve}")                                                       
    except Exception as e:                                                                                              
        logging.error(f"Error downloading or sending video: {e}")                                                       
                                                                                                                        
async def main() -> None:                                                                                               
    await dp.start_polling(bot)                                                                                         
                                                                                                                        
if __name__ == "__main__":                                                                                              
    asyncio.run(main())    
