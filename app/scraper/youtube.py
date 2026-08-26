"""yt-dlp + youtube-transcript-api wrapper with SOCKS5 proxy support.

Handles both single videos and channels/playlists. Extracts video metadata
(yt-dlp) and transcripts (youtube-transcript-api) with retry + rate limiting.
"""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yt_dlp

logger = logging.getLogger(__name__)

YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")


@dataclass
class VideoMeta:
    youtube_id: str
    title: str
    channel: str
    url: str
    duration_seconds: Optional[int] = None
    upload_date: Optional[str] = None
    description: Optional[str] = None
    is_shorts: bool = False


@dataclass
class TranscriptSegment:
    start: float
    duration: float
    text: str

    def to_dict(self) -> dict:
        return {"start": self.start, "duration": self.duration, "text": self.text}


@dataclass
class TranscriptResult:
    video_id: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = "en"
    is_auto_generated: bool = True

    @property
    def raw_text(self) -> str:
        return "\n".join(s.text for s in self.segments)


def validate_youtube_url(url: str) -> bool:
    """Validate that URL is a legitimate YouTube domain to prevent SSRF."""
    try:
        parsed = urlparse(url.lower())
        allowed_domains = {
            "youtube.com", "www.youtube.com", "m.youtube.com", 
            "youtu.be", "www.youtu.be"
        }
        return parsed.netloc in allowed_domains and parsed.scheme in ("http", "https")
    except Exception:
        return False


def extract_video_id(text: str) -> Optional[str]:
    """Extract an 11-char YouTube video ID from a URL or bare ID string.
    
    Validates URLs to ensure they're from YouTube domains to prevent SSRF.
    """
    text = text.strip()
    
    # If it looks like a URL, validate the domain first
    if "://" in text and not validate_youtube_url(text):
        return None
    
    # If it's exactly an 11-char ID, allow it
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
        
    # Extract from validated YouTube URLs
    m = YOUTUBE_ID_RE.search(text)
    if m:
        return m.group(1)
        
    # Last-resort: any 11-char token in the string (only if no URL detected)
    if "://" not in text:
        for tok in re.findall(r"[A-Za-z0-9_-]{11}", text):
            return tok
            
    return None


def _is_shorts_url_or_title(title: str, url: str) -> bool:
    if "/shorts/" in url:
        return True
    lowered = title.lower()
    return bool(re.search(r"#shorts\b", lowered)) or lowered.startswith("shorts ")


class YouTubeScraper:
    """Wrapper around yt-dlp + youtube-transcript-api.

    Args:
        proxy: SOCKS5 URL like socks5h://user:pass@host:port. If empty,
               direct connection is attempted.
        rate_limit_seconds: base delay between network requests.
        max_retries: retries for transient failures (exponential backoff).
    """

    def __init__(self, proxy: Optional[str] = None, rate_limit_seconds: float = 3.0,
                 max_retries: int = 3, cookies_file: Optional[str] = None):
        self.proxy = proxy or ""
        self.rate_limit = rate_limit_seconds
        self.max_retries = max_retries
        self.cookies_file = cookies_file
        self._last_request_at = 0.0

    # -- rate limiting ------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_at
        delay = self.rate_limit + random.uniform(-0.5, 1.5)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request_at = time.time()

    # -- yt-dlp options ------------------------------------------------------

    def _ydl_opts(self, *, quiet: bool = True) -> dict:
        opts: dict = {
            "quiet": quiet,
            "no_warnings": quiet,
            "skip_download": True,
            "ignoreerrors": True,
            "noplaylist": True,
            "extract_flat": "in_playlist",
            "socket_timeout": 30,
            "retries": self.max_retries,
            "fragment_retries": self.max_retries,
        }
        if self.proxy:
            opts["proxy"] = self.proxy
            opts["socks_proxy"] = self.proxy
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        return opts

    # -- single video metadata ----------------------------------------------

    def fetch_video_metadata(self, url_or_id: str) -> Optional[VideoMeta]:
        """Fetch metadata for a single video via yt-dlp."""
        # Validate URL if it contains a protocol to prevent SSRF
        if "://" in url_or_id and not validate_youtube_url(url_or_id):
            logger.error("Invalid or non-YouTube URL rejected: %r", url_or_id)
            return None
            
        video_id = extract_video_id(url_or_id)
        if not video_id:
            logger.error("Could not extract video ID from %r", url_or_id)
            return None
        url = f"https://www.youtube.com/watch?v={video_id}"
        opts = self._ydl_opts()
        opts["noplaylist"] = True
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        return None
                    return self._build_meta(info)
            except Exception as exc:  # noqa: BLE001 - yt-dlp raises varied exceptions
                last_err = exc
                logger.warning("Metadata attempt %d/%d failed for %s: %s",
                               attempt, self.max_retries, url, exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
        logger.error("Failed to fetch metadata for %s: %s", url, last_err)
        return None

    def _build_meta(self, info: dict) -> VideoMeta:
        video_id = info.get("id") or extract_video_id(str(info.get("webpage_url", ""))) or ""
        url = f"https://www.youtube.com/watch?v={video_id}"
        title = info.get("title") or "(untitled)"
        channel = info.get("channel") or info.get("uploader") or info.get("channel_id") or "unknown"
        duration = info.get("duration")
        if isinstance(duration, float):
            duration = int(duration)
        return VideoMeta(
            youtube_id=video_id,
            title=title,
            channel=channel,
            url=url,
            duration_seconds=duration,
            upload_date=info.get("upload_date"),
            description=info.get("description"),
            is_shorts=_is_shorts_url_or_title(title, str(info.get("webpage_url", ""))),
        )

    # -- channel / playlist listing -----------------------------------------

    def list_channel_videos(self, channel_url: str, *, flat: bool = True) -> list[VideoMeta]:
        """List videos from a channel (handle /@handle, /channel/, /c/ forms).

        Uses yt-dlp's flat extraction to avoid downloading every page fully.
        """
        # Validate channel URL to prevent SSRF
        if not validate_youtube_url(channel_url):
            logger.error("Invalid or non-YouTube channel URL rejected: %r", channel_url)
            return []
            
        metas: list[VideoMeta] = []
        seen: set[str] = set()
        opts = self._ydl_opts()
        opts["noplaylist"] = False
        opts["extract_flat"] = True
        opts["playlist_items"] = "1-10000"
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(channel_url, download=False)
                    entries = info.get("entries") or []
                    for entry in entries:
                        if not entry or not entry.get("id"):
                            continue
                        vid = entry["id"]
                        if vid in seen:
                            continue
                        seen.add(vid)
                        title = entry.get("title") or "(untitled)"
                        meta = VideoMeta(
                            youtube_id=vid,
                            title=title,
                            channel=entry.get("channel") or info.get("channel") or "unknown",
                            url=f"https://www.youtube.com/watch?v={vid}",
                            duration_seconds=entry.get("duration"),
                            upload_date=entry.get("upload_date"),
                            is_shorts=_is_shorts_url_or_title(title, str(entry.get("url", ""))),
                        )
                        metas.append(meta)
                return metas
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning("Channel listing attempt %d/%d failed for %s: %s",
                               attempt, self.max_retries, channel_url, exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
        logger.error("Failed to list channel %s: %s", channel_url, last_err)
        return metas

    def list_playlist_videos(self, playlist_url: str) -> list[VideoMeta]:
        """List videos from a playlist URL or bare playlist ID."""
        if re.fullmatch(r"[A-Za-z0-9_-]+", playlist_url.strip()) and "youtube" not in playlist_url:
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_url.strip()}"
        
        # Validate playlist URL to prevent SSRF
        if not validate_youtube_url(playlist_url):
            logger.error("Invalid or non-YouTube playlist URL rejected: %r", playlist_url)
            return []
            
        return self.list_channel_videos(playlist_url)

    # -- transcripts ----------------------------------------------------------

    def fetch_transcript(self, url_or_id: str) -> Optional[TranscriptResult]:
        """Fetch a transcript using youtube-transcript-api (with proxy).

        Falls back gracefully: returns None if no transcript is available.
        """
        video_id = extract_video_id(url_or_id)
        if not video_id:
            return None
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            from youtube_transcript_api.proxies import GenericProxyConfig
        except ImportError as exc:  # pragma: no cover
            logger.error("youtube-transcript-api not installed: %s", exc)
            return None

        api_kwargs: dict = {}
        if self.proxy:
            api_kwargs["proxy_config"] = GenericProxyConfig(http_url=self.proxy, https_url=self.proxy)

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                api = YouTubeTranscriptApi(**api_kwargs)
                fetched = api.fetch(video_id)
                segments = [
                    TranscriptSegment(start=float(s.start), duration=float(s.duration), text=s.text)
                    for s in fetched
                ]
                lang = getattr(fetched, "language_code", "en") or "en"
                is_auto = bool(getattr(fetched, "is_generated", True))
                if not segments:
                    return None
                return TranscriptResult(
                    video_id=video_id,
                    segments=segments,
                    language=lang,
                    is_auto_generated=is_auto,
                )
            except Exception as exc:  # noqa: BLE001 - various transcript API errors
                err_str = str(exc)
                err_cls = type(exc).__name__
                # No transcript available -> not retryable
                if err_cls in ("NoTranscriptFound", "TranscriptsDisabled", "VideoUnavailable",
                               "VideoUnplayable", "AgeRestricted", "InvalidVideoId",
                               "NotTranslatable", "TranslationLanguageNotAvailable"):
                    logger.info("No transcript available for %s (%s)", video_id, err_cls)
                    return None
                # IP blocked / bot-check -> not retryable without a different proxy
                if err_cls in ("RequestBlocked", "IpBlocked", "PoTokenRequired",
                               "YouTubeRequestFailed") or any(k in err_str.lower() for k in
                               ("sign in to confirm", "blocking requests", "bot")):
                    logger.warning("Transcript blocked for %s (%s): %s", video_id, err_cls, err_str[:200])
                    return None
                last_err = exc
                logger.warning("Transcript attempt %d/%d failed for %s: %s",
                               attempt, self.max_retries, video_id, exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 30))
        logger.warning("Failed to fetch transcript for %s: %s", video_id, last_err)
        return None

    # -- combined scrape ------------------------------------------------------

    def scrape_video(self, url_or_id: str) -> dict:
        """Scrape metadata + transcript for one video.

        Returns a dict: {meta, transcript, video_id} or raises RuntimeError.
        """
        video_id = extract_video_id(url_or_id)
        if not video_id:
            raise RuntimeError(f"Cannot extract video ID from {url_or_id!r}")

        meta = self.fetch_video_metadata(url_or_id)
        if meta is None:
            raise RuntimeError(f"Failed to fetch metadata for {url_or_id}")

        transcript = self.fetch_transcript(video_id)
        return {"meta": meta, "transcript": transcript, "video_id": video_id}


def save_transcript_json(result: TranscriptResult, transcripts_dir: Path) -> Path:
    """Persist a transcript as JSON (segments) plus a .txt of raw text."""
    import json

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    json_path = transcripts_dir / f"{result.video_id}.json"
    txt_path = transcripts_dir / f"{result.video_id}.txt"
    json_path.write_text(json.dumps({
        "video_id": result.video_id,
        "language": result.language,
        "is_auto_generated": result.is_auto_generated,
        "segments": [s.to_dict() for s in result.segments],
    }, indent=2), encoding="utf-8")
    txt_path.write_text(result.raw_text, encoding="utf-8")
    return json_path
