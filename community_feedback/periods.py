"""时期归属。

案件按其办结时间（``cases.closed_at``）归入时期；未办结或办结时间不落在
任何已登记时期内的案件归入“未归期”。时期边界采用左闭右开区间，与
periods 的 start/end 语义一致。
"""

from __future__ import annotations

from datetime import date

from .models import Period

UNASSIGNED_PERIOD = "未归期"


def assign_period(closed_at: date | None, periods: list[Period]) -> str:
    if closed_at is None:
        return UNASSIGNED_PERIOD
    for period in sorted(periods, key=lambda p: p.start):
        if period.start <= closed_at < period.end:
            return period.id
    return UNASSIGNED_PERIOD


def assign_period_iso(closed_at_iso: str | None, periods: list[Period]) -> str:
    """供案件视图（closed_at 已转为 ISO 字符串）使用的便捷入口。"""

    if closed_at_iso is None:
        return UNASSIGNED_PERIOD
    return assign_period(date.fromisoformat(closed_at_iso), periods)
