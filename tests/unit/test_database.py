"""Unit tests for database functionality."""
import pytest
import sqlite3
from app.database import (
    upsert_video, get_video_by_youtube_id, get_video, list_videos, update_video_status,
    add_source, list_sources, remove_source, touch_source,
    save_transcript, get_transcript_for_video,
    enqueue_job, claim_next_job, finish_job, fail_job, list_jobs, reset_stuck_jobs,
    create_article, get_article, get_article_by_slug, list_articles, update_article,
    set_article_status, delete_article, set_article_tags, get_article_tags,
    sync_article_to_fts, search_articles, _fts_query
)


class TestVideoOperations:
    """Test video database operations."""
    
    def test_upsert_video_new(self, db_conn, sample_video_data):
        """Test inserting a new video."""
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"],
            sample_video_data["duration_seconds"]
        )
        assert video_id is not None
        
        # Verify the video was inserted
        video = get_video_by_youtube_id(db_conn, sample_video_data["youtube_id"])
        assert video is not None
        assert video["youtube_id"] == sample_video_data["youtube_id"]
        assert video["title"] == sample_video_data["title"]
        assert video["channel"] == sample_video_data["channel"]
        assert video["url"] == sample_video_data["url"]
        assert video["duration_seconds"] == sample_video_data["duration_seconds"]
    
    def test_upsert_video_update(self, db_conn, sample_video_data):
        """Test updating an existing video."""
        # Insert original video
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            "Original Title",
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        # Update with new title
        updated_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"],
            sample_video_data["duration_seconds"]
        )
        
        # Should return same ID
        assert updated_id == video_id
        
        # Verify the update
        video = get_video(db_conn, video_id)
        assert video["title"] == sample_video_data["title"]
        assert video["duration_seconds"] == sample_video_data["duration_seconds"]
    
    def test_list_videos(self, db_conn, sample_video_data):
        """Test listing videos with filters."""
        # Insert test videos
        upsert_video(db_conn, "video1", "Title 1", "Channel A", "url1", status="pending")
        upsert_video(db_conn, "video2", "Title 2", "Channel B", "url2", status="scraped")
        upsert_video(db_conn, "video3", "Title 3", "Channel A", "url3", status="published")
        
        # Test status filter
        pending_videos = list_videos(db_conn, status="pending")
        assert len(pending_videos) == 1
        assert pending_videos[0]["youtube_id"] == "video1"
        
        # Test channel filter
        channel_a_videos = list_videos(db_conn, channel="Channel A")
        assert len(channel_a_videos) == 2
        
        # Test limit
        limited_videos = list_videos(db_conn, limit=1)
        assert len(limited_videos) == 1
    
    def test_update_video_status(self, db_conn, sample_video_data):
        """Test updating video status."""
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        update_video_status(db_conn, video_id, "processed")
        
        video = get_video(db_conn, video_id)
        assert video["status"] == "processed"


class TestSourceOperations:
    """Test source (channel/playlist) database operations."""
    
    def test_add_source(self, db_conn):
        """Test adding a new source."""
        source_id = add_source(
            db_conn,
            "https://youtube.com/channel/test",
            "channel",
            "Test Channel",
            auto_scrape=True
        )
        assert source_id is not None
        
        sources = list_sources(db_conn)
        assert len(sources) == 1
        assert sources[0]["url"] == "https://youtube.com/channel/test"
        assert sources[0]["type"] == "channel"
        assert sources[0]["name"] == "Test Channel"
        assert sources[0]["auto_scrape"] == 1
    
    def test_add_duplicate_source(self, db_conn):
        """Test adding duplicate source returns existing ID."""
        url = "https://youtube.com/channel/test"
        source_id1 = add_source(db_conn, url, "channel", "Test")
        # With INSERT OR IGNORE, lastrowid is 0 on conflict; query for actual ID
        source_id2 = add_source(db_conn, url, "channel", "Test Updated")
        
        # Both should resolve to the same source
        assert source_id1 == source_id2
        assert len(list_sources(db_conn)) == 1
    
    def test_remove_source(self, db_conn):
        """Test removing a source."""
        source_id = add_source(db_conn, "https://youtube.com/test", "channel")
        assert len(list_sources(db_conn)) == 1
        
        remove_source(db_conn, source_id)
        assert len(list_sources(db_conn)) == 0
    
    def test_touch_source(self, db_conn):
        """Test updating source last_scraped_at."""
        source_id = add_source(db_conn, "https://youtube.com/test", "channel")
        
        # Initially should be None
        source = list_sources(db_conn)[0]
        assert source["last_scraped_at"] is None
        
        touch_source(db_conn, source_id)
        
        # Should now have a timestamp
        updated_source = list_sources(db_conn)[0]
        assert updated_source["last_scraped_at"] is not None


class TestTranscriptOperations:
    """Test transcript database operations."""
    
    def test_save_transcript(self, db_conn, sample_video_data, sample_transcript_data):
        """Test saving transcript data."""
        # First create a video
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        # Save transcript
        transcript_id = save_transcript(
            db_conn,
            video_id,
            sample_transcript_data["raw_text"],
            sample_transcript_data["segments"],
            sample_transcript_data["language"],
            sample_transcript_data["is_auto_generated"]
        )
        assert transcript_id is not None
        
        # Retrieve transcript
        transcript = get_transcript_for_video(db_conn, video_id)
        assert transcript is not None
        assert transcript["raw_text"] == sample_transcript_data["raw_text"]
        assert transcript["language"] == sample_transcript_data["language"]
        assert transcript["is_auto_generated"] == sample_transcript_data["is_auto_generated"]
        
        import json
        segments = json.loads(transcript["segments_json"])
        assert len(segments) == len(sample_transcript_data["segments"])


class TestJobQueue:
    """Test job queue database operations."""
    
    def test_enqueue_job(self, db_conn, sample_video_data):
        """Test enqueueing a job."""
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        job_id = enqueue_job(db_conn, video_id, "scrape", "test payload")
        assert job_id is not None
        
        jobs = list_jobs(db_conn)
        assert len(jobs) == 1
        assert jobs[0]["video_id"] == video_id
        assert jobs[0]["job_type"] == "scrape"
        assert jobs[0]["status"] == "pending"
        assert jobs[0]["payload"] == "test payload"
    
    def test_claim_next_job(self, db_conn, sample_video_data):
        """Test claiming the next pending job."""
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        job_id = enqueue_job(db_conn, video_id, "scrape")
        
        # Claim the job
        claimed_job = claim_next_job(db_conn)
        assert claimed_job is not None
        assert claimed_job["id"] == job_id
        assert claimed_job["status"] == "pending"  # Status in result is old
        
        # Verify status was updated in database
        jobs = list_jobs(db_conn)
        assert jobs[0]["status"] == "running"
        
        # Should not be able to claim again
        no_job = claim_next_job(db_conn)
        assert no_job is None
    
    def test_finish_job(self, db_conn, sample_video_data):
        """Test finishing a job successfully."""
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        job_id = enqueue_job(db_conn, video_id, "scrape")
        
        finish_job(db_conn, job_id, "done")
        
        jobs = list_jobs(db_conn)
        assert jobs[0]["status"] == "done"
        assert jobs[0]["error"] is None
    
    def test_fail_job(self, db_conn, sample_video_data):
        """Test failing a job with error message."""
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        job_id = enqueue_job(db_conn, video_id, "scrape")
        
        fail_job(db_conn, job_id, "Test error message")
        
        jobs = list_jobs(db_conn)
        assert jobs[0]["status"] == "failed"
        assert jobs[0]["error"] == "Test error message"
    
    def test_reset_stuck_jobs(self, db_conn, sample_video_data):
        """Test resetting stuck running jobs."""
        video_id = upsert_video(
            db_conn,
            sample_video_data["youtube_id"],
            sample_video_data["title"],
            sample_video_data["channel"],
            sample_video_data["url"]
        )
        
        job_id = enqueue_job(db_conn, video_id, "scrape")
        
        # Manually set status to running (simulate stuck job)
        db_conn.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (job_id,))
        
        reset_count = reset_stuck_jobs(db_conn)
        assert reset_count == 1
        
        jobs = list_jobs(db_conn)
        assert jobs[0]["status"] == "pending"


class TestArticleOperations:
    """Test article database operations."""
    
    def test_create_article(self, db_conn, sample_article_data):
        """Test creating a new article."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        assert article_id is not None
        
        article = get_article(db_conn, article_id)
        assert article is not None
        assert article["title"] == sample_article_data["title"]
        assert article["slug"] == sample_article_data["slug"]
        assert article["content_markdown"] == sample_article_data["content_markdown"]
        assert article["category"] == sample_article_data["category"]
        assert article["status"] == sample_article_data["status"]
    
    def test_get_article_by_slug(self, db_conn, sample_article_data):
        """Test retrieving article by slug."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        
        article = get_article_by_slug(db_conn, sample_article_data["slug"])
        assert article is not None
        assert article["id"] == article_id
        assert article["title"] == sample_article_data["title"]
    
    def test_update_article(self, db_conn, sample_article_data):
        """Test updating article fields."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        
        update_article(db_conn, article_id, title="Updated Title", category="updated")
        
        article = get_article(db_conn, article_id)
        assert article["title"] == "Updated Title"
        assert article["category"] == "updated"
        assert article["content_markdown"] == sample_article_data["content_markdown"]  # Unchanged
    
    def test_set_article_status(self, db_conn, sample_article_data):
        """Test updating article status."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        
        set_article_status(db_conn, article_id, "published")
        
        article = get_article(db_conn, article_id)
        assert article["status"] == "published"
    
    def test_delete_article(self, db_conn, sample_article_data):
        """Test deleting an article."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        
        # Add some tags first
        set_article_tags(db_conn, article_id, ["tag1", "tag2"])
        
        delete_article(db_conn, article_id)
        
        # Article should be gone
        article = get_article(db_conn, article_id)
        assert article is None
        
        # Tags relationship should also be cleaned up
        tags = get_article_tags(db_conn, article_id)
        assert len(tags) == 0
    
    def test_list_articles_with_filters(self, db_conn):
        """Test listing articles with various filters."""
        # Create test articles
        create_article(
            db_conn, video_id=None, title="Article 1", slug="article-1",
            content_markdown="Content 1", category="category1", status="draft"
        )
        create_article(
            db_conn, video_id=None, title="Article 2", slug="article-2",
            content_markdown="Content 2", category="category2", status="published"
        )
        create_article(
            db_conn, video_id=None, title="Article 3", slug="article-3",
            content_markdown="Content 3", category="category1", status="published"
        )
        
        # Test status filter
        published = list_articles(db_conn, status="published")
        assert len(published) == 2
        
        # Test category filter
        cat1 = list_articles(db_conn, category="category1")
        assert len(cat1) == 2
        
        # Test combined filters
        pub_cat1 = list_articles(db_conn, status="published", category="category1")
        assert len(pub_cat1) == 1
        assert pub_cat1[0]["title"] == "Article 3"


class TestTagOperations:
    """Test tag database operations."""
    
    def test_set_article_tags(self, db_conn, sample_article_data):
        """Test setting tags for an article."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        
        tags = ["automotive", "diagnostic", "honda"]
        set_article_tags(db_conn, article_id, tags)
        
        retrieved_tags = get_article_tags(db_conn, article_id)
        assert set(retrieved_tags) == set(tags)
    
    def test_update_article_tags(self, db_conn, sample_article_data):
        """Test updating existing tags."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        
        # Set initial tags
        set_article_tags(db_conn, article_id, ["tag1", "tag2"])
        
        # Update with different tags
        set_article_tags(db_conn, article_id, ["tag2", "tag3", "tag4"])
        
        retrieved_tags = get_article_tags(db_conn, article_id)
        assert set(retrieved_tags) == {"tag2", "tag3", "tag4"}
    
    def test_empty_tags(self, db_conn, sample_article_data):
        """Test handling empty or whitespace-only tags."""
        article_id = create_article(db_conn, video_id=None, **sample_article_data)
        
        # Set tags with empty strings and whitespace
        set_article_tags(db_conn, article_id, ["tag1", "", "  ", "tag2", "   tag3   "])
        
        retrieved_tags = get_article_tags(db_conn, article_id)
        assert set(retrieved_tags) == {"tag1", "tag2", "tag3"}


class TestFullTextSearch:
    """Test FTS5 full-text search functionality."""
    
    def test_fts_query_sanitization(self):
        """Test FTS query sanitization."""
        # Normal text
        assert _fts_query("hello world") == '"hello"* OR "world"*'
        
        # With special characters that should be stripped
        assert _fts_query("hello! @world #test") == '"hello"* OR "world"* OR "test"*'
        
        # Empty string
        assert _fts_query("") == "*"
        assert _fts_query("   ") == "*"
        
        # Only special characters
        assert _fts_query("!@#$%^&*()") == "*"
    
    def test_search_articles(self, db_conn):
        """Test full-text search of articles."""
        # Create test articles
        article1_id = create_article(
            db_conn, video_id=None, title="Honda Civic Repair", slug="honda-civic-repair",
            content_markdown="This is about Honda Civic engine problems and solutions.",
            category="automotive", status="published"
        )
        
        article2_id = create_article(
            db_conn, video_id=None, title="Toyota Maintenance", slug="toyota-maintenance",
            content_markdown="Toyota maintenance tips and tricks for better performance.",
            category="automotive", status="published"
        )
        
        article3_id = create_article(
            db_conn, video_id=None, title="BMW Diagnostic", slug="bmw-diagnostic",
            content_markdown="BMW diagnostic procedures and error codes.",
            category="diagnostic", status="draft"
        )
        
        # Sync articles to FTS
        sync_article_to_fts(db_conn, article1_id)
        sync_article_to_fts(db_conn, article2_id)
        sync_article_to_fts(db_conn, article3_id)
        
        # Test basic search
        results, total = search_articles(db_conn, "Honda")
        assert total == 1
        assert results[0]["id"] == article1_id
        
        # Test search with multiple terms
        results, total = search_articles(db_conn, "Honda engine")
        assert total == 1
        assert results[0]["id"] == article1_id
        
        # Test category filter
        results, total = search_articles(db_conn, "diagnostic", category="diagnostic")
        assert total == 1
        assert results[0]["id"] == article3_id
        
        # Test search across multiple articles
        results, total = search_articles(db_conn, "maintenance")
        assert total == 1
        assert results[0]["id"] == article2_id