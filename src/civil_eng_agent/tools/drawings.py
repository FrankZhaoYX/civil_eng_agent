"""find_drawing tool: search standard drawings by series, topic, or road type."""
from __future__ import annotations

from pydantic import BaseModel

from civil_eng_agent.config import Config
from civil_eng_agent.store.repository import Repository


class DrawingReference(BaseModel):
    series: str
    drawing_no: str
    title: str
    file_path: str
    applies_to: str | None
    callouts: list[str]
    version_date: str


def find_drawing(
    series: str | None = None,
    topic: str | None = None,
    road_type: str | None = None,
    cfg: Config | None = None,
    repo: Repository | None = None,
) -> list[DrawingReference]:
    """Return matching standard drawings with file paths and extracted callouts."""
    if cfg is None:
        cfg = Config.load()
    if repo is None:
        repo = Repository(cfg.db_path)

    import json

    rows = repo.find_drawings(series=series, topic=topic, road_type=road_type)
    results = []
    for row in rows:
        callouts = json.loads(row["callouts"]) if row["callouts"] else []
        results.append(
            DrawingReference(
                series=row["series"],
                drawing_no=row["drawing_no"],
                title=row["title"],
                file_path=row["file_path"],
                applies_to=row["applies_to"],
                callouts=callouts,
                version_date=row["version_date"],
            )
        )
    return results
