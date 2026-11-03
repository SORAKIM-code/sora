"""SQLite 저장소. 카탈로그·권한·세션·감사로그·신고를 보관한다."""
import json
import sqlite3
import threading

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, name TEXT, org TEXT, role TEXT, department TEXT,
  pw_salt TEXT, pw_hash TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS grants(
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT, subject_id TEXT, purpose TEXT,
  levels TEXT, domains TEXT, valid_from TEXT, valid_to TEXT,
  revoked_at TEXT, revoked_by TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id TEXT, purpose TEXT, created_at TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS catalog_versions(
  catalog_id TEXT, version INTEGER, status TEXT, data TEXT, source_text TEXT,
  created_by TEXT, created_at TEXT, reviewed_by TEXT, reviewed_at TEXT, note TEXT,
  PRIMARY KEY(catalog_id, version));
CREATE TABLE IF NOT EXISTS audit_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user_id TEXT, purpose TEXT, event TEXT,
  query_text TEXT, query_hash TEXT, evidence TEXT, permission TEXT, model TEXT,
  outcome TEXT, flags TEXT);
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user_id TEXT, catalog_id TEXT, version INTEGER,
  field TEXT, message TEXT, status TEXT DEFAULT 'open', resolution TEXT,
  resolved_by TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS login_failures(username TEXT PRIMARY KEY, count INTEGER, last_at TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def run(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def get_meta(self, key, default=None):
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_meta(self, key, value):
        self.run("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))

    def bump_generation(self):
        """카탈로그·권한이 바뀔 때마다 올린다. 검색 인덱스와 결과 캐시의 키에 들어간다."""
        with self.lock:
            g = self.get_meta("generation", 0) + 1
            self.set_meta("generation", g)
            return g

    def generation(self):
        return self.get_meta("generation", 0)
