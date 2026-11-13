"""PostgreSQL + pgvector store, driven through the ``psql`` client.

Why psql instead of psycopg: in the environment where this lab was run, Python
packages could not be installed (no network), but the PostgreSQL 16 client was
present.  Every statement is sent to ``psql`` on stdin; user-supplied values are
passed as psql variables and interpolated with ``:'var'`` (psql quotes them as
SQL literals), never formatted into SQL by hand.  Filter *keys* are checked
against a whitelist.

Set ``PSQL_BIN`` to e.g. ``docker exec -i day6_student_starter-postgres-1 psql``
to use the Docker container from ``docker-compose.yml`` without a local client.
Search is exact (sequential scan, no ANN index), cosine distance ``<=>``.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shlex
import subprocess
from typing import Any

from .models import Chunk

FILTER_COLUMNS = {"pep_type", "python_version", "status", "document_id", "section"}
TABLE = "chunks"


class StoreError(RuntimeError):
    pass


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise StoreError("DATABASE_URL is empty")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions
        self.psql = shlex.split(os.getenv("PSQL_BIN", "psql"))

    # ------------------------------------------------------------ plumbing
    def _run(self, script: str, variables: dict[str, str] | None = None) -> str:
        cmd = [*self.psql, self.database_url, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
        for k, v in (variables or {}).items():
            cmd += ["-v", f"{k}={v}"]
        proc = subprocess.run(cmd, input=script, capture_output=True, text=True)
        if proc.returncode != 0:
            raise StoreError(f"psql failed ({proc.returncode}): {proc.stderr.strip()[:2000]}")
        return proc.stdout

    def server_info(self) -> dict[str, str]:
        out = self._run("SELECT json_build_object('db', current_database(), 'pg', "
                        "current_setting('server_version'), 'pgvector', "
                        "(SELECT extversion FROM pg_extension WHERE extname='vector'));")
        return json.loads(out.strip())

    # ------------------------------------------------------------ schema
    def create_schema(self) -> None:
        self._run(f"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS {TABLE} (
    strategy       text    NOT NULL,
    chunk_id       text    NOT NULL,
    document_id    text    NOT NULL,
    source         text    NOT NULL,
    page           integer NOT NULL,
    unit_id        text    NOT NULL,
    section        text,
    title          text,
    pep_type       text,
    python_version text,
    status         text,
    text           text    NOT NULL,
    char_len       integer NOT NULL,
    content_hash   text    NOT NULL,
    embedding      vector({self.dimensions}) NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy, chunk_id)
);
CREATE INDEX IF NOT EXISTS {TABLE}_filter_idx ON {TABLE} (strategy, pep_type, python_version);
""")

    # ------------------------------------------------------------ write
    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> dict[str, int]:
        """Insert/update chunks with stable IDs; delete obsolete chunks of re-ingested documents.

        Returns counts: inserted, updated, unchanged, deleted.
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk_id in batch")
        buf = io.StringIO()

        class _TextCopyWriter:  # COPY text format: one physical line per row, escaped
            @staticmethod
            def writerow(values: list) -> None:
                out = []
                for val in values:
                    if val is None:
                        out.append(r"\N")
                    else:
                        s = str(val).replace("\\", "\\\\").replace("\n", "\\n") \
                            .replace("\r", "\\r").replace("\t", "\\t")
                        out.append(s)
                buf.write("\t".join(out) + "\n")

        writer = _TextCopyWriter()
        for c, v in zip(chunks, vectors):
            if len(v) != self.dimensions:
                raise ValueError(f"vector for {c.chunk_id} has {len(v)} dims, expected {self.dimensions}")
            m = c.metadata
            digest = hashlib.sha256(c.text.encode("utf-8")).hexdigest()
            writer.writerow([strategy, c.chunk_id, c.document_id, c.source, c.page, m.get("unit_id"),
                             m.get("section"), m.get("title"), m.get("pep_type"), m.get("python_version"),
                             m.get("status"), c.text, len(c.text), digest,
                             "[" + ",".join(f"{x:.7g}" for x in v) + "]"])
        cols = ("strategy, chunk_id, document_id, source, page, unit_id, section, title, pep_type, "
                "python_version, status, text, char_len, content_hash, embedding")
        script = f"""
BEGIN;
CREATE TEMP TABLE staging (LIKE {TABLE} INCLUDING DEFAULTS) ON COMMIT DROP;
COPY staging ({cols}) FROM STDIN WITH (FORMAT text);
{buf.getvalue()}\\.
WITH del AS (
  DELETE FROM {TABLE} t
  WHERE t.strategy = :'strategy'
    AND t.document_id IN (SELECT DISTINCT document_id FROM staging)
    AND NOT EXISTS (SELECT 1 FROM staging s WHERE s.chunk_id = t.chunk_id)
  RETURNING 1),
up AS (
  INSERT INTO {TABLE} ({cols})
  SELECT {cols} FROM staging
  ON CONFLICT (strategy, chunk_id) DO UPDATE SET
    document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
    unit_id = EXCLUDED.unit_id, section = EXCLUDED.section, title = EXCLUDED.title,
    pep_type = EXCLUDED.pep_type, python_version = EXCLUDED.python_version,
    status = EXCLUDED.status, text = EXCLUDED.text, char_len = EXCLUDED.char_len,
    content_hash = EXCLUDED.content_hash, embedding = EXCLUDED.embedding, updated_at = now()
  WHERE {TABLE}.content_hash IS DISTINCT FROM EXCLUDED.content_hash
     OR {TABLE}.section IS DISTINCT FROM EXCLUDED.section
  RETURNING (xmax = 0) AS inserted)
SELECT json_build_object(
  'deleted', (SELECT count(*) FROM del),
  'inserted', (SELECT count(*) FROM up WHERE inserted),
  'updated', (SELECT count(*) FROM up WHERE NOT inserted),
  'batch', (SELECT count(*) FROM staging));
COMMIT;
"""
        out = self._run(script, {"strategy": strategy})
        stats = json.loads([ln for ln in out.splitlines() if ln.startswith("{")][-1])
        stats["unchanged"] = stats["batch"] - stats["inserted"] - stats["updated"]
        return stats

    def count(self, strategy: str) -> dict[str, int]:
        out = self._run(f"SELECT json_build_object('rows', count(*), 'distinct_ids', count(DISTINCT chunk_id)) "
                        f"FROM {TABLE} WHERE strategy = :'strategy';", {"strategy": strategy})
        return json.loads(out.strip())

    # ------------------------------------------------------------ read
    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector has wrong dimensions")
        variables = {"strategy": strategy,
                     "qvec": "[" + ",".join(f"{x:.7g}" for x in query_vector) + "]",
                     "k": str(int(top_k))}
        where = ["strategy = :'strategy'"]
        for i, (key, value) in enumerate(sorted((filters or {}).items())):
            if key not in FILTER_COLUMNS:
                raise ValueError(f"filter on '{key}' is not allowed")
            variables[f"f{i}"] = str(value)
            where.append(f"{key} = :'f{i}'")
        script = f"""
SELECT coalesce(json_agg(r ORDER BY r.distance), '[]'::json) FROM (
  SELECT chunk_id, document_id, source, page, unit_id, section, title, pep_type,
         python_version, status, text, char_len,
         embedding <=> :'qvec'::vector AS distance
  FROM {TABLE}
  WHERE {' AND '.join(where)}
  ORDER BY embedding <=> :'qvec'::vector
  LIMIT :k) r;
"""
        rows = json.loads(self._run(script, variables).strip())
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
            row["score"] = round(1.0 - row["distance"], 6)  # cosine similarity
        return rows
