"""Unit tests for YouTube scraper functionality."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.scraper.youtube import (
    extract_video_id, validate_youtube_url, YouTubeScraper,
    VideoMeta, TranscriptSegment, TranscriptResult,
    _is_shorts_url_or_title, save_transcript_json
)

# Valid 11-char YouTube IDs for testing
VID_A = "dQw4w9WgXcQ"
VID_B = "abcdefghijk"


class TestURLValidation:
    def test_validate_youtube_url(self):
        assert validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert validate_youtube_url("http://youtube.com/watch?v=dQw4w9WgXcQ")
        assert validate_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        assert validate_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
        assert not validate_youtube_url("https://evil.com/watch?v=dQw4w9WgXcQ")
        assert not validate_youtube_url("ftp://youtube.com/watch?v=dQw4w9WgXcQ")
        assert not validate_youtube_url("not-a-url")

    def test_extract_video_id_from_urls(self):
        for url in [
            f"https://www.youtube.com/watch?v={VID_A}",
            f"https://youtu.be/{VID_A}",
            f"https://www.youtube.com/embed/{VID_A}",
            f"https://www.youtube.com/shorts/{VID_A}",
            f"https://www.youtube.com/live/{VID_A}",
            f"https://m.youtube.com/watch?v={VID_A}",
        ]:
            assert extract_video_id(url) == VID_A, f"Failed for {url}"

    def test_extract_video_id_bare_id(self):
        assert extract_video_id(VID_A) == VID_A
        assert extract_video_id(f"  {VID_A}  ") == VID_A

    def test_extract_video_id_invalid(self):
        assert extract_video_id("https://evil.com/watch?v=dQw4w9WgXcQ") is None
        assert extract_video_id("") is None

    def test_is_shorts_detection(self):
        assert _is_shorts_url_or_title("T", "https://youtube.com/shorts/abc")
        assert _is_shorts_url_or_title("Check #shorts", "https://youtube.com/watch?v=abc")
        assert _is_shorts_url_or_title("Shorts test", "https://youtube.com/watch?v=abc")
        assert not _is_shorts_url_or_title("Regular", "https://youtube.com/watch?v=abc")


class TestYouTubeScraper:
    def test_scraper_initialization(self):
        s = YouTubeScraper()
        assert s.proxy == ""
        assert s.rate_limit == 3.0
        assert s.max_retries == 3
        s2 = YouTubeScraper(proxy="socks5h://p:1080", rate_limit_seconds=1.0,
                           max_retries=5, cookies_file="/cookies")
        assert s2.proxy == "socks5h://p:1080"
        assert s2.cookies_file == "/cookies"

    def test_ydl_opts(self):
        s = YouTubeScraper(proxy="socks5h://p:1080", cookies_file="/cookies")
        opts = s._ydl_opts()
        assert opts["quiet"] is True
        assert opts["skip_download"] is True
        assert opts["proxy"] == "socks5h://p:1080"
        assert opts["cookiefile"] == "/cookies"

    def test_throttling(self):
        """Test that throttling sleeps when called too quickly."""
        import time
        s = YouTubeScraper(rate_limit_seconds=2.0)
        # Set last_request_at to now so next call needs to sleep
        s._last_request_at = time.time()
        with patch('time.sleep') as mock_sleep:
            s._throttle()
            mock_sleep.assert_called_once()

    def test_throttling_no_sleep_first_call(self):
        """First call should not sleep."""
        s = YouTubeScraper(rate_limit_seconds=2.0)
        s._last_request_at = 0.0
        with patch('time.sleep') as mock_sleep, patch('time.time', return_value=100.0):
            s._throttle()
            mock_sleep.assert_not_called()

    @patch('app.scraper.youtube.yt_dlp.YoutubeDL')
    def test_fetch_video_metadata_success(self, mock_ydl_class):
        mock_info = {
            'id': VID_A, 'title': 'Test Video',
            'channel': 'Test Channel', 'duration': 213,
            'upload_date': '20230101', 'description': 'desc',
            'webpage_url': f'https://www.youtube.com/watch?v={VID_A}'
        }
        mock_ydl = Mock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        s = YouTubeScraper()
        with patch.object(s, '_throttle'):
            meta = s.fetch_video_metadata(f'https://www.youtube.com/watch?v={VID_A}')
        assert meta is not None
        assert meta.youtube_id == VID_A
        assert meta.title == 'Test Video'

    @patch('app.scraper.youtube.yt_dlp.YoutubeDL')
    def test_fetch_video_metadata_failure(self, mock_ydl_class):
        mock_ydl = Mock()
        mock_ydl.extract_info.side_effect = Exception("Network error")
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        s = YouTubeScraper(max_retries=2)
        with patch.object(s, '_throttle'):
            with patch('time.sleep'):
                meta = s.fetch_video_metadata(f'https://www.youtube.com/watch?v={VID_A}')
        assert meta is None
        assert mock_ydl.extract_info.call_count == 2

    @patch('app.scraper.youtube.yt_dlp.YoutubeDL')
    def test_list_channel_videos(self, mock_ydl_class):
        mock_info = {
            'channel': 'Test Channel',
            'entries': [
                {'id': VID_A, 'title': 'Video 1', 'channel': 'Test Channel', 'duration': 100},
                {'id': VID_B, 'title': 'Video 2', 'channel': 'Test Channel', 'duration': 200},
            ]
        }
        mock_ydl = Mock()
        mock_ydl.extract_info.return_value = mock_info
        mock_ydl_class.return_value.__enter__.return_value = mock_ydl
        s = YouTubeScraper()
        with patch.object(s, '_throttle'):
            videos = s.list_channel_videos('https://www.youtube.com/channel/UCtest')
        assert len(videos) == 2
        assert videos[0].youtube_id == VID_A

    def test_fetch_transcript_success(self):
        from youtube_transcript_api import YouTubeTranscriptApi
        mock_segments = [
            Mock(start=0.0, duration=2.5, text="Hello world"),
            Mock(start=2.5, duration=3.0, text="This is a test"),
        ]
        mock_fetched = Mock()
        mock_fetched.__iter__ = lambda self: iter(mock_segments)
        mock_fetched.language_code = "en"
        mock_fetched.is_generated = True
        s = YouTubeScraper()
        with patch.object(s, '_throttle'):
            with patch.object(YouTubeTranscriptApi, 'fetch', return_value=mock_fetched):
                with patch('youtube_transcript_api.YouTubeTranscriptApi.__init__', return_value=None):
                    result = s.fetch_transcript(VID_A)
        assert result is not None
        assert result.video_id == VID_A
        assert result.raw_text == "Hello world\nThis is a test"

    def test_fetch_transcript_not_available(self):
        from youtube_transcript_api import YouTubeTranscriptApi
        s = YouTubeScraper()
        with patch.object(s, '_throttle'):
            with patch.object(YouTubeTranscriptApi, 'fetch',
                              side_effect=Exception("NoTranscriptFound")):
                with patch('youtube_transcript_api.YouTubeTranscriptApi.__init__', return_value=None):
                    result = s.fetch_transcript(VID_A)
        assert result is None

    def test_scrape_video_integration(self):
        s = YouTubeScraper()
        mock_meta = VideoMeta(youtube_id=VID_A, title='Test Video',
                              channel='Test Channel',
                              url=f'https://www.youtube.com/watch?v={VID_A}')
        mock_transcript = TranscriptResult(
            video_id=VID_A,
            segments=[TranscriptSegment(0.0, 2.0, "Test transcript")],
        )
        with patch.object(s, 'fetch_video_metadata', return_value=mock_meta):
            with patch.object(s, 'fetch_transcript', return_value=mock_transcript):
                # Use the bare ID to bypass URL validation
                result = s.scrape_video(VID_A)
        assert result['video_id'] == VID_A
        assert result['meta'] == mock_meta
        assert result['transcript'] == mock_transcript

    def test_scrape_video_invalid_id(self):
        s = YouTubeScraper()
        with pytest.raises(RuntimeError, match="Cannot extract video ID"):
            s.scrape_video('https://evil.com/watch?v=invalid')

    def test_scrape_video_metadata_failure(self):
        s = YouTubeScraper()
        with patch.object(s, 'fetch_video_metadata', return_value=None):
            with pytest.raises(RuntimeError, match="Failed to fetch metadata"):
                # Use bare valid ID so extract_video_id passes
                s.scrape_video(VID_A)


class TestTranscriptModels:
    def test_transcript_segment(self):
        seg = TranscriptSegment(start=10.5, duration=3.2, text="Test")
        assert seg.start == 10.5
        d = seg.to_dict()
        assert d == {"start": 10.5, "duration": 3.2, "text": "Test"}

    def test_transcript_result(self):
        segs = [TranscriptSegment(0.0, 2.0, "Hello"),
                TranscriptSegment(2.0, 3.0, "world")]
        r = TranscriptResult(video_id="t123", segments=segs)
        assert r.raw_text == "Hello\nworld"

    def test_save_transcript_json(self, temp_dir):
        segs = [TranscriptSegment(0.0, 2.0, "Hello"),
                TranscriptSegment(2.0, 3.0, "world")]
        r = TranscriptResult(video_id="t123", segments=segs)
        json_path = save_transcript_json(r, temp_dir)
        assert json_path.exists()
        import json
        data = json.loads(json_path.read_text())
        assert data["video_id"] == "t123"
        txt = (temp_dir / "t123.txt").read_text()
        assert txt == "Hello\nworld"


class TestVideoMetaModel:
    def test_creation(self):
        m = VideoMeta(youtube_id="abc", title="T", channel="C",
                      url="https://www.youtube.com/watch?v=abc")
        assert m.youtube_id == "abc"
        assert m.duration_seconds is None

    def test_full_creation(self):
        m = VideoMeta(youtube_id="abc", title="T", channel="C",
                      url="https://www.youtube.com/watch?v=abc",
                      duration_seconds=120, upload_date="20230101",
                      description="desc", is_shorts=True)
        assert m.duration_seconds == 120
        assert m.is_shorts is True
