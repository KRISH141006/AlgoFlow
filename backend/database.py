"""SQLite connections and repeatable, additive schema upgrades."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def database_path():
    return Path(os.environ.get('ALGOFLOW_DB', str(ROOT / 'data/demo.db')))


def identity_from_link(link):
    parsed = urlparse(link)
    host = (parsed.hostname or '').lower()
    platform = 'leetcode' if host == 'leetcode.com' or host.endswith('.leetcode.com') else 'gfg' if host == 'geeksforgeeks.org' or host.endswith('.geeksforgeeks.org') else 'manual'
    parts = parsed.path.strip('/').split('/')
    slug = parts[parts.index('problems') + 1] if 'problems' in parts and len(parts) > parts.index('problems') + 1 else None
    return platform, slug


@contextmanager
def connection(write=False):
    db = sqlite3.connect(database_path(), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def migrate():
    database_path().parent.mkdir(parents=True, exist_ok=True)
    with connection(write=True) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            difficulty TEXT NOT NULL, link TEXT NOT NULL, date_added TEXT NOT NULL,
            stage INTEGER NOT NULL DEFAULT 0, next_review_date TEXT,
            status TEXT NOT NULL DEFAULT 'pending')''')
        db.execute('''CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'General', notes TEXT DEFAULT '', link TEXT DEFAULT '',
            date_added TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
            next_review_date TEXT, status TEXT NOT NULL DEFAULT 'pending')''')
        for table, parent in [('review_history', 'problem'), ('topic_review_history', 'topic')]:
            db.execute(f'''CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT, {parent}_id INTEGER NOT NULL REFERENCES {parent + 's'}(id),
                review_date TEXT NOT NULL, stage_completed INTEGER NOT NULL, was_on_time INTEGER NOT NULL)''')
        existing = {row['name'] for row in db.execute('PRAGMA table_info(problems)')}
        additions = {'platform': "TEXT NOT NULL DEFAULT 'manual'", 'slug': 'TEXT',
                     'platform_id': 'TEXT', 'topic_tags': "TEXT NOT NULL DEFAULT '[]'",
                     'company_tags': "TEXT NOT NULL DEFAULT '[]'", 'problem_html': "TEXT NOT NULL DEFAULT ''",
                     'imported_at': 'TEXT', 'historical_import': 'INTEGER NOT NULL DEFAULT 0', 'solved_at': 'TEXT', 'solve_state': "TEXT NOT NULL DEFAULT 'unverified'"}
        for name, definition in additions.items():
            if name not in existing:
                db.execute(f'ALTER TABLE problems ADD COLUMN {name} {definition}')
                if name == 'historical_import':
                    db.execute('UPDATE problems SET historical_import=1 WHERE imported_at IS NOT NULL')
        for row in db.execute("SELECT id, link FROM problems WHERE platform='manual' AND slug IS NULL").fetchall():
            platform, slug = identity_from_link(row['link'])
            if slug:
                db.execute('UPDATE problems SET platform=?,slug=? WHERE id=?', (platform, slug, row['id']))
        db.execute('CREATE INDEX IF NOT EXISTS problems_identity ON problems(platform,slug)')
        db.execute('''CREATE TABLE IF NOT EXISTS problem_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, problem_id INTEGER NOT NULL REFERENCES problems(id),
            version_number INTEGER NOT NULL, commit_message TEXT NOT NULL, code TEXT NOT NULL,
            language TEXT NOT NULL, what_is_good TEXT NOT NULL DEFAULT '', what_is_bad TEXT NOT NULL DEFAULT '',
            time_complexity TEXT NOT NULL DEFAULT '', space_complexity TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL,
            submission_id TEXT, fingerprint TEXT NOT NULL, delivery_key TEXT NOT NULL,
            UNIQUE(problem_id,version_number), UNIQUE(problem_id,delivery_key))''')
        db.execute('PRAGMA user_version = 2')
