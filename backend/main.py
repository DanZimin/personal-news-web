import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

DB_PATH = Path("/app/data/news.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
USER_AGENT = "PersonalNewsAggregator/1.0"
TIMEOUT = 20

app = FastAPI(title="Personal News RSS API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Для личного прототипа. При публичном размещении ограничить доменом фронтенда.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                added_at TEXT NOT NULL,
                last_fetched_at TEXT,
                last_status TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                summary TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                UNIQUE(feed_id, url),
                FOREIGN KEY(feed_id) REFERENCES feeds(id)
            )
        """)


@app.on_event("startup")
def startup():
    init_db()


class FeedCreate(BaseModel):
    url: HttpUrl


def parse_feed(url: str):
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Не удалось прочитать RSS: {parsed.bozo_exception}")
    if not parsed.entries:
        raise ValueError("В ленте нет публикаций или формат не поддерживается.")
    return parsed


def parse_date(entry):
    for field in ("published", "updated", "created"):
        raw = entry.get(field)
        if raw:
            try:
                dt = date_parser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError):
                pass
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
            except (ValueError, TypeError, OverflowError):
                pass
    return None


def plain_text(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)


def save_entries(feed_id, entries):
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with connect() as conn:
        for entry in entries:
            link = (entry.get("link") or "").strip()
            if not link:
                continue
            title = (entry.get("title") or "(Без заголовка)").strip()
            summary = plain_text(entry.get("summary") or entry.get("description") or "")
            cursor = conn.execute("""
                INSERT OR IGNORE INTO articles
                (feed_id, title, url, summary, published_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (feed_id, title, link, summary, parse_date(entry), now))
            inserted += cursor.rowcount
    return inserted


def feed_dict(row):
    return dict(row)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/feeds")
def get_feeds():
    with connect() as conn:
        rows = conn.execute("""
            SELECT f.*, COUNT(a.id) AS article_count
            FROM feeds f LEFT JOIN articles a ON a.feed_id = f.id
            GROUP BY f.id ORDER BY f.title COLLATE NOCASE
        """).fetchall()
    return [feed_dict(row) for row in rows]


@app.post("/api/feeds", status_code=201)
def create_feed(payload: FeedCreate):
    url = str(payload.url)
    try:
        parsed = parse_feed(url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось загрузить ленту: {exc}")
    title = (parsed.feed.get("title") or "").strip() or url
    now = datetime.now(timezone.utc).isoformat()
    try:
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO feeds(url, title, added_at) VALUES (?, ?, ?)",
                (url, title, now),
            )
            feed_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Этот источник уже добавлен.")
    count = save_entries(feed_id, parsed.entries)
    with connect() as conn:
        conn.execute(
            "UPDATE feeds SET last_fetched_at=?, last_status=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), f"Добавлен; публикаций: {count}", feed_id),
        )
        row = conn.execute("""
            SELECT f.*, (SELECT COUNT(*) FROM articles WHERE feed_id=f.id) AS article_count
            FROM feeds f WHERE f.id=?
        """, (feed_id,)).fetchone()
    return feed_dict(row)


@app.delete("/api/feeds/{feed_id}")
def remove_feed(feed_id: int):
    with connect() as conn:
        exists = conn.execute("SELECT id FROM feeds WHERE id=?", (feed_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Источник не найден.")
        conn.execute("DELETE FROM articles WHERE feed_id=?", (feed_id,))
        conn.execute("DELETE FROM feeds WHERE id=?", (feed_id,))
    return {"deleted": True}


@app.post("/api/feeds/refresh")
def refresh_feeds():
    with connect() as conn:
        feeds = conn.execute("SELECT * FROM feeds ORDER BY title").fetchall()
    results = []
    for feed in feeds:
        try:
            parsed = parse_feed(feed["url"])
            count = save_entries(feed["id"], parsed.entries)
            status = f"OK; новых публикаций: {count}"
            error = None
        except Exception as exc:
            count = 0
            status = f"Ошибка: {exc}"
            error = str(exc)
        with connect() as conn:
            conn.execute(
                "UPDATE feeds SET last_fetched_at=?, last_status=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), status, feed["id"]),
            )
        results.append({"feed_id": feed["id"], "title": feed["title"], "new_articles": count, "error": error})
    return {"results": results, "new_articles": sum(x["new_articles"] for x in results)}


@app.get("/api/articles")
def get_articles(days: int = 7, feed_id: int | None = None):
    if days not in (1, 3, 7, 30, 90):
        raise HTTPException(status_code=400, detail="Допустимые периоды: 1, 3, 7, 30 или 90 дней.")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = """
        SELECT a.*, f.title AS feed_title
        FROM articles a JOIN feeds f ON f.id=a.feed_id
        WHERE (a.published_at IS NULL OR a.published_at >= ?)
    """
    params = [cutoff]
    if feed_id is not None:
        query += " AND a.feed_id=?"
        params.append(feed_id)
    query += " ORDER BY COALESCE(a.published_at, a.fetched_at) DESC LIMIT 500"
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
