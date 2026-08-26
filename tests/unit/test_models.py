"""Unit tests for wiki models."""
import pytest
from unittest.mock import patch, Mock
from app.wiki.models import Article, Category, Channel, Tag, _csv


class TestArticleModel:
    """Test Article model functionality."""
    
    def test_article_from_row(self):
        """Test creating Article instance from database row."""
        mock_row = {
            "id": 1,
            "video_id": 123,
            "title": "Test Article",
            "slug": "test-article",
            "content_markdown": "# Test\nContent",
            "category": "automotive",
            "source_channel": "Test Channel",
            "source_url": "https://youtube.com/watch?v=test",
            "dtc_codes": "P0123,P0456",
            "vehicle_refs": "Honda Civic,Toyota Corolla",
            "tools_used": "OBD scanner,Multimeter",
            "status": "published",
            "created_at": "2023-01-01T00:00:00",
            "updated_at": "2023-01-02T00:00:00"
        }
        
        article = Article.from_row(mock_row)
        
        assert article.id == 1
        assert article.video_id == 123
        assert article.title == "Test Article"
        assert article.slug == "test-article"
        assert article.content_markdown == "# Test\nContent"
        assert article.category == "automotive"
        assert article.source_channel == "Test Channel"
        assert article.source_url == "https://youtube.com/watch?v=test"
        assert article.dtc_codes == ["P0123", "P0456"]
        assert article.vehicle_refs == ["Honda Civic", "Toyota Corolla"]
        assert article.tools_used == ["OBD scanner", "Multimeter"]
        assert article.status == "published"
        assert article.created_at == "2023-01-01T00:00:00"
        assert article.updated_at == "2023-01-02T00:00:00"
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.get_article')
    @patch('app.wiki.models.get_article_tags')
    def test_article_get(self, mock_get_tags, mock_get_article, mock_get_conn):
        """Test Article.get() class method."""
        # Mock database connection
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        # Mock database row
        mock_row = {
            "id": 1, "video_id": None, "title": "Test", "slug": "test",
            "content_markdown": "Content", "category": None, "source_channel": None,
            "source_url": None, "dtc_codes": None, "vehicle_refs": None,
            "tools_used": None, "status": "draft", "created_at": None, "updated_at": None
        }
        mock_get_article.return_value = mock_row
        mock_get_tags.return_value = ["tag1", "tag2"]
        
        article = Article.get(1)
        
        assert article is not None
        assert article.id == 1
        assert article.tags == ["tag1", "tag2"]
        mock_get_article.assert_called_once_with(mock_conn, 1)
        mock_get_tags.assert_called_once_with(mock_conn, 1)
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.get_article')
    def test_article_get_not_found(self, mock_get_article, mock_get_conn):
        """Test Article.get() when article doesn't exist."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_get_article.return_value = None
        
        article = Article.get(999)
        
        assert article is None
        mock_get_article.assert_called_once_with(mock_conn, 999)
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.get_article_by_slug')
    @patch('app.wiki.models.get_article_tags')
    def test_article_get_by_slug(self, mock_get_tags, mock_get_article_by_slug, mock_get_conn):
        """Test Article.get_by_slug() class method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        mock_row = {
            "id": 1, "video_id": None, "title": "Test", "slug": "test-slug",
            "content_markdown": "Content", "category": None, "source_channel": None,
            "source_url": None, "dtc_codes": None, "vehicle_refs": None,
            "tools_used": None, "status": "draft", "created_at": None, "updated_at": None
        }
        mock_get_article_by_slug.return_value = mock_row
        mock_get_tags.return_value = []
        
        article = Article.get_by_slug("test-slug")
        
        assert article is not None
        assert article.slug == "test-slug"
        mock_get_article_by_slug.assert_called_once_with(mock_conn, "test-slug")
        mock_get_tags.assert_called_once_with(mock_conn, article_id=1)
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.list_articles')
    def test_article_list(self, mock_list_articles, mock_get_conn):
        """Test Article.list() class method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        mock_rows = [
            {
                "id": 1, "video_id": None, "title": "Article 1", "slug": "article-1",
                "content_markdown": "Content 1", "category": "cat1", "source_channel": None,
                "source_url": None, "dtc_codes": None, "vehicle_refs": None,
                "tools_used": None, "status": "published", "created_at": None, "updated_at": None
            },
            {
                "id": 2, "video_id": None, "title": "Article 2", "slug": "article-2",
                "content_markdown": "Content 2", "category": "cat2", "source_channel": None,
                "source_url": None, "dtc_codes": None, "vehicle_refs": None,
                "tools_used": None, "status": "draft", "created_at": None, "updated_at": None
            }
        ]
        mock_list_articles.return_value = mock_rows
        
        articles = Article.list(status="published", limit=10)
        
        assert len(articles) == 2
        assert articles[0].title == "Article 1"
        assert articles[1].title == "Article 2"
        mock_list_articles.assert_called_once_with(
            mock_conn, status="published", category=None, channel=None,
            tag=None, limit=10, offset=0
        )
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.update_article')
    @patch('app.wiki.models.set_article_tags')
    @patch('app.database.sync_article_to_fts')
    def test_article_save(self, mock_sync_fts, mock_set_tags, mock_update, mock_get_conn):
        """Test Article.save() method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        article = Article(
            id=1, video_id=None, title="Updated Title", slug="updated-slug",
            content_markdown="Updated content", category="updated_cat",
            source_channel="Updated Channel", source_url="https://example.com",
            dtc_codes=["P0001", "P0002"], vehicle_refs=["Car A", "Car B"],
            tools_used=["Tool 1", "Tool 2"], tags=["tag1", "tag2"],
            status="published"
        )
        
        article.save()
        
        mock_update.assert_called_once_with(
            mock_conn, 1,
            title="Updated Title", slug="updated-slug",
            content_markdown="Updated content", category="updated_cat",
            source_channel="Updated Channel", source_url="https://example.com",
            dtc_codes="P0001,P0002", vehicle_refs="Car A,Car B",
            tools_used="Tool 1,Tool 2", status="published"
        )
        mock_set_tags.assert_called_once_with(mock_conn, 1, ["tag1", "tag2"])
        mock_sync_fts.assert_called_once_with(mock_conn, 1)
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.set_article_status')
    def test_article_publish(self, mock_set_status, mock_get_conn):
        """Test Article.publish() method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        article = Article(
            id=1, video_id=None, title="Test", slug="test",
            content_markdown="Content", status="draft"
        )
        
        article.publish()
        
        assert article.status == "published"
        mock_set_status.assert_called_once_with(mock_conn, 1, "published")
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.set_article_status')
    def test_article_unpublish(self, mock_set_status, mock_get_conn):
        """Test Article.unpublish() method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        article = Article(
            id=1, video_id=None, title="Test", slug="test",
            content_markdown="Content", status="published"
        )
        
        article.unpublish()
        
        assert article.status == "draft"
        mock_set_status.assert_called_once_with(mock_conn, 1, "draft")


class TestCategoryModel:
    """Test Category model functionality."""
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.list_categories')
    def test_category_list(self, mock_list_categories, mock_get_conn):
        """Test Category.list() class method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        mock_rows = [
            {"category": "automotive", "count": 15},
            {"category": "diagnostic", "count": 8},
            {"category": "maintenance", "count": 12}
        ]
        mock_list_categories.return_value = mock_rows
        
        categories = Category.list()
        
        assert len(categories) == 3
        assert categories[0].name == "automotive"
        assert categories[0].count == 15
        assert categories[1].name == "diagnostic"
        assert categories[1].count == 8
        assert categories[2].name == "maintenance"
        assert categories[2].count == 12
        mock_list_categories.assert_called_once_with(mock_conn)


class TestChannelModel:
    """Test Channel model functionality."""
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.list_channels')
    def test_channel_list(self, mock_list_channels, mock_get_conn):
        """Test Channel.list() class method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        mock_rows = [
            {"channel": "AutoRepair Pro", "count": 25},
            {"channel": "CarTech Tips", "count": 18},
            {"channel": "Mechanic Mike", "count": 30}
        ]
        mock_list_channels.return_value = mock_rows
        
        channels = Channel.list()
        
        assert len(channels) == 3
        assert channels[0].name == "AutoRepair Pro"
        assert channels[0].count == 25
        assert channels[1].name == "CarTech Tips"
        assert channels[1].count == 18
        assert channels[2].name == "Mechanic Mike"
        assert channels[2].count == 30
        mock_list_channels.assert_called_once_with(mock_conn)


class TestTagModel:
    """Test Tag model functionality."""
    
    @patch('app.wiki.models.get_conn')
    @patch('app.wiki.models.list_tags')
    def test_tag_list(self, mock_list_tags, mock_get_conn):
        """Test Tag.list() class method."""
        mock_conn = Mock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        
        mock_rows = [
            {"name": "honda", "count": 10},
            {"name": "toyota", "count": 8},
            {"name": "diagnostic", "count": 15}
        ]
        mock_list_tags.return_value = mock_rows
        
        tags = Tag.list()
        
        assert len(tags) == 3
        assert tags[0].name == "honda"
        assert tags[0].count == 10
        assert tags[1].name == "toyota"
        assert tags[1].count == 8
        assert tags[2].name == "diagnostic"
        assert tags[2].count == 15
        mock_list_tags.assert_called_once_with(mock_conn)


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_csv_parsing(self):
        """Test _csv function for parsing CSV strings."""
        # Normal CSV string
        assert _csv("apple,banana,cherry") == ["apple", "banana", "cherry"]
        
        # CSV with spaces
        assert _csv("apple, banana , cherry ") == ["apple", "banana", "cherry"]
        
        # Empty string
        assert _csv("") == []
        assert _csv(None) == []
        
        # Single item
        assert _csv("apple") == ["apple"]
        
        # Empty items (should be filtered out)
        assert _csv("apple,,banana,") == ["apple", "banana"]
        
        # Only commas and spaces
        assert _csv(", , ,") == []
        
        # Mixed with empty items
        assert _csv("apple, , banana, ,cherry") == ["apple", "banana", "cherry"]