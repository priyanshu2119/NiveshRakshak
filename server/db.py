"""SQLite storage: registry mirror, verdict audit log, response cache, metadata.

Privacy posture (documented in README):
  - raw user messages and uploaded images are NEVER persisted
  - audit rows keep only extracted identifiers needed for auditability:
    UPI handles in full (they are payment destinations, quasi-public),
    bank accounts as sha256 prefix + last4, phone numbers as last4
  - rows auto-purge after RETENTION_DAYS
"""
import hashlib
import json
import os
import sqlite3
import threading
import time

DB_PATH = os.environ.get("NR_DB", os.path.join(os.path.dirname(__file__), "..", "data", "nr.sqlite"))
RETENTION_DAYS = int(os.environ.get("NR_RETENTION_DAYS", "90"))

_local = threading.local()


def conn() -> sqlite3.Connection:
    """One connection per thread (sqlite3 objects are thread-affine by default)."""
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=15)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.row_factory = sqlite3.Row
        _local.conn = c
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS registry (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    trade_name TEXT,
    reg_no TEXT,
    reg_no_norm TEXT,
    type TEXT,
    category_id INTEGER,
    validity TEXT,
    exchange TEXT,
    imported_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_name_norm ON registry(name_norm);
CREATE INDEX IF NOT EXISTS idx_registry_regno ON registry(reg_no_norm);

CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    upi TEXT,
    account_ref TEXT,
    claimed_name TEXT,
    claimed_regno TEXT,
    headline TEXT NOT NULL,
    primary_json TEXT,
    registry_json TEXT,
    redflag_ids TEXT,
    sebi_txn TEXT,
    sources_json TEXT,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_checks_ts ON checks(ts);

CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
    purge_old()


def purge_old() -> int:
    cutoff = int(time.time()) - RETENTION_DAYS * 86400
    with conn() as c:
        cur = c.execute("DELETE FROM checks WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM cache WHERE fetched_at < ?", (cutoff,))
        return cur.rowcount


# --- meta helpers -----------------------------------------------------------

def meta_get(key: str, default=None):
    row = conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(key: str, value) -> None:
    with conn() as c:
        c.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# --- cache helpers ----------------------------------------------------------

def cache_get(key: str, ttl_sec: int):
    row = conn().execute("SELECT response, fetched_at FROM cache WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    if time.time() - row["fetched_at"] > ttl_sec:
        return None
    return json.loads(row["response"])


def cache_set(key: str, response: dict) -> None:
    with conn() as c:
        c.execute("INSERT INTO cache(key,response,fetched_at) VALUES(?,?,?) "
                  "ON CONFLICT(key) DO UPDATE SET response=excluded.response, "
                  "fetched_at=excluded.fetched_at",
                  (key, json.dumps(response, ensure_ascii=False), int(time.time())))


# --- audit helpers ----------------------------------------------------------

def mask_account(acc: str) -> str:
    """Privacy-preserving account reference: sha256 prefix + last4."""
    if not acc:
        return ""
    return hashlib.sha256(acc.encode()).hexdigest()[:12] + "…" + acc[-4:]


def mask_phone(phone: str) -> str:
    return "••••" + phone[-4:] if phone else ""


def log_check(row: dict) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO checks(ts,upi,account_ref,claimed_name,claimed_regno,headline,"
            "primary_json,registry_json,redflag_ids,sebi_txn,sources_json,duration_ms) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (int(time.time()), row.get("upi"), row.get("account_ref"),
             row.get("claimed_name"), row.get("claimed_regno"), row["headline"],
             json.dumps(row.get("primary"), ensure_ascii=False),
             json.dumps(row.get("registry"), ensure_ascii=False),
             ",".join(row.get("redflag_ids", [])), row.get("sebi_txn"),
             json.dumps(row.get("sources"), ensure_ascii=False), row.get("duration_ms")),
        )
        return cur.lastrowid


def total_checks() -> int:
    return conn().execute("SELECT COUNT(*) n FROM checks").fetchone()["n"]


# --- registry mirror helpers ------------------------------------------------

def registry_count() -> int:
    return conn().execute("SELECT COUNT(*) n FROM registry").fetchone()["n"]


def registry_replace_rows(category_id: int, rows: list[dict]) -> int:
    """Atomically replace one category's rows. rows: dicts with name/trade/reg/type/..."""
    now = int(time.time())
    with conn() as c:
        c.execute("DELETE FROM registry WHERE category_id=?", (category_id,))
        c.executemany(
            "INSERT INTO registry(name,name_norm,trade_name,reg_no,reg_no_norm,type,"
            "category_id,validity,exchange,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(r["name"], r["name_norm"], r.get("trade_name"), r.get("reg_no"),
              r.get("reg_no_norm"), r.get("type"), category_id, r.get("validity"),
              r.get("exchange"), now) for r in rows],
        )
    return len(rows)


def registry_all_names() -> list[tuple[int, str, str]]:
    """(id, name_norm, reg_no_norm) for fuzzy matching — loaded into memory."""
    return [(r["id"], r["name_norm"], r["reg_no_norm"] or "")
            for r in conn().execute("SELECT id,name_norm,reg_no_norm FROM registry")]


def registry_rows_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    q = ",".join("?" * len(ids))
    return [dict(r) for r in conn().execute(
        f"SELECT name,trade_name,reg_no,type,validity,exchange FROM registry WHERE id IN ({q})", ids)]
