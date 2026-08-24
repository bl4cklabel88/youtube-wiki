"""Wiki domain models: Article, Category, Tag — thin wrappers over DB rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..database import (
    get_article,
    get_article_by_slug,
    get_article_tags,
    get_conn,
    list_articles,
    list_categories,
    list_channels,
    list_tags,
    set_article_status,
    set_article_tags,
    update_article,
)


@dataclass
class Article:
    id: int
    video_id: Optional[int]
    title: str
    slug: str
    content_markdown: str
    category: Optional[str] = None
    source_channel: Optional[str] = None
    source_url: Optional[str] = None
    dtc_codes: list[str] = field(default_factory=list)
    vehicle_refs: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: str = "draft"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Article":
        return cls(
            id=row["id"],
            video_id=row["video_id"],
            title=row["title"],
            slug=row["slug"],
            content_markdown=row["content_markdown"],
            category=row["category"],
            source_channel=row["source_channel"],
            source_url=row["source_url"],
            dtc_codes=_csv(row["dtc_codes"]),
            vehicle_refs=_csv(row["vehicle_refs"]),
            tools_used=_csv(row["tools_used"]),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def get(article_id: int) -> Optional["Article"]:
        with get_conn() as conn:
            row = get_article(conn, article_id)
            if not row:
                return None
            art = Article.from_row(row)
            art.tags = get_article_tags(conn, article_id)
            return art

    @staticmethod
    def get_by_slug(slug: str) -> Optional["Article"]:
        with get_conn() as conn:
            row = get_article_by_slug(conn, slug)
            if not row:
                return None
            art = Article.from_row(row)
            art.tags = get_article_tags(conn, article_id=row["id"])
            return art

    @staticmethod
    def list(*, status: Optional[str] = None, category: Optional[str] = None,
             channel: Optional[str] = None, tag: Optional[str] = None,
             limit: int = 100, offset: int = 0) -> list["Article"]:
        with get_conn() as conn:
            rows = list_articles(conn, status=status, category=category, channel=channel,
                                 tag=tag, limit=limit, offset=offset)
            return [Article.from_row(r) for r in rows]

    def save(self) -> None:
        with get_conn() as conn:
            update_article(conn, self.id,
                           title=self.title, slug=self.slug,
                           content_markdown=self.content_markdown,
                           category=self.category, source_channel=self.source_channel,
                           source_url=self.source_url,
                           dtc_codes=",".join(self.dtc_codes),
                           vehicle_refs=",".join(self.vehicle_refs),
                           tools_used=",".join(self.tools_used),
                           status=self.status)
            set_article_tags(conn, self.id, self.tags)
            from ..database import sync_article_to_fts
            sync_article_to_fts(conn, self.id)

    def publish(self) -> None:
        with get_conn() as conn:
            set_article_status(conn, self.id, "published")
        self.status = "published"

    def unpublish(self) -> None:
        with get_conn() as conn:
            set_article_status(conn, self.id, "draft")
        self.status = "draft"


def _csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass
class Category:
    name: str
    count: int = 0

    @staticmethod
    def list() -> list["Category"]:
        with get_conn() as conn:
            return [Category(r["category"], r["count"]) for r in list_categories(conn)]


@dataclass
class Channel:
    name: str
    count: int = 0

    @staticmethod
    def list() -> list["Channel"]:
        with get_conn() as conn:
            return [Channel(r["channel"], r["count"]) for r in list_channels(conn)]


@dataclass
class Tag:
    name: str
    count: int = 0

    @staticmethod
    def list() -> list["Tag"]:
        with get_conn() as conn:
            return [Tag(r["name"], r["count"]) for r in list_tags(conn)]
