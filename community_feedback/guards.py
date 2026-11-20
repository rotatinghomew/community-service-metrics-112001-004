"""推断守卫：什么情况下允许给结论，什么情况下只能描述。

三类限制：

1. 抽样框架（``periods.sampling``）必须已登记，且框架总体覆盖组内全部案件；
   否则结论只适用于框架内总体，不能代表整组。
2. 有效评价票数达到最小样本量，且回收率达到最低回收率。
3. 跨多个不同抽样框架混合的组（如跨期网格汇总）不做合并推断。

未通过守卫的组仍展示描述性统计（分布、覆盖率、履约事实），但不进入
满意度排名，并明确列出限制原因。未回应群体始终标为“未知”，不参与任何
平均分计算。
"""

from __future__ import annotations

from dataclasses import dataclass

from .feedback import CaseView
from .metrics import GroupMetrics
from .periods import UNASSIGNED_PERIOD

DEFAULT_MIN_RESPONSES = 5
DEFAULT_MIN_RESPONSE_RATE = 0.5


@dataclass(frozen=True)
class FrameInfo:
    code: str
    label: str
    target: str
    description: str


# 抽样框架登记表：新机制上线时应在此登记其推断目标与覆盖范围。
FRAME_REGISTRY: dict[str, FrameInfo] = {
    "eligible_completed_cases": FrameInfo(
        code="eligible_completed_cases",
        label="符合邀请条件的已办结事项",
        target="符合邀请条件且已办结的案件",
        description="仅对有资格收到邀请的已办结案件抽样；未纳入邀请的案件不在框架内。",
    ),
    "all_closed_cases": FrameInfo(
        code="all_closed_cases",
        label="全部已办结事项",
        target="全部已办结案件（含未纳入邀请者）",
        description="对全部已办结案件抽样；未办结案件不在框架内。",
    ),
}


@dataclass(frozen=True)
class GuardVerdict:
    group_key: str
    dimension: str
    rank_allowed: bool
    reasons: tuple[str, ...]
    frame_code: str | None
    frame_target: str | None
    frame_covers_group: bool
    rated_cases: int
    response_rate: float | None
    notes: tuple[str, ...]


def _frame_population_membership(frame_code: str, view: CaseView) -> bool:
    """判断案件是否属于某抽样框架的目标总体。"""

    if frame_code == "eligible_completed_cases":
        return view.eligible and view.closed_at is not None
    if frame_code == "all_closed_cases":
        return view.closed_at is not None
    return False


def _frame_covers_group(frame_code: str, views: list[CaseView]) -> bool:
    return all(_frame_population_membership(frame_code, view) for view in views)


def evaluate_group(
    metrics: GroupMetrics,
    views_by_key: dict[str, list[CaseView]],
    min_responses: int = DEFAULT_MIN_RESPONSES,
    min_response_rate: float = DEFAULT_MIN_RESPONSE_RATE,
) -> GuardVerdict:
    """对单个分组执行推断守卫。"""

    group_views = views_by_key[metrics.key]
    reasons: list[str] = []
    notes: list[str] = []
    samplings = metrics.samplings
    frame_code: str | None = None
    frame_target: str | None = None
    covers = False

    period_ids = metrics.period_ids
    has_unassigned = UNASSIGNED_PERIOD in period_ids
    if metrics.key == UNASSIGNED_PERIOD and metrics.dimension == "period":
        reasons.append("该组案件未落入任何已登记时期，没有可识别的抽样框架")
    elif not samplings:
        reasons.append("组内案件没有可识别的抽样框架信息")
    elif len(set(samplings)) > 1:
        reasons.append(
            "组内混合了不同抽样框架（"
            + "、".join(dict.fromkeys(samplings))
            + "），样本构成改变，不能合并做总体推断"
        )
    else:
        frame_code = samplings[0]
        frame = FRAME_REGISTRY.get(frame_code)
        if frame is None:
            reasons.append(f"抽样框架 {frame_code!r} 未在框架登记表中注册，不支持总体推断")
            frame_code = None
        else:
            frame_target = frame.target
            covers = _frame_covers_group(frame.code, group_views)
            if has_unassigned and len(period_ids) > 1:
                reasons.append("组内包含未落入任何已登记时期的案件，抽样框架无法覆盖这些案件")
            if not covers:
                reasons.append(
                    f"框架仅覆盖“{frame.target}”，组内存在框架外案件"
                    "（如未办结或未纳入邀请），结论不能代表整组"
                )

    funnel = metrics.funnel
    if funnel.responded < min_responses:
        reasons.append(
            f"有效评价样本不足：{funnel.responded} 票，低于最小样本量 {min_responses} 票"
        )
    rate = funnel.response_rate_eligible
    if rate is None:
        reasons.append("没有符合邀请条件的案件，回收率无法计算")
    elif rate < min_response_rate:
        reasons.append(
            f"回收率不足：{rate:.1%}，低于最低回收率阈值 {min_response_rate:.0%}"
        )

    if funnel.unknown > 0:
        notes.append(
            f"{funnel.unknown} 个已送达案件未回应，按“未知”处理，未计入平均分或零分"
        )
    notes.append("评价为自愿回应样本，存在自选偏差；覆盖率与回收率须与平均分并读")

    return GuardVerdict(
        group_key=metrics.key,
        dimension=metrics.dimension,
        rank_allowed=not reasons,
        reasons=tuple(reasons),
        frame_code=frame_code,
        frame_target=frame_target,
        frame_covers_group=covers,
        rated_cases=funnel.responded,
        response_rate=rate,
        notes=tuple(notes),
    )


def evaluate_all(
    grouped_metrics: dict[str, list[GroupMetrics]],
    views: list[CaseView],
    min_responses: int = DEFAULT_MIN_RESPONSES,
    min_response_rate: float = DEFAULT_MIN_RESPONSE_RATE,
) -> dict[str, list[GuardVerdict]]:
    # 预建各维度分组键到案件视图的映射
    index: dict[tuple[str, str], list[CaseView]] = {}
    for dimension, groups in grouped_metrics.items():
        for group in groups:
            index[(dimension, group.key)] = [
                view for view in views if view.case_id in group.case_ids
            ]
    verdicts: dict[str, list[GuardVerdict]] = {}
    for dimension, groups in grouped_metrics.items():
        verdicts[dimension] = [
            evaluate_group(
                group,
                {group.key: index[(dimension, group.key)]},
                min_responses,
                min_response_rate,
            )
            for group in groups
        ]
    return verdicts


def build_rankings(
    grouped_metrics: dict[str, list[GroupMetrics]],
    verdicts: dict[str, list[GuardVerdict]],
) -> dict[str, list[dict]]:
    """仅对通过守卫的组排名；未通过者不参与，且不生成全体满意度排名。"""

    rankings: dict[str, list[dict]] = {}
    for dimension, groups in grouped_metrics.items():
        verdict_by_key = {v.group_key: v for v in verdicts[dimension]}
        eligible = [
            group
            for group in groups
            if verdict_by_key[group.key].rank_allowed
            and group.rating.mean is not None
        ]
        ordered = sorted(
            eligible,
            key=lambda g: (g.rating.mean, g.rating.rated_cases, g.key),
            reverse=True,
        )
        rankings[dimension] = [
            {
                "rank": index + 1,
                "group_key": group.key,
                "mean": group.rating.mean,
                "rated_cases": group.rating.rated_cases,
                "frame_target": verdict_by_key[group.key].frame_target,
            }
            for index, group in enumerate(ordered)
        ]
    return rankings
