"""Integration tests for API routes."""
import pytest
import json
from unittest.mock import patch, Mock
from fastapi import status
from app.database import upsert_video, create_article, set_article_tags, sync_article_to_fts


class TestHealthEndpoint:
    """Test health check endpoint."""
    
    def test_health_check(self, client):
        """Test health endpoint returns OK."""
        response = client.get("/api/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}


class TestArticleEndpoints:
    """Test article-related API endpoints."""
    
    def test_list_articles_empty(self, client):
        """Test listing articles when none exist."""
        response = client.get("/api/articles")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert data["limit"] == 50
        assert data["offset"] == 0
    
    def test_list_articles_with_data(self, client, db_conn):
        """Test listing articles with test data."""
        # Create test articles
        article1_id = create_article(
            db_conn, video_id=None, title="Article 1", slug="article-1",
            content_markdown="Content 1", category="automotive", status="published"
        )
        article2_id = create_article(
            db_conn, video_id=None, title="Article 2", slug="article-2", 
            content_markdown="Content 2", category="diagnostic", status="draft"
        )
        
        response = client.get("/api/articles")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        
        # Check article data structure
        article_data = data["items"][0]  # Most recent first
        assert "id" in article_data
        assert "title" in article_data
        assert "slug" in article_data
        assert "category" in article_data
        assert "status" in article_data
        assert "tags" in article_data
        assert "updated_at" in article_data
        # Should not include full content in list view
        assert "content_markdown" not in article_data
    
    def test_list_articles_with_filters(self, client, db_conn):
        """Test listing articles with status filter."""
        # Create test articles with different statuses
        create_article(
            db_conn, video_id=None, title="Published Article", slug="published",
            content_markdown="Content", status="published"
        )
        create_article(
            db_conn, video_id=None, title="Draft Article", slug="draft",
            content_markdown="Content", status="draft"
        )
        
        # Test status filter
        response = client.get("/api/articles?status=published")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Published Article"
        
        # Test category filter
        response = client.get("/api/articles?category=nonexistent")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 0
    
    def test_list_articles_with_search(self, client, db_conn):
        """Test listing articles with full-text search."""
        # Create test articles
        article1_id = create_article(
            db_conn, video_id=None, title="Honda Civic Repair", slug="honda-repair",
            content_markdown="Guide to fixing Honda Civic engine problems",
            category="automotive", status="published"
        )
        article2_id = create_article(
            db_conn, video_id=None, title="Toyota Maintenance", slug="toyota-maintenance",
            content_markdown="Toyota Camry maintenance tips and tricks",
            category="automotive", status="published"
        )
        
        # Sync to FTS
        sync_article_to_fts(db_conn, article1_id)
        sync_article_to_fts(db_conn, article2_id)
        
        # Search for Honda
        response = client.get("/api/articles?q=Honda")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Honda Civic Repair"
        
        # Search for maintenance 
        response = client.get("/api/articles?q=maintenance")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Toyota Maintenance"
    
    def test_get_article_detail(self, client, db_conn):
        """Test getting article detail by ID."""
        article_id = create_article(
            db_conn, video_id=None, title="Test Article", slug="test-article",
            content_markdown="# Test Article\n\nThis is test content.",
            category="test", source_channel="Test Channel",
            source_url="https://youtube.com/watch?v=test",
            dtc_codes="P0123,P0456", vehicle_refs="Honda Civic",
            tools_used="OBD scanner", status="published"
        )
        set_article_tags(db_conn, article_id, ["test", "automotive"])
        
        response = client.get(f"/api/articles/{article_id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["id"] == article_id
        assert data["title"] == "Test Article"
        assert data["slug"] == "test-article"
        assert data["content_markdown"] == "# Test Article\n\nThis is test content."
        assert data["category"] == "test"
        assert data["source_channel"] == "Test Channel"
        assert data["source_url"] == "https://youtube.com/watch?v=test"
        assert data["dtc_codes"] == ["P0123", "P0456"]
        assert data["vehicle_refs"] == ["Honda Civic"]
        assert data["tools_used"] == ["OBD scanner"]
        assert data["status"] == "published"
        assert set(data["tags"]) == {"test", "automotive"}
        assert "created_at" in data
        assert "updated_at" in data
    
    def test_get_article_not_found(self, client):
        """Test getting non-existent article returns 404."""
        response = client.get("/api/articles/999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Article not found"


class TestVideoSubmissionEndpoint:
    """Test video submission endpoint."""
    
    @patch('app.api.routes.get_scraper')
    @patch('app.api.routes.run_in_threadpool')
    def test_submit_valid_youtube_url(self, mock_threadpool, mock_get_scraper, client, db_conn):
        """Test submitting a valid YouTube URL."""
        # Mock scraper and metadata
        mock_meta = Mock()
        mock_meta.youtube_id = "dQw4w9WgXcQ"
        mock_meta.title = "Test Video"
        mock_meta.channel = "Test Channel"
        mock_meta.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        mock_meta.duration_seconds = 213
        
        mock_scraper = Mock()
        mock_scraper.fetch_video_metadata.return_value = mock_meta
        mock_get_scraper.return_value = mock_scraper
        mock_threadpool.return_value = mock_meta
        
        response = client.post("/api/submit?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["ok"] is True
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert data["status"] == "pending"
        assert data["title"] == "Test Video"
        assert "Queued for scraping" in data["message"]
    
    def test_submit_invalid_url(self, client):
        """Test submitting an invalid URL."""
        response = client.post("/api/submit?url=https://evil.com/watch?v=malicious")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or non-YouTube URL rejected" in response.json()["detail"]
    
    def test_submit_invalid_video_id(self, client):
        """Test submitting URL with no extractable video ID."""
        response = client.post("/api/submit?url=https://youtube.com/invalid")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Could not extract a YouTube video ID" in response.json()["detail"]
    
    def test_submit_existing_video(self, client, db_conn):
        """Test submitting a video that already exists."""
        # Create existing video
        video_id = upsert_video(
            db_conn, "dQw4w9WgXcQ", "Existing Video", "Test Channel",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ", status="scraped"
        )
        
        response = client.post("/api/submit?url=dQw4w9WgXcQ")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["ok"] is True
        assert data["video_id"] == "dQw4w9WgXcQ"
        assert data["status"] == "scraped"
        assert "already known" in data["message"]


class TestChannelEndpoints:
    """Test channel management endpoints."""
    
    def test_list_channels_empty(self, client):
        """Test listing channels when none exist."""
        response = client.get("/api/channels")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
    
    def test_list_channels_with_data(self, client, db_conn):
        """Test listing channels with video data."""
        # Create test videos with different channels
        upsert_video(db_conn, "video1", "Video 1", "Channel A", "url1")
        upsert_video(db_conn, "video2", "Video 2", "Channel B", "url2")
        upsert_video(db_conn, "video3", "Video 3", "Channel A", "url3")
        
        response = client.get("/api/channels")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        # Should have 2 channels
        assert len(data["items"]) == 2
        
        # Find Channel A (should have count 2)
        channel_a = next(item for item in data["items"] if item["channel"] == "Channel A")
        assert channel_a["count"] == 2
        
        # Find Channel B (should have count 1)
        channel_b = next(item for item in data["items"] if item["channel"] == "Channel B")
        assert channel_b["count"] == 1
    
    def test_add_channel_unauthorized(self, client):
        """Test adding channel without API key."""
        response = client.post("/api/channels?url=https://youtube.com/channel/test")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid or missing API key" in response.json()["detail"]
    
    def test_add_channel_authorized(self, client):
        """Test adding channel with valid API key."""
        headers = {"X-API-Key": "test_password"}  # Using admin password as API key
        response = client.post(
            "/api/channels?url=https://youtube.com/channel/test&name=Test Channel",
            headers=headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["ok"] is True
        assert "id" in data
    
    def test_add_invalid_channel_url(self, client):
        """Test adding invalid channel URL."""
        headers = {"X-API-Key": "test_password"}
        response = client.post(
            "/api/channels?url=https://evil.com/channel/malicious",
            headers=headers
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or non-YouTube URL rejected" in response.json()["detail"]
    
    def test_delete_channel_unauthorized(self, client):
        """Test deleting channel without API key."""
        response = client.delete("/api/channels/1")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_delete_channel_authorized(self, client, db_conn):
        """Test deleting channel with valid API key."""
        # Create a source first
        from app.database import add_source
        source_id = add_source(db_conn, "https://youtube.com/channel/test", "channel")
        
        headers = {"X-API-Key": "test_password"}
        response = client.delete(f"/api/channels/{source_id}", headers=headers)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["ok"] is True


class TestMetadataEndpoints:
    """Test metadata endpoints for categories, tags, and queue."""
    
    def test_categories_empty(self, client):
        """Test categories endpoint when no articles exist."""
        response = client.get("/api/categories")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
    
    def test_categories_with_data(self, client, db_conn):
        """Test categories endpoint with article data."""
        create_article(
            db_conn, video_id=None, title="Article 1", slug="article-1",
            content_markdown="Content", category="automotive", status="published"
        )
        create_article(
            db_conn, video_id=None, title="Article 2", slug="article-2",
            content_markdown="Content", category="automotive", status="published"
        )
        create_article(
            db_conn, video_id=None, title="Article 3", slug="article-3",
            content_markdown="Content", category="diagnostic", status="published"
        )
        
        response = client.get("/api/categories")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert len(data["items"]) == 2
        # Should be sorted by count descending
        assert data["items"][0]["category"] == "automotive"
        assert data["items"][0]["count"] == 2
        assert data["items"][1]["category"] == "diagnostic"
        assert data["items"][1]["count"] == 1
    
    def test_tags_empty(self, client):
        """Test tags endpoint when no tags exist."""
        response = client.get("/api/tags")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
    
    def test_tags_with_data(self, client, db_conn):
        """Test tags endpoint with tag data."""
        # Create articles with tags
        article1_id = create_article(
            db_conn, video_id=None, title="Article 1", slug="article-1",
            content_markdown="Content", status="published"
        )
        article2_id = create_article(
            db_conn, video_id=None, title="Article 2", slug="article-2", 
            content_markdown="Content", status="published"
        )
        
        set_article_tags(db_conn, article1_id, ["honda", "automotive"])
        set_article_tags(db_conn, article2_id, ["honda", "diagnostic"])
        
        response = client.get("/api/tags")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        # Should have 3 unique tags
        assert len(data["items"]) == 3
        
        # Find honda tag (should have count 2)
        honda_tag = next(item for item in data["items"] if item["name"] == "honda")
        assert honda_tag["count"] == 2
    
    def test_queue_empty(self, client):
        """Test queue endpoint when no jobs exist."""
        response = client.get("/api/queue")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
    
    def test_queue_with_data(self, client, db_conn):
        """Test queue endpoint with job data."""
        # Create test video and jobs
        from app.database import enqueue_job
        
        video_id = upsert_video(
            db_conn, "test123", "Test Video", "Test Channel", "url"
        )
        job1_id = enqueue_job(db_conn, video_id, "scrape")
        job2_id = enqueue_job(db_conn, video_id, "process")
        
        response = client.get("/api/queue")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert len(data["items"]) == 2
        
        # Check job structure
        job_data = data["items"][0]  # Most recent first
        assert "id" in job_data
        assert "job_type" in job_data
        assert "status" in job_data
        assert "youtube_id" in job_data
        assert "video_title" in job_data
        assert "channel" in job_data
        assert "created_at" in job_data
    
    def test_queue_status_filter(self, client, db_conn):
        """Test queue endpoint with status filter."""
        from app.database import enqueue_job, finish_job
        
        video_id = upsert_video(
            db_conn, "test123", "Test Video", "Test Channel", "url"
        )
        pending_job = enqueue_job(db_conn, video_id, "scrape")
        done_job = enqueue_job(db_conn, video_id, "process")
        finish_job(db_conn, done_job, "done")
        
        # Test pending filter
        response = client.get("/api/queue?status=pending")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "pending"
        
        # Test done filter  
        response = client.get("/api/queue?status=done")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "done"