"""分组指标聚合：漏斗、评价分布、履约事实、渠道构成。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .feedback import CaseView
from .models import Period
from .periods import assign_period_iso


@dataclass(frozen=True)
class Funnel:
    """三层分母漏斗；未知 = 已送达但未评价，绝不按零分处理。"""

    cases: int
    eligible: int
    delivered: int
    responded: int
    unknown: int
    not_invited: int
    delivery_rate: float | None
    response_rate_eligible: float | None
    response_rate_delivered: float | None
    coverage_rate: float | None  # 有评价案件 / 全部案件


@dataclass(frozen=True)
class RatingSummary:
    """仅统计当前有效评价；未回应案件不进入。"""

    rated_cases: int
    mean: float | None
    distribution: dict[int, int]
    # 满意（4-5）、中性（3）、不满（1-2）的案件数
    positive: int
    neutral: int
    negative: int


@dataclass(frozen=True)
class Fulfillment:
    """独立办理事实：只来自 cases，不使用任何评价数据。"""

    total: int
    closed: int
    open: int
    closed_rate: float | None
    outcome_counts: dict[str, int]
    # completed 结果在已办结案件中的占比
    completion_rate: float | None


@dataclass
class GroupMetrics:
    key: str
    dimension: str
    funnel: Funnel
    rating: RatingSummary
    fulfillment: Fulfillment
    channel_mix: dict[str, int]
    period_ids: tuple[str, ...] = ()
    samplings: tuple[str, ...] = ()
    case_ids: tuple[str, ...] = field(default_factory=tuple)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _funnel(views: list[CaseView]) -> Funnel:
    total = len(views)
    eligible = sum(1 for v in views if v.eligible)
    delivered = sum(1 for v in views if v.delivered)
    responded = sum(1 for v in views if v.responded)
    unknown = delivered - responded
    not_invited = total - eligible
    return Funnel(
        cases=total,
        eligible=eligible,
        delivered=delivered,
        responded=responded,
        unknown=unknown,
        not_invited=not_invited,
        delivery_rate=_ratio(delivered, eligible),
        response_rate_eligible=_ratio(responded, eligible),
        response_rate_delivered=_ratio(responded, delivered),
        coverage_rate=_ratio(responded, total),
    )


def _rating(views: list[CaseView]) -> RatingSummary:
    scored = [v for v in views if v.responded and v.current_score is not None]
    distribution = {score: 0 for score in range(1, 6)}
    for view in scored:
        distribution[view.current_score] += 1
    positive = sum(count for score, count in distribution.items() if score >= 4)
    neutral = distribution[3]
    negative = sum(count for score, count in distribution.items() if score <= 2)
    mean = round(sum(v.current_score for v in scored) / len(scored), 2) if scored else None
    return RatingSummary(
        rated_cases=len(scored),
        mean=mean,
        distribution=distribution,
        positive=positive,
        neutral=neutral,
        negative=negative,
    )


def _fulfillment(views: list[CaseView]) -> Fulfillment:
    total = len(views)
    closed_views = [v for v in views if v.closed_at is not None]
    open_views = total - len(closed_views)
    outcome_counts: dict[str, int] = {}
    for view in views:
        outcome_counts[view.outcome] = outcome_counts.get(view.outcome, 0) + 1
    completed = outcome_counts.get("completed", 0)
    return Fulfillment(
        total=total,
        closed=len(closed_views),
        open=open_views,
        closed_rate=_ratio(len(closed_views), total),
        outcome_counts=dict(sorted(outcome_counts.items())),
        completion_rate=_ratio(completed, len(closed_views)),
    )


def _channel_mix(views: list[CaseView]) -> dict[str, int]:
    """渠道构成按“案件—渠道”去重统计（同一案件多次同渠道邀请只计一次）。"""

    mix: dict[str, int] = {}
    for view in views:
        for channel in view.channels:
            mix[channel] = mix.get(channel, 0) + 1
    return dict(sorted(mix.items()))


def aggregate(
    views: list[CaseView],
    dimension: str,
    periods: list[Period],
) -> list[GroupMetrics]:
    """按维度聚合。dimension 取 grid / service / period / overall。"""

    period_sampling = {period.id: period.sampling for period in periods}
    buckets: dict[str, list[CaseView]] = {}
    for view in views:
        if dimension == "overall":
            key = "全体"
        elif dimension == "period":
            key = assign_period_iso(view.closed_at, periods)
        else:
            key = getattr(view, dimension)
        buckets.setdefault(key, []).append(view)

    metrics_list: list[GroupMetrics] = []
    for key in sorted(buckets):
        group_views = buckets[key]
        period_ids = tuple(
            sorted({assign_period_iso(v.closed_at, periods) for v in group_views})
        )
        samplings = tuple(
            dict.fromkeys(period_sampling[pid] for pid in period_ids if pid in period_sampling)
        )
        metrics_list.append(
            GroupMetrics(
                key=key,
                dimension=dimension,
                funnel=_funnel(group_views),
                rating=_rating(group_views),
                fulfillment=_fulfillment(group_views),
                channel_mix=_channel_mix(group_views),
                period_ids=period_ids,
                samplings=samplings,
                case_ids=tuple(v.case_id for v in group_views),
            )
        )
    return metrics_list


def aggregate_all(
    views: list[CaseView], periods: list[Period]
) -> dict[str, list[GroupMetrics]]:
    return {
        dimension: aggregate(views, dimension, periods)
        for dimension in ("overall", "grid", "service", "period")
    }
