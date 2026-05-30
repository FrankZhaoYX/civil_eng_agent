PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Documents — tagged with category/subcategory from the source config
CREATE TABLE IF NOT EXISTS documents (
  doc_id        TEXT PRIMARY KEY,
  category      TEXT NOT NULL,
  subcategory   TEXT NOT NULL,
  title         TEXT NOT NULL,
  doc_type      TEXT NOT NULL CHECK (doc_type IN ('guideline','standard_drawing','specification','bid_form','master_plan')),
  source_url    TEXT NOT NULL,
  filename      TEXT NOT NULL,
  format        TEXT NOT NULL CHECK (format IN ('pdf','docx')),
  version_date  DATE,
  sha256        TEXT NOT NULL,
  ingested_at   TIMESTAMP NOT NULL,
  is_latest     BOOLEAN NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_documents_cat    ON documents(category, subcategory);
CREATE INDEX IF NOT EXISTS idx_documents_type   ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_latest ON documents(is_latest);

-- Prose chunks for semantic + FTS search
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
  section     TEXT,
  page        INTEGER,
  road_types  TEXT,   -- JSON array
  topics      TEXT,   -- JSON array
  chunk_text  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

-- FTS over chunks (content table mirrors chunks)
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  chunk_text, road_types, topics,
  content='chunks', content_rowid='chunk_id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, chunk_text, road_types, topics)
  VALUES (new.chunk_id, new.chunk_text, new.road_types, new.topics);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, chunk_text, road_types, topics)
  VALUES ('delete', old.chunk_id, old.chunk_text, old.road_types, old.topics);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, chunk_text, road_types, topics)
  VALUES ('delete', old.chunk_id, old.chunk_text, old.road_types, old.topics);
  INSERT INTO chunks_fts(rowid, chunk_text, road_types, topics)
  VALUES (new.chunk_id, new.chunk_text, new.road_types, new.topics);
END;

-- Road type catalog
CREATE TABLE IF NOT EXISTS road_types (
  road_type_id   INTEGER PRIMARY KEY,
  name           TEXT UNIQUE NOT NULL,
  description    TEXT,
  source_doc     TEXT NOT NULL,
  source_section TEXT,
  source_page    INTEGER,
  version_date   DATE NOT NULL
);

-- Cross-section element standards
CREATE TABLE IF NOT EXISTS cross_section_standards (
  id              INTEGER PRIMARY KEY,
  road_type_id    INTEGER REFERENCES road_types(road_type_id),
  element         TEXT NOT NULL,
  position        TEXT,
  min_m           REAL,
  typical_m       REAL,
  max_m           REAL,
  conditions      TEXT,
  source_doc      TEXT NOT NULL,
  source_section  TEXT,
  source_page     INTEGER,
  version_date    DATE NOT NULL
);

-- Geometric design parameters
CREATE TABLE IF NOT EXISTS geometric_standards (
  id            INTEGER PRIMARY KEY,
  road_type_id  INTEGER REFERENCES road_types(road_type_id),
  parameter     TEXT NOT NULL,
  value         REAL NOT NULL,
  unit          TEXT NOT NULL,
  conditions    TEXT,
  source_doc    TEXT NOT NULL,
  source_section TEXT,
  source_page   INTEGER,
  version_date  DATE NOT NULL
);

-- Standard drawings (DS-series, NHF-series)
CREATE TABLE IF NOT EXISTS standard_drawings (
  id            INTEGER PRIMARY KEY,
  series        TEXT NOT NULL,
  drawing_no    TEXT NOT NULL,
  title         TEXT NOT NULL,
  file_path     TEXT NOT NULL,
  applies_to    TEXT,
  callouts      TEXT,  -- JSON array of extracted callout strings
  version_date  DATE NOT NULL,
  UNIQUE (series, drawing_no, version_date)
);

-- Compliance rules
CREATE TABLE IF NOT EXISTS compliance_rules (
  rule_id         TEXT PRIMARY KEY,
  description     TEXT NOT NULL,
  road_type_id    INTEGER REFERENCES road_types(road_type_id),
  check_logic     TEXT NOT NULL,  -- JSON: {parameter, operator, threshold, unit}
  severity        TEXT NOT NULL CHECK (severity IN ('must','should','may')),
  source_doc      TEXT NOT NULL,
  source_section  TEXT,
  source_page     INTEGER,
  version_date    DATE NOT NULL
);

-- Embeddings table (populated only when vec0 extension available)
-- If sqlite-vec is not installed this table is skipped and we fall back to FTS only.
