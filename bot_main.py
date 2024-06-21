import asyncio
import logging
import os
import subprocess
import sys
import uuid
import instaloader
import yt_dlp

from datetime import datetime
from aiogram import Bot, Dispatcher, html, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

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

# Function to download video from Instagram
def download_instagram_video(url):
    L = instaloader.Instaloader(dirname_pattern=TMP_DIR)
    post = instaloader.Post.from_shortcode(L.context, url.split("/")[-2])
    video_url = post.video_url

    video_path = os.path.join(TMP_DIR, f"{post.owner_username}_{post.shortcode}.mp4")
    L.download_post(post, target=TMP_DIR)

    for file in os.listdir(TMP_DIR):
        if file.endswith(".mp4"):
            return os.path.join(TMP_DIR, file)

    raise ValueError("Failed to download Instagram video")

# Function to download video from a URL
async def download_video(url):
    if "instagram.com" in url:
        return download_instagram_video(url)
    else:
        ydl_opts = {"format": "best", "outtmpl": os.path.join(TMP_DIR, "%(title)s.%(ext)s")}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get("duration", 0)
            if duration > 120:  # Check if video duration exceeds 2 minutes
                raise ValueError("Video duration exceeds 2 minutes.")
            filename = ydl.prepare_filename(info)
            
            # file_size = info.get('filesize')
            # if file_size is not None and int(file_size) > 30 * 1024 * 1024:  # Convert MB to bytes
            #     raise ValueError("File size exceeds 30 MB.")
            # filename = ydl.prepare_filename(info)

            ydl.download([url])  # Download the video
        return filename

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
@dp.message(F.text & F.text.startswith("http"))
async def download_and_send_video(message: Message):
    try:
        # Check if message is a URL using a separate function
        if is_valid_url(message.text):
            url = message.text
            # Check if the URL is from a blocked site
            if is_blocked_site(url):
                await message.answer(
                    "Sorry, downloading from this site is not supported."
                )
                return
            filename = await download_video(url)
            renamed_filename = rename_file(filename)

            mp4_filename = convert_to_mp4(renamed_filename)

            await message.reply_video(video=types.FSInputFile(mp4_filename))

            # Remove the original file
            if mp4_filename != renamed_filename:
                os.remove(renamed_filename)
            os.remove(mp4_filename)
        else:
            await message.answer(
                "Please send a video link starting with http or https."
            )
    except ValueError as ve:
        logging.error(f"Error downloading or sending video: {ve}")
        await message.answer(f"Video cannot be downloaded: {ve}")
    except Exception as e:
        logging.error(f"Error downloading or sending video: {e}")
    #     await message.answer(
    #         "An error occurred while downloading or sending the video. Please try again or send a different link."
    #     )

async def main() -> None:
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
