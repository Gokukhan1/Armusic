import os
import re
import json
import yt_dlp
import random
import logging
import aiohttp
import asyncio
from typing import Union
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch, Playlist
from AviaxMusic.utils.database import is_on_off
from AviaxMusic.utils.formatters import time_to_seconds

from config import API_URL, VIDEO_API_URL, API_KEY, API2_URL

def extract_video_id(link: str):
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", link)
    return match.group(1) if match else None


async def run_ytdlp_download(link, ydl_opts):
    loop = asyncio.get_running_loop()

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            return ydl.prepare_filename(info)

    return await loop.run_in_executor(None, _download)


async def download_song_api2(video_id: str):
    file_path = os.path.join("downloads", f"{video_id}.mp3")
    if os.path.exists(file_path):
        return file_path

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{API2_URL}/download",
                params={"url": video_id, "type": "audio"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                token = data.get("download_token")
                if not token:
                    return None

            stream_url = f"{API2_URL}/stream/{video_id}?type=audio&token={token}"
            async with session.get(stream_url) as audio_resp:
                if audio_resp.status == 302:
                    redirect = audio_resp.headers.get("Location")
                    if not redirect:
                        return None
                    async with session.get(redirect) as final_resp:
                        if final_resp.status != 200:
                            return None
                        with open(file_path, "wb") as f:
                            async for chunk in final_resp.content.iter_chunked(16384):
                                f.write(chunk)
                elif audio_resp.status == 200:
                    with open(file_path, "wb") as f:
                        async for chunk in audio_resp.content.iter_chunked(16384):
                            f.write(chunk)
                else:
                    return None
            return file_path
        except Exception:
            return None

async def download_song(link: str):
    video_id = link.split('v=')[-1].split('&')[0]
    download_folder = "downloads"
    for ext in ["mp3", "m4a", "webm"]:
        file_path = f"{download_folder}/{video_id}.{ext}"
        if os.path.exists(file_path):
            return file_path
        
    # Try API 1
    song_url = f"{API_URL}/song/{video_id}?api={API_KEY}"
    async with aiohttp.ClientSession() as session:
        for attempt in range(10):
            try:
                async with session.get(song_url) as response:
                    if response.status != 200:
                        break
                
                    data = await response.json()
                    status = data.get("status", "").lower()

                    if status == "done":
                        download_url = data.get("link")
                        if not download_url:
                            break
                        
                        file_format = data.get("format", "mp3")
                        file_extension = file_format.lower()
                        file_name = f"{video_id}.{file_extension}"
                        os.makedirs(download_folder, exist_ok=True)
                        file_path = os.path.join(download_folder, file_name)

                        async with session.get(download_url) as file_response:
                            with open(file_path, 'wb') as f:
                                while True:
                                    chunk = await file_response.content.read(8192)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                            return file_path
                    elif status == "downloading":
                        await asyncio.sleep(4)
                    else:
                        break
            except Exception:
                break
    
    # Fallback to API 2
    return await download_song_api2(video_id)

async def download_video(link: str):
    video_id = link.split('v=')[-1].split('&')[0]

    download_folder = "downloads"
    for ext in ["mp4", "webm", "mkv"]:
        file_path = f"{download_folder}/{video_id}.{ext}"
        if os.path.exists(file_path):
            return file_path
        
    video_url = f"{VIDEO_API_URL}/video/{video_id}?api={API_KEY}"
    async with aiohttp.ClientSession() as session:
        for attempt in range(10):
            try:
                async with session.get(video_url) as response:
                    if response.status != 200:
                        raise Exception(f"API request failed with status code {response.status}")
                
                    data = await response.json()
                    status = data.get("status", "").lower()

                    if status == "done":
                        download_url = data.get("link")
                        if not download_url:
                            raise Exception("API response did not provide a download URL.")
                        break
                    elif status == "downloading":
                        await asyncio.sleep(8)
                    else:
                        error_msg = data.get("error") or data.get("message") or f"Unexpected status '{status}'"
                        raise Exception(f"API error: {error_msg}")
            except Exception as e:
                # print(f"[FAIL] {e}")
                return None
        else:
            print("⏱️ Max retries reached. Still downloading...")
            return None
    

        try:
            file_format = data.get("format", "mp4")
            file_extension = file_format.lower()
            file_name = f"{video_id}.{file_extension}"
            download_folder = "downloads"
            os.makedirs(download_folder, exist_ok=True)
            file_path = os.path.join(download_folder, file_name)

            async with session.get(download_url) as file_response:
                with open(file_path, 'wb') as f:
                    while True:
                        chunk = await file_response.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                return file_path
        except aiohttp.ClientError as e:
            print(f"Network or client error occurred while downloading: {e}")
            return None
        except Exception as e:
            print(f"Error occurred while downloading video: {e}")
            return None
    return None

async def check_file_size(link):
    async def get_format_info(link):
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-J",
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f'Error:\n{stderr.decode()}')
            return None
        return json.loads(stdout.decode())

    def parse_size(formats):
        total_size = 0
        for format in formats:
            if 'filesize' in format:
                total_size += format['filesize']
        return total_size

    info = await get_format_info(link)
    if info is None:
        return None
    
    formats = info.get('formats', [])
    if not formats:
        print("No formats found.")
        return None
    
    total_size = parse_size(formats)
    return total_size

async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        umm = text[offset : offset + length]
        if "?si=" in umm:
            umm = umm.split("?si=")[0]
        return umm

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            search_results = await results.next()
            if not search_results or not isinstance(search_results, dict) or "result" not in search_results or not search_results["result"]:
                return "Unknown", "00:00", 0, config.YOUTUBE_IMG_URL, "None"
            
            result = search_results["result"][0]
            title = result.get("title") or "Unknown"
            duration_min = result.get("duration") or "00:00"
            thumbnails = result.get("thumbnails", [])
            thumbnail = thumbnails[0].get("url").split("?")[0] if thumbnails and isinstance(thumbnails, list) and thumbnails[0].get("url") else config.YOUTUBE_IMG_URL
            vidid = result.get("id") or "None"
            
            if not duration_min or str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
            return title, duration_min, duration_sec, thumbnail, vidid
        except Exception as e:
            print(f"Error in YouTube details: {e}")
            return "Unknown", "00:00", 0, config.YOUTUBE_IMG_URL, "None"

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            search_results = await results.next()
            if not search_results or not isinstance(search_results, dict) or "result" not in search_results or not search_results["result"]:
                return "Unknown"
            return search_results["result"][0].get("title") or "Unknown"
        except:
            return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            search_results = await results.next()
            if not search_results or not isinstance(search_results, dict) or "result" not in search_results or not search_results["result"]:
                return "00:00"
            return search_results["result"][0].get("duration") or "00:00"
        except:
            return "00:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            search_results = await results.next()
            if not search_results or not isinstance(search_results, dict) or "result" not in search_results or not search_results["result"]:
                return config.YOUTUBE_IMG_URL
            thumbnails = search_results["result"][0].get("thumbnails", [])
            return thumbnails[0].get("url").split("?")[0] if thumbnails and isinstance(thumbnails, list) and thumbnails[0].get("url") else config.YOUTUBE_IMG_URL
        except:
            return config.YOUTUBE_IMG_URL

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        
        # Try video API first
        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                return 1, downloaded_file
        except Exception:
            pass
        
        return 0, "Failed to fetch track details via APIs."

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        
        # User snippet used `Playlist.get(link)` via py_yt
        # Playlist is now imported from youtubesearchpython.__future__
        try:
            plist = await Playlist.get(link)
        except:
            return []

        videos = plist.get("videos") or []
        ids: list[str] = []
        for data in videos[:limit]:
            if not data:
                continue
            vid = data.get("id")
            if not vid:
                continue
            ids.append(vid)
        return ids

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            search_results = await results.next()
            if not search_results or not isinstance(search_results, dict) or "result" not in search_results or not search_results["result"]:
                 return {
                    "title": "Unknown",
                    "link": link,
                    "vidid": "None",
                    "duration_min": "00:00",
                    "thumb": config.YOUTUBE_IMG_URL,
                }, "None"

            result = search_results["result"][0]
            title = result.get("title") or "Unknown"
            duration_min = result.get("duration") or "00:00"
            vidid = result.get("id") or "None"
            yturl = result.get("link") or link
            thumbnails = result.get("thumbnails", [])
            thumbnail = thumbnails[0].get("url").split("?")[0] if thumbnails and isinstance(thumbnails, list) and thumbnails[0].get("url") else config.YOUTUBE_IMG_URL
            
            track_details = {
                "title": title,
                "link": yturl,
                "vidid": vidid,
                "duration_min": duration_min,
                "thumb": thumbnail,
            }
            return track_details, vidid
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error in YouTube track: {e}")
            raise e

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            try:
                r = ydl.extract_info(link, download=False)
                for format in r.get("formats", []):
                    try:
                        str(format["format"])
                    except:
                        continue
                    if not "dash" in str(format["format"]).lower():
                        try:
                            format["format"]
                            format.get("filesize")
                            format["format_id"]
                            format["ext"]
                            format.get("format_note")
                        except:
                            continue
                        formats_available.append(
                            {
                                "format": format["format"],
                                "filesize": format.get("filesize"),
                                "format_id": format["format_id"],
                                "ext": format["ext"],
                                "format_note": format.get("format_note"),
                                "yturl": link,
                            }
                        )
            except Exception:
                pass
        return formats_available, link

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            a = VideosSearch(link, limit=10)
            res = await a.next()
            result = res.get("result") if res and isinstance(res, dict) else None
            if not result or len(result) <= query_type:
                return "Unknown", "00:00", config.YOUTUBE_IMG_URL, "None"
                
            item = result[query_type]
            title = item.get("title") or "Unknown"
            duration_min = item.get("duration") or "00:00"
            vidid = item.get("id") or "None"
            thumbnails = item.get("thumbnails", [])
            thumbnail = thumbnails[0].get("url").split("?")[0] if thumbnails and isinstance(thumbnails, list) and thumbnails[0].get("url") else config.YOUTUBE_IMG_URL
            return title, duration_min, thumbnail, vidid
        except:
            return "Unknown", "00:00", config.YOUTUBE_IMG_URL, "None"

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            link = self.base + link
        loop = asyncio.get_running_loop()


        # Helper to try multiple clients for downloading
        def run_with_strategies(opts_template, strategies):
            for strategy in strategies:
                try:
                    opts = opts_template.copy()
                    opts.update(strategy) # merge strategy into opts
                    # Clean up if cookiefile is explicitly None (to disable cookies)
                    if 'cookiefile' in opts and opts['cookiefile'] is None:
                        del opts['cookiefile']

                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(link, download=True)
                        filename = ydl.prepare_filename(info)
                        if os.path.exists(filename):
                            return filename
                except Exception as e:
                    # logging.warning(f"Download failed with strategy {strategy}: {e}")
                    continue
            raise Exception("All download strategies failed.")

        # Define strategies: Android, TV, Web, iOS, Android Creator, Android VR, Mweb (No Cookies)
        strategies = [
            {"extractor_args": {"youtube": {"player_client": ["android", "web"]}}}, # Primary Bypass
            {"extractor_args": {"youtube": {"player_client": ["tv"]}}},
            {}, # Default Web
            {"extractor_args": {"youtube": {"player_client": ["ios"]}}},
            {"extractor_args": {"youtube": {"player_client": ["android_creator"]}}},
            {"extractor_args": {"youtube": {"player_client": ["android_vr"]}}},
            {"extractor_args": {"youtube": {"player_client": ["mweb"]}}},
        ]

        def audio_dl():
            local_strategies = strategies

            ydl_optssx = {
                "format": "bestaudio/best",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
            }
            return run_with_strategies(ydl_optssx, local_strategies)


        def video_dl():
            local_strategies = strategies

            ydl_optssx = {
                "format": "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
            }
            return run_with_strategies(ydl_optssx, local_strategies)


        def song_video_dl():
            formats = f"{format_id}+140" if format_id else "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])"
            ydl_optssx = {
                "format": formats,
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
            }
            return run_with_strategies(ydl_optssx, strategies)

        def song_audio_dl():
             ydl_optssx = {
                "format": format_id or "bestaudio/best",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
             return run_with_strategies(ydl_optssx, strategies)

        if songvideo:
            fpath = await download_video(link)
            if fpath: return fpath
            raise Exception("Failed to download video file")
            
        elif songaudio:
            fpath = await download_song(link)
            if fpath: return fpath
            raise Exception("Failed to download audio file")
            
        elif video:
            fpath = await download_video(link)
            if fpath: 
                 direct = True
                 return fpath, direct
            raise Exception("Failed to download video file")
        else:
            direct = True
            downloaded_file = await download_song(link)
            if downloaded_file:
                return downloaded_file, direct
            raise Exception("Failed to download audio file")
