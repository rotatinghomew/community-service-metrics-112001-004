"""评价更正链解析与案件级视图构建。

口径要点：

* ``supersedes`` 形成更正链：新评价替代旧评价，只有链头部（未被任何评价
  替代者）可能成为有效评价；检测到循环时整个链作废并给出警告。
* 一个案件可能收到多条独立链（如不同邀请渠道各有回应）。若并存多个有效
  头部，取 ``received_at`` 最晚者为当前有效评价，同时给出“多头并存”警告；
  无论选哪条，该案件在漏斗中只计一次回应、只计一票。
* 挂在未送达或不符合条件邀请下的评价不进入漏斗，单独提示。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DataIssue, Dataset, Response


@dataclass(frozen=True)
class CaseView:
    """单个案件在邀请—送达—回应—履约全链路上的归并视图。"""

    case_id: str
    grid: str
    service: str
    outcome: str
    closed_at: str | None
    invitation_count: int
    eligible: bool
    delivered: bool
    responded: bool
    # 当前有效评价；无有效评价时为 None（未知，不是零分）
    current_response_id: str | None
    current_score: int | None
    current_respondent: str | None
    current_channel: str | None
    current_received_at: str | None
    # 该案件全部评价（含已被更正的历史评价）
    all_response_ids: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    warnings: tuple[DataIssue, ...] = field(default_factory=tuple)


def _parse_chain_heads(
    responses: list[Response],
) -> tuple[list[Response], list[DataIssue]]:
    """返回更正链头部评价与解析警告（循环、链分裂等在此检测）。"""

    by_id = {resp.id: resp for resp in responses}
    superseded_ids = {resp.supersedes for resp in responses if resp.supersedes}
    heads = [resp for resp in responses if resp.id not in superseded_ids]
    issues: list[DataIssue] = []

    # 循环检测：从每条评价沿 supersedes 前进，超过节点数即成环。
    seen_chain: set[str] = set()
    for start in responses:
        chain: list[str] = []
        current: Response | None = start
        visited: set[str] = set()
        while current is not None:
            if current.id in visited:
                cycle = chain[chain.index(current.id) :] if current.id in chain else [current.id]
                key = "|".join(sorted(cycle))
                if key not in seen_chain:
                    seen_chain.add(key)
                    issues.append(
                        DataIssue(
                            "warning",
                            "supersede_cycle",
                            f"评价更正链存在循环（{' -> '.join(cycle)}），"
                            "链上评价均不能作为有效评价",
                            tuple(cycle),
                        )
                    )
                break
            visited.add(current.id)
            chain.append(current.id)
            current = by_id.get(current.supersedes) if current.supersedes else None

    if issues:
        # 成环链上的评价全部剔除，不参与头部选择。
        cycled_ids: set[str] = set()
        for issue in issues:
            cycled_ids.update(issue.refs)
        heads = [head for head in heads if head.id not in cycled_ids]
    return heads, issues


def build_case_views(dataset: Dataset) -> tuple[list[CaseView], list[DataIssue]]:
    """把四张表归并为案件级视图列表，并返回数据质量警告。"""

    issues: list[DataIssue] = []
    views: list[CaseView] = []

    for case in dataset.cases:
        invitations = sorted(dataset.invitations_for_case(case.id), key=lambda inv: inv.id)
        channels = tuple(dict.fromkeys(inv.channel for inv in invitations))
        local_warnings: list[DataIssue] = []

        eligible_invitations = [inv for inv in invitations if inv.eligible]
        delivered_invitations = [inv for inv in eligible_invitations if inv.delivered]
        eligible = bool(eligible_invitations)
        delivered = bool(delivered_invitations)

        # 收集该案件全部评价；区分“可进漏斗”的评价与异常评价。
        case_responses: list[Response] = []
        for inv in invitations:
            case_responses.extend(dataset.responses_for_invitation(inv.id))

        for resp in case_responses:
            inv = dataset.invitation_by_id(resp.invitation_id)
            assert inv is not None  # 引用完整性已在加载阶段保证
            if not inv.eligible:
                local_warnings.append(
                    DataIssue(
                        "warning",
                        "response_on_ineligible_invitation",
                        f"评价 {resp.id} 挂在不符合邀请条件的邀请 {inv.id} 下，"
                        "不计入回应分母",
                        (resp.id, inv.id),
                    )
                )
            elif not inv.delivered:
                local_warnings.append(
                    DataIssue(
                        "warning",
                        "response_on_undelivered_invitation",
                        f"评价 {resp.id} 挂在未送达的邀请 {inv.id} 下，"
                        "不计入送达与回应分母",
                        (resp.id, inv.id),
                    )
                )

        funnel_invitations = set(delivered_invitations)
        funnel_responses = [
            resp
            for resp in case_responses
            if (inv := dataset.invitation_by_id(resp.invitation_id)) in funnel_invitations
        ]

        heads, chain_issues = _parse_chain_heads(funnel_responses)
        for issue in chain_issues:
            local_warnings.append(issue)

        # 多链并存检测（多个头部意味着存在互不相连的评价链）
        if len(heads) > 1:
            local_warnings.append(
                DataIssue(
                    "warning",
                    "multiple_response_chains",
                    f"案件 {case.id} 存在 {len(heads)} 条相互独立的有效评价链，"
                    f"取收到时间最晚者（{max(heads, key=lambda r: r.received_at or r.id).id}），"
                    "该案件仍只计一票",
                    (case.id,),
                )
            )

        current: Response | None = None
        if heads:
            current = max(heads, key=lambda r: (r.received_at is not None, r.received_at or r.id))

        # 被更正的历史评价仅作事实留存，不再计入任何分布。
        superseded = {resp.supersedes for resp in funnel_responses if resp.supersedes}
        for resp_id in sorted(superseded):
            local_warnings.append(
                DataIssue(
                    "info",
                    "superseded_response",
                    f"评价 {resp_id} 已被后续评价更正，仅保留历史，不计入当前分布",
                    (resp_id,),
                )
            )

        current_inv = (
            dataset.invitation_by_id(current.invitation_id) if current is not None else None
        )
        views.append(
            CaseView(
                case_id=case.id,
                grid=case.grid,
                service=case.service,
                outcome=case.outcome,
                closed_at=case.closed_at.isoformat() if case.closed_at else None,
                invitation_count=len(invitations),
                eligible=eligible,
                delivered=delivered,
                responded=current is not None,
                current_response_id=current.id if current else None,
                current_score=current.score if current else None,
                current_respondent=current.respondent if current else None,
                current_channel=current_inv.channel if current_inv else None,
                current_received_at=(
                    current.received_at.isoformat() if current and current.received_at else None
                ),
                all_response_ids=tuple(resp.id for resp in case_responses),
                channels=channels,
                warnings=tuple(local_warnings),
            )
        )
        issues.extend(local_warnings)

    return views, issues
