"""测试辅助：把内存中的表写入临时资料目录。"""

from __future__ import annotations

import json
from pathlib import Path

_TABLE_NAMES = ("cases", "invitations", "responses", "periods")


def write_fixtures(
    tmp_path: Path,
    *,
    cases: list[dict],
    invitations: list[dict],
    responses: list[dict],
    periods: list[dict],
) -> Path:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    for name in _TABLE_NAMES:
        (fixtures / f"{name}.json").write_text(
            json.dumps(locals()[name], ensure_ascii=False), encoding="utf-8"
        )
    return fixtures


def minimal_periods() -> list[dict]:
    return [
        {"id": "P1", "start": "2026-06-01", "end": "2026-07-01",
         "sampling": "eligible_completed_cases"},
        {"id": "P2", "start": "2026-07-01", "end": "2026-08-01",
         "sampling": "all_closed_cases"},
    ]
