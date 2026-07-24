"""Backend Postgres/Neon per lo store del motore ICH.

Implementa le stesse operazioni del backend JSON (vedi ich/store.py) su Postgres,
così lo stato del dispatcher è **durevole** anche sul disco effimero del cloud.

Modello dei dati — semplice e a prova d'espianto (ogni item è un JSONB opaco,
`pg_dump` porta via tutto in SQL standard):

  items(id PK, seq, data JSONB, updated_at)      -- ledger dei CanonicalItem
  outbox(channel, item_id, seq, data JSONB)       -- uscite per canale (PK channel+item_id)
  audit(seq PK, ts, event, item_id, title, source, actor, detail)
  queries(seq PK, ts, q, answered, categories JSONB)
  feed_sources(id PK, name, source, icon, type, kind, url, path,
               field_map JSONB, description, note, enabled, verified, created_at)

Dipendenza: psycopg (v3). La connessione è **per-operazione** (context manager):
a questa scala l'overhead è trascurabile e regge bene le disconnessioni del
serverless Neon. `prepare_threshold=None` disattiva i prepared statement
automatici, che darebbero problemi sul pooler PgBouncer di Neon.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         TEXT PRIMARY KEY,
    seq        BIGSERIAL,
    data       JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS outbox (
    channel TEXT NOT NULL,
    item_id TEXT NOT NULL,
    seq     BIGSERIAL,
    data    JSONB NOT NULL,
    PRIMARY KEY (channel, item_id)
);
CREATE TABLE IF NOT EXISTS audit (
    seq     BIGSERIAL PRIMARY KEY,
    ts      TEXT,
    event   TEXT,
    item_id TEXT,
    title   TEXT,
    source  TEXT,
    actor   TEXT,
    detail  TEXT
);
CREATE TABLE IF NOT EXISTS queries (
    seq        BIGSERIAL PRIMARY KEY,
    ts         TEXT,
    q          TEXT,
    answered   BOOLEAN,
    categories JSONB
);
CREATE TABLE IF NOT EXISTS feed_sources (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    source      TEXT,
    icon        TEXT,
    type        TEXT,
    kind        TEXT,
    url         TEXT,
    path        TEXT,
    field_map   JSONB,
    description TEXT,
    note        TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    verified    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS topics (
    id   TEXT PRIMARY KEY,
    seq  BIGSERIAL,
    data JSONB NOT NULL
);
"""


class PgStore:
    def __init__(self, url: str):
        self.url = url

    def _conn(self):
        # prepare_threshold=None: niente prepared statement (compat. pooler Neon).
        return psycopg.connect(self.url, autocommit=False, prepare_threshold=None)

    def ensure_schema(self) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(_SCHEMA)

    # ─── items ────────────────────────────────────────────────────────────────
    def load_items(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT data FROM items ORDER BY seq")
            return [row[0] for row in cur.fetchall()]

    def get_item(self, item_id: str) -> dict | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT data FROM items WHERE id = %s", (item_id,))
            row = cur.fetchone()
            return row[0] if row else None

    def upsert_item(self, item: dict) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO items (id, data) VALUES (%s, %s) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                (item.get("id"), Jsonb(item)),
            )

    def save_items(self, items: list[dict]) -> None:
        """Sostituzione completa del ledger (usata di rado; l' order è preservato
        dall'ordine d'inserimento)."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE items")
            for it in items:
                cur.execute("INSERT INTO items (id, data) VALUES (%s, %s)",
                            (it.get("id"), Jsonb(it)))

    # ─── outbox ───────────────────────────────────────────────────────────────
    def load_outbox(self, channel: str) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT data FROM outbox WHERE channel = %s ORDER BY seq",
                        (channel,))
            return [row[0] for row in cur.fetchall()]

    def save_outbox(self, channel: str, entries: list[dict]) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM outbox WHERE channel = %s", (channel,))
            for e in entries:
                cur.execute(
                    "INSERT INTO outbox (channel, item_id, data) VALUES (%s, %s, %s) "
                    "ON CONFLICT (channel, item_id) DO UPDATE SET data = EXCLUDED.data",
                    (channel, str(e.get("id")), Jsonb(e)),
                )

    # ─── audit ────────────────────────────────────────────────────────────────
    def append_audit(self, entry: dict) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit (ts, event, item_id, title, source, actor, detail) "
                "VALUES (%(ts)s, %(event)s, %(item_id)s, %(title)s, %(source)s, %(actor)s, %(detail)s)",
                entry,
            )

    def load_audit(self, limit: int | None = None) -> list[dict]:
        sql = ("SELECT ts, event, item_id, title, source, actor, detail "
               "FROM audit ORDER BY seq DESC")
        params: tuple = ()
        if limit:
            sql += " LIMIT %s"
            params = (limit,)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            cols = ("ts", "event", "item_id", "title", "source", "actor", "detail")
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ─── queries ──────────────────────────────────────────────────────────────
    def append_query(self, entry: dict) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO queries (ts, q, answered, categories) "
                "VALUES (%s, %s, %s, %s)",
                (entry.get("ts"), entry.get("q"), entry.get("answered"),
                 Jsonb(entry.get("categories") or [])),
            )

    def load_queries(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT ts, q, answered, categories FROM queries ORDER BY seq")
            cols = ("ts", "q", "answered", "categories")
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ─── feed_sources (Serbatoio 2 — config durevole) ─────────────────────────
    _FEED_COLS = ("id", "name", "source", "icon", "type", "kind", "url", "path",
                  "field_map", "description", "note", "enabled", "verified")

    def list_feed_sources(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, source, icon, type, kind, url, path, field_map, "
                "description, note, enabled, verified FROM feed_sources ORDER BY created_at"
            )
            return [dict(zip(self._FEED_COLS, row)) for row in cur.fetchall()]

    def upsert_feed_source(self, feed: dict) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO feed_sources "
                "(id, name, source, icon, type, kind, url, path, field_map, description, note, enabled, verified) "
                "VALUES (%(id)s, %(name)s, %(source)s, %(icon)s, %(type)s, %(kind)s, %(url)s, %(path)s, "
                "        %(field_map)s, %(description)s, %(note)s, %(enabled)s, %(verified)s) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  name=EXCLUDED.name, source=EXCLUDED.source, icon=EXCLUDED.icon, type=EXCLUDED.type, "
                "  kind=EXCLUDED.kind, url=EXCLUDED.url, path=EXCLUDED.path, field_map=EXCLUDED.field_map, "
                "  description=EXCLUDED.description, note=EXCLUDED.note, enabled=EXCLUDED.enabled, "
                "  verified=EXCLUDED.verified",
                {**feed, "field_map": Jsonb(feed.get("field_map") or {})},
            )

    def set_feed_enabled(self, feed_id: str, enabled: bool) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE feed_sources SET enabled = %s WHERE id = %s",
                        (enabled, feed_id))

    def delete_feed_source(self, feed_id: str) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM feed_sources WHERE id = %s", (feed_id,))

    def count_feed_sources(self) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM feed_sources")
            return cur.fetchone()[0]

    # ─── topics (argomenti editoriali — Fase 1/2) ─────────────────────────────
    def list_topics(self) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT data FROM topics ORDER BY seq")
            return [row[0] for row in cur.fetchall()]

    def save_topics(self, topics: list[dict]) -> None:
        """Sostituzione completa (gli argomenti si editano come insieme in UI)."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE topics")
            for t in topics:
                cur.execute("INSERT INTO topics (id, data) VALUES (%s, %s)",
                            (t.get("id"), Jsonb(t)))

    def count_topics(self) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM topics")
            return cur.fetchone()[0]
