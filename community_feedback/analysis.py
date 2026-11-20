"""分析编排：加载 → 案件归并 → 分组聚合 → 推断守卫 → 受限排名。

另产出两类跨期可比性提示：

* 框架漂移：相邻时期的抽样框架标识不同，样本总体改变；
* 渠道变化：相邻时期实际使用的邀请渠道集合不同，触达机制改变。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .feedback import CaseView, build_case_views
from .guards import (
    DEFAULT_MIN_RESPONSE_RATE,
    DEFAULT_MIN_RESPONSES,
    GuardVerdict,
    build_rankings,
    evaluate_all,
)
from .loading import load_dataset
from .metrics import GroupMetrics, aggregate_all
from .models import DataIssue
from .periods import UNASSIGNED_PERIOD, assign_period_iso


@dataclass(frozen=True)
class DriftNote:
    kind: str  # frame_drift / channel_change
    left_period: str
    right_period: str
    detail: str


@dataclass
class Analysis:
    fixtures_dir: str
    min_responses: int
    min_response_rate: float
    total_cases: int
    views: list[CaseView]
    issues: list[DataIssue]
    grouped_metrics: dict[str, list[GroupMetrics]]
    verdicts: dict[str, list[GuardVerdict]]
    rankings: dict[str, list[dict]]
    drifts: list[DriftNote]
    period_channel_mix: dict[str, dict[str, int]]
    period_sampling: dict[str, str]

    def verdict_for(self, dimension: str, key: str) -> GuardVerdict | None:
        for verdict in self.verdicts.get(dimension, ()):
            if verdict.group_key == key:
                return verdict
        return None


def _period_drifts(analysis_views: list[CaseView], periods) -> tuple[list[DriftNote], dict[str, dict[str, int]], dict[str, str]]:
    period_sampling = {p.id: p.sampling for p in periods}
    period_mix: dict[str, dict[str, int]] = {p.id: {} for p in periods}
    for view in analysis_views:
        pid = assign_period_iso(view.closed_at, periods)
        if pid == UNASSIGNED_PERIOD:
            continue
        bucket = period_mix.setdefault(pid, {})
        for channel in view.channels:
            bucket[channel] = bucket.get(channel, 0) + 1

    drifts: list[DriftNote] = []
    ordered_periods = sorted(periods, key=lambda p: p.start)
    for left, right in zip(ordered_periods, ordered_periods[1:]):
        if left.sampling != right.sampling:
            drifts.append(
                DriftNote(
                    kind="frame_drift",
                    left_period=left.id,
                    right_period=right.id,
                    detail=(
                        f"抽样框架由 {left.sampling} 变为 {right.sampling}，"
                        "两期样本总体不同，平均分与覆盖率不可直接比较"
                    ),
                )
            )
        left_channels = set(period_mix.get(left.id, {}))
        right_channels = set(period_mix.get(right.id, {}))
        if left_channels and right_channels and left_channels != right_channels:
            added = sorted(right_channels - left_channels)
            removed = sorted(left_channels - right_channels)
            parts = []
            if added:
                parts.append(f"新增渠道 {', '.join(added)}")
            if removed:
                parts.append(f"停用渠道 {', '.join(removed)}")
            drifts.append(
                DriftNote(
                    kind="channel_change",
                    left_period=left.id,
                    right_period=right.id,
                    detail="、".join(parts) + "，触达机制改变，回应构成可能变化",
                )
            )
    return drifts, period_mix, period_sampling


def run_analysis(
    fixtures_dir: str | Path,
    min_responses: int = DEFAULT_MIN_RESPONSES,
    min_response_rate: float = DEFAULT_MIN_RESPONSE_RATE,
) -> Analysis:
    dataset, load_warnings = load_dataset(fixtures_dir)
    views, view_warnings = build_case_views(dataset)
    issues = [*load_warnings, *view_warnings]

    grouped = aggregate_all(views, dataset.periods)
    verdicts = evaluate_all(grouped, views, min_responses, min_response_rate)
    rankings = build_rankings(grouped, verdicts)
    drifts, period_mix, period_sampling = _period_drifts(views, dataset.periods)

    return Analysis(
        fixtures_dir=str(fixtures_dir),
        min_responses=min_responses,
        min_response_rate=min_response_rate,
        total_cases=len(dataset.cases),
        views=views,
        issues=issues,
        grouped_metrics=grouped,
        verdicts=verdicts,
        rankings=rankings,
        drifts=drifts,
        period_channel_mix=period_mix,
        period_sampling=period_sampling,
    )
