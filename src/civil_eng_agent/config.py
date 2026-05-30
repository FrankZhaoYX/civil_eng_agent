"""Runtime configuration for civil-eng-agent."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data" / "raw"
RUNTIME_DIR = Path.home() / ".civil-eng-agent"


class EmbedConfig(BaseModel):
    provider: str = "voyage"       # "voyage" | "local"
    voyage_model: str = "voyage-3"
    local_model: str = "all-MiniLM-L6-v2"
    dimension: int = 1024


class Config(BaseModel):
    db_path: Path = Field(default_factory=lambda: RUNTIME_DIR / "corpus.db")
    cache_dir: Path = Field(default_factory=lambda: RUNTIME_DIR / "cache")
    data_raw_dir: Path = Field(default_factory=lambda: DATA_DIR)
    sources_yaml: Path = Field(default_factory=lambda: CONFIG_DIR / "sources.yaml")
    embed: EmbedConfig = Field(default_factory=EmbedConfig)
    air_gapped: bool = False
    voyage_api_key: str | None = None
    anthropic_api_key: str | None = None

    @classmethod
    def load(cls) -> "Config":
        runtime_cfg = RUNTIME_DIR / "config.yaml"
        data: dict = {}
        if runtime_cfg.exists():
            with runtime_cfg.open() as f:
                data = yaml.safe_load(f) or {}

        voyage_key = os.environ.get("VOYAGE_API_KEY") or data.pop("voyage_api_key", None)
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or data.pop("anthropic_api_key", None)

        cfg = cls(**data)
        cfg.voyage_api_key = voyage_key
        cfg.anthropic_api_key = anthropic_key

        if cfg.air_gapped:
            cfg.embed.provider = "local"

        if cfg.embed.provider == "voyage" and not cfg.voyage_api_key:
            cfg.embed.provider = "local"
            cfg.embed.dimension = 384

        return cfg

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
