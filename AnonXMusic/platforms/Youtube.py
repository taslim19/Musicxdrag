import asyncio
import os
import re
import json
from typing import Union

from yt_dlp import YoutubeDL
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch

import config
from AnonXMusic.utils.database import is_on_off
from AnonXMusic.utils.formatters import time_to_seconds


def cookiefile():
    cookie_dir = "cookies"
    cookies_files = [f for f in os.listdir(cookie_dir) if f.endswith(".txt")]

    return os.path.join(cookie_dir, cookies_files[0])


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
        # Allow overriding piped base via config.PIPED_BASE. Default to piped.video.
        self.piped_base = getattr(config, "PIPED_BASE", "https://piped.video")

    # ----- helper methods for piped -----
    def _is_youtube_link(self, link: str) -> bool:
        if not link:
            return False
        return bool(re.search(self.regex, link)) or len(link) == 11

    def _extract_video_id(self, link: str) -> Union[str, None]:
        # If it's already an 11-char id, return it
        if link and len(link) == 11 and re.match(r"^[A-Za-z0-9_-]{11}$", link):
            return link
        # Try to parse typical youtube link forms
        try:
            if "v=" in link:
                vidid = link.split("v=")[-1].split("&")[0]
                if re.match(r"^[A-Za-z0-9_-]{11}$", vidid):
                    return vidid
            if "youtu.be/" in link:
                vidid = link.split("youtu.be/")[-1].split("?")[0]
                if re.match(r"^[A-Za-z0-9_-]{11}$", vidid):
                    return vidid
        except Exception:
            return None
        return None

    def _piped_watch_url(self, link: str) -> Union[str, None]:
        """
        Return a piped.watch URL for the given youtube link/id, or None.
        """
        vidid = self._extract_video_id(link)
        if vidid:
            return f"{self.piped_base}/watch?v={vidid}"
        return None

    # ----- existing API methods (modified to try piped) -----
    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

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
        return None if offset in (None,) else text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        """
        Try piped first (if applicable), then fallback to original link.
        Returns (1, url) on success (stdout first line), or (0, stderr) on failure.
        """
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]

        candidates = [link]
        # if youtube-like link or id, try piped variant first
        piped = self._piped_watch_url(link)
        if piped:
            candidates.insert(0, piped)

        for candidate in candidates:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--cookies",
                cookiefile(),
                "-g",
                "-f",
                "best[height<=?720][width<=?1280]",
                f"{candidate}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if stdout:
                return (1, stdout.decode().split("\n")[0])
            # if stderr mentions piped-specific issue, continue to next candidate
            # else if last candidate, return stderr
            # continue loop to try next candidate
        # if none succeeded, return the last stderr
        return (0, (stderr.decode() if stderr else "Unknown error"))

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        cmd = (
            f"yt-dlp -i --compat-options no-youtube-unavailable-videos "
            f"--get-id --flat-playlist --playlist-end {limit} --skip-download '{link}' "
            f"2>/dev/null"
        )
        playlist = await shell_cmd(cmd)
        try:
            result = [key for key in playlist.split("\n") if key]
        except Exception:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
            "cookiefile": cookiefile(),
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]

        candidates = [link]
        piped = self._piped_watch_url(link)
        if piped:
            candidates.insert(0, piped)

        ytdl_opts = {"quiet": True}
        for candidate in candidates:
            try:
                ydl = YoutubeDL(ytdl_opts)
                with ydl:
                    formats_available = []
                    r = ydl.extract_info(candidate, download=False)
                    for fmt in r.get("formats", []):
                        try:
                            str(fmt["format"])
                        except Exception:
                            continue
                        if "dash" not in str(fmt["format"]).lower():
                            try:
                                fmt["format"]
                                fmt.get("filesize")
                                fmt["format_id"]
                                fmt["ext"]
                                fmt.get("format_note", "")
                            except Exception:
                                continue
                            formats_available.append(
                                {
                                    "format": fmt["format"],
                                    "filesize": fmt.get("filesize"),
                                    "format_id": fmt["format_id"],
                                    "ext": fmt["ext"],
                                    "format_note": fmt.get("format_note", ""),
                                    "yturl": candidate,
                                    "cookiefile": cookiefile(),
                                }
                            )
                    # If formats found, return them
                    if formats_available:
                        return formats_available, link
            except Exception:
                # try next candidate
                continue
        # if all candidates fail, raise or return empty
        return [], link

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
        a = VideosSearch(link, limit=10)
        result = (await a.next()).get("result")
        title = result[query_type]["title"]
        duration_min = result[query_type]["duration"]
        vidid = result[query_type]["id"]
        thumbnail = result[query_type]["thumbnails"][0]["url"].split("?")[0]
        return title, duration_min, thumbnail, vidid

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
        """
        Attempts download using piped first (when applicable) then falls back to original link.
        Returns (downloaded_file, direct) or path string depending on the flags (preserves previous API).
        """
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]

        # Build candidate list: try piped first if possible
        candidates = [link]
        piped = self._piped_watch_url(link)
        if piped:
            candidates.insert(0, piped)

        loop = asyncio.get_running_loop()

        # create parameterized download functions so we can pass different candidate links
        def _audio_dl_candidate(cand_link):
            ydl_optssx = {
                "cookiefile": cookiefile(),
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
            }
            with YoutubeDL(ydl_optssx) as x:
                info = x.extract_info(cand_link, False)
                xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                if os.path.exists(xyz):
                    return xyz
                x.download([cand_link])
                return xyz

        def _video_dl_candidate(cand_link):
            ydl_optssx = {
                "cookiefile": cookiefile(),
                "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
            }
            with YoutubeDL(ydl_optssx) as x:
                info = x.extract_info(cand_link, False)
                xyz = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                if os.path.exists(xyz):
                    return xyz
                x.download([cand_link])
                return xyz

        def _song_video_dl_candidate(cand_link):
            formats = f"{format_id}+140"
            fpath = f"downloads/{title}"
            ydl_optssx = {
                "format": formats,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "cookiefile": cookiefile(),
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
            }
            x = YoutubeDL(ydl_optssx)
            x.download([cand_link])

        def _song_audio_dl_candidate(cand_link):
            fpath = f"downloads/{title}.%(ext)s"
            ydl_optssx = {
                "format": format_id,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "cookiefile": cookiefile(),
                "prefer_ffmpeg": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
            x = YoutubeDL(ydl_optssx)
            x.download([cand_link])

        # If songvideo or songaudio we don't need candidate swapping logic beyond trying piped then original
        if songvideo:
            last_exc = None
            for cand in candidates:
                try:
                    await loop.run_in_executor(None, _song_video_dl_candidate, cand)
                    fpath = f"downloads/{title}.mp4"
                    return fpath
                except Exception as e:
                    last_exc = e
                    continue
            # If we reach here, all failed
            raise last_exc or Exception("song video download failed")

        if songaudio:
            last_exc = None
            for cand in candidates:
                try:
                    await loop.run_in_executor(None, _song_audio_dl_candidate, cand)
                    fpath = f"downloads/{title}.mp3"
                    return fpath
                except Exception as e:
                    last_exc = e
                    continue
            raise last_exc or Exception("song audio download failed")

        if video:
            # If is_on_off(1) True -> use download path for video
            if await is_on_off(1):
                # attempt to download using candidates
                last_exc = None
                for cand in candidates:
                    try:
                        downloaded_file = await loop.run_in_executor(None, _video_dl_candidate, cand)
                        return downloaded_file, True
                    except Exception as e:
                        last_exc = e
                        continue
                # all failed
                raise last_exc or Exception("video download failed")
            else:
                # try to get direct URL via yt-dlp -g (piped first)
                for cand in candidates:
                    proc = await asyncio.create_subprocess_exec(
                        "yt-dlp",
                        "--cookies",
                        cookiefile(),
                        "-g",
                        "-f",
                        "best[height<=?720][width<=?1280]",
                        f"{cand}",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await proc.communicate()
                    if stdout:
                        downloaded_file = stdout.decode().split("\n")[0]
                        direct = None
                        return downloaded_file, direct
                    # else try next candidate
                # if none returned stdout, return None
                return

        # default: audio download
        last_exc = None
        for cand in candidates:
            try:
                downloaded_file = await loop.run_in_executor(None, _audio_dl_candidate, cand)
                direct = True
                return downloaded_file, direct
            except Exception as e:
                last_exc = e
                continue
        # if none succeeded
        raise last_exc or Exception("audio download failed")
