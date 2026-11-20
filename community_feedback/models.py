"""领域模型与数据容器。

原始资料中的空字符串统一转换为 ``None``：来源没有给出该事实，不等同于零、
否或业务终态（见 DATA.md）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Case:
    """服务事项（案件），分析的基本单位。"""

    id: str
    grid: str
    service: str
    closed_at: date | None
    outcome: str


@dataclass(frozen=True)
class Invitation:
    """一次评价邀请。同一案件可能有多次邀请（渠道可能不同）。"""

    id: str
    case_id: str
    channel: str
    eligible: bool
    delivered: bool
    sent_at: date | None


@dataclass(frozen=True)
class Response:
    """一条居民评价；``supersedes`` 指向被其更正的旧评价。"""

    id: str
    invitation_id: str
    respondent: str
    score: int
    received_at: date | None
    supersedes: str | None


@dataclass(frozen=True)
class Period:
    """统计时期及其抽样框架标识。"""

    id: str
    start: date
    end: date
    sampling: str


@dataclass(frozen=True)
class DataIssue:
    """数据质量提示。

    level 取值：``error`` 表示结构性错误（资料无法据此分析）；
    ``warning`` 表示语义异常（可继续分析，但相关记录须隔离或提示）。
    """

    level: str
    code: str
    message: str
    refs: tuple[str, ...] = ()


class DataValidationError(Exception):
    """资料存在结构性错误时抛出，携带全部错误级问题。"""

    def __init__(self, issues: list[DataIssue]):
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


class Dataset:
    """四张表的只读容器，附带按标识建索引的访问器。"""

    def __init__(
        self,
        cases: list[Case],
        invitations: list[Invitation],
        responses: list[Response],
        periods: list[Period],
    ) -> None:
        self.cases = cases
        self.invitations = invitations
        self.responses = responses
        self.periods = periods
        self._cases = {case.id: case for case in cases}
        self._invitations = {inv.id: inv for inv in invitations}
        self._responses = {resp.id: resp for resp in responses}
        self._invitations_by_case: dict[str, list[Invitation]] = {}
        for inv in invitations:
            self._invitations_by_case.setdefault(inv.case_id, []).append(inv)
        self._responses_by_invitation: dict[str, list[Response]] = {}
        for resp in responses:
            self._responses_by_invitation.setdefault(resp.invitation_id, []).append(resp)

    def case_by_id(self, case_id: str) -> Case | None:
        return self._cases.get(case_id)

    def invitation_by_id(self, invitation_id: str) -> Invitation | None:
        return self._invitations.get(invitation_id)

    def response_by_id(self, response_id: str) -> Response | None:
        return self._responses.get(response_id)

    def invitations_for_case(self, case_id: str) -> list[Invitation]:
        return list(self._invitations_by_case.get(case_id, ()))

    def responses_for_invitation(self, invitation_id: str) -> list[Response]:
        return list(self._responses_by_invitation.get(invitation_id, ()))
