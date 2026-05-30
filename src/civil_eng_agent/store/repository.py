"""SQLite repository — all DB access goes through here."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Per-thread connection cache: db_path -> connection
_local = threading.local()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False is safe here because each thread gets its own
    # connection via _local; WAL mode allows concurrent readers.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _get_thread_conn(db_path: Path) -> sqlite3.Connection:
    """Return a connection for the current thread, creating one if needed."""
    key = str(db_path)
    cache: dict = getattr(_local, "conns", None) or {}
    if not hasattr(_local, "conns"):
        _local.conns = cache
    if key not in cache:
        cache[key] = _connect(db_path)
    return cache[key]


def init_db(db_path: Path) -> None:
    """Create schema and optional vec table on the calling thread's connection."""
    conn = _get_thread_conn(db_path)
    sql = SCHEMA_PATH.read_text()
    conn.executescript(sql)
    try:
        conn.enable_load_extension(True)
        conn.load_extension("vec0")
        _init_vec_table(conn)
    except Exception:
        pass
    conn.commit()


def _init_vec_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_embeddings
        USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[1024])
        """
    )


class Repository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        init_db(db_path)

    @property
    def _conn(self) -> sqlite3.Connection:
        """Always return the connection for the current thread."""
        return _get_thread_conn(self._db_path)

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def upsert_document(self, doc: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO documents
              (doc_id, category, subcategory, title, doc_type, source_url,
               filename, format, version_date, sha256, ingested_at, is_latest)
            VALUES
              (:doc_id, :category, :subcategory, :title, :doc_type, :source_url,
               :filename, :format, :version_date, :sha256, :ingested_at, :is_latest)
            ON CONFLICT(doc_id) DO UPDATE SET
              sha256     = excluded.sha256,
              ingested_at = excluded.ingested_at,
              is_latest  = excluded.is_latest
            """,
            doc,
        )
        self._conn.commit()

    def list_documents(
        self,
        category: str | None = None,
        subcategory: str | None = None,
        doc_type: str | None = None,
        latest_only: bool = True,
    ) -> list[sqlite3.Row]:
        clauses, params = [], []
        if latest_only:
            clauses.append("is_latest = 1")
        if category:
            clauses.append("category = ?")
            params.append(category)
        if subcategory:
            clauses.append("subcategory = ?")
            params.append(subcategory)
        if doc_type:
            clauses.append("doc_type = ?")
            params.append(doc_type)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(f"SELECT * FROM documents {where}", params).fetchall()
        return rows

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> list[int]:
        ids = []
        for chunk in chunks:
            cur = self._conn.execute(
                """
                INSERT INTO chunks (doc_id, section, page, road_types, topics, chunk_text)
                VALUES (:doc_id, :section, :page, :road_types, :topics, :chunk_text)
                """,
                {
                    **chunk,
                    "road_types": json.dumps(chunk.get("road_types", [])),
                    "topics": json.dumps(chunk.get("topics", [])),
                },
            )
            ids.append(cur.lastrowid)
        self._conn.commit()
        return ids

    def delete_chunks_for_doc(self, doc_id: str) -> None:
        self._conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Embeddings (sqlite-vec, optional)
    # ------------------------------------------------------------------

    def has_vec(self) -> bool:
        try:
            self._conn.execute("SELECT * FROM chunk_embeddings LIMIT 0")
            return True
        except sqlite3.OperationalError:
            return False

    def upsert_embeddings(self, rows: list[tuple[int, list[float]]]) -> None:
        if not self.has_vec():
            return
        self._conn.executemany(
            "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)",
            [(cid, json.dumps(emb)) for cid, emb in rows],
        )
        self._conn.commit()

    def vector_search(
        self, query_embedding: list[float], limit: int = 8
    ) -> list[sqlite3.Row]:
        if not self.has_vec():
            return []
        rows = self._conn.execute(
            """
            SELECT c.chunk_id, c.doc_id, c.section, c.page,
                   c.road_types, c.topics, c.chunk_text,
                   ce.distance AS score
            FROM chunk_embeddings ce
            JOIN chunks c ON c.chunk_id = ce.chunk_id
            WHERE ce.embedding MATCH ?
            ORDER BY ce.distance
            LIMIT ?
            """,
            (json.dumps(query_embedding), limit),
        ).fetchall()
        return rows

    # ------------------------------------------------------------------
    # FTS search
    # ------------------------------------------------------------------

    def fts_search(self, query: str, limit: int = 8) -> list[sqlite3.Row]:
        # BM25 in FTS5 is negative; negate it so higher = more relevant
        rows = self._conn.execute(
            """
            SELECT c.chunk_id, c.doc_id, c.section, c.page,
                   c.road_types, c.topics, c.chunk_text,
                   -bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.chunk_id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
            ORDER BY score DESC
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return rows

    # ------------------------------------------------------------------
    # Standards lookups (Phase 2+)
    # ------------------------------------------------------------------

    def lookup_parameter(
        self,
        road_type_name: str,
        parameter: str,
        conditions: dict | None = None,
    ) -> list[sqlite3.Row]:
        rows = self._conn.execute(
            """
            SELECT gs.*, rt.name AS road_type_name
            FROM geometric_standards gs
            JOIN road_types rt ON rt.road_type_id = gs.road_type_id
            WHERE LOWER(rt.name) = LOWER(?)
              AND LOWER(gs.parameter) LIKE LOWER(?)
            ORDER BY gs.version_date DESC
            """,
            (road_type_name, f"%{parameter}%"),
        ).fetchall()
        return rows

    def find_drawings(
        self,
        series: str | None = None,
        topic: str | None = None,
        road_type: str | None = None,
    ) -> list[sqlite3.Row]:
        clauses, params = [], []
        if series:
            clauses.append("series = ?")
            params.append(series)
        if topic:
            clauses.append("(title LIKE ? OR applies_to LIKE ?)")
            params += [f"%{topic}%", f"%{topic}%"]
        if road_type:
            clauses.append("applies_to LIKE ?")
            params.append(f"%{road_type}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return self._conn.execute(
            f"SELECT * FROM standard_drawings {where} ORDER BY series, drawing_no",
            params,
        ).fetchall()

    def list_compliance_rules(
        self, road_type_id: int | None = None
    ) -> list[sqlite3.Row]:
        if road_type_id:
            return self._conn.execute(
                "SELECT * FROM compliance_rules WHERE road_type_id = ? OR road_type_id IS NULL",
                (road_type_id,),
            ).fetchall()
        return self._conn.execute("SELECT * FROM compliance_rules").fetchall()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        def scalar(sql: str) -> int:
            return self._conn.execute(sql).fetchone()[0]

        return {
            "documents": scalar("SELECT COUNT(*) FROM documents WHERE is_latest=1"),
            "chunks": scalar("SELECT COUNT(*) FROM chunks"),
            "has_vectors": self.has_vec(),
            "road_types": scalar("SELECT COUNT(*) FROM road_types"),
            "compliance_rules": scalar("SELECT COUNT(*) FROM compliance_rules"),
        }
