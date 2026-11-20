"""资料加载与结构校验。

校验分两类：

* 错误（error）：字段缺失、类型/取值非法、引用悬空等结构性问题，
  收集齐全后抛出 :class:`DataValidationError`。
* 警告（warning）：语义异常但仍可分析的情形（如不符合邀请条件却标记送达、
  评价挂在未送达邀请下），交由后续分析环节隔离并提示。

空字符串仅在可空字段（日期、``supersedes``）合法，含义是“来源未给出”。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from .models import (
    Case,
    DataIssue,
    DataValidationError,
    Dataset,
    Invitation,
    Period,
    Response,
)

_BOOL_TEXT = {"yes": True, "no": False}
_DATE_FIELDS = frozenset({"closed_at", "sent_at", "received_at", "start", "end"})
# 每张表的必备字段；顺序同时用于错误提示。
_TABLE_FIELDS: dict[str, tuple[str, ...]] = {
    "cases.json": ("id", "grid", "service", "closed_at", "outcome"),
    "invitations.json": ("id", "case", "channel", "eligible", "delivered", "sent_at"),
    "responses.json": ("id", "invitation", "respondent", "score", "received_at", "supersedes"),
    "periods.json": ("id", "start", "end", "sampling"),
}


def _parse_date(value: str, *, field: str, ref: str, errors: list[DataIssue]) -> date | None:
    if value == "":
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        errors.append(
            DataIssue("error", "bad_date", f"{ref} 的字段 {field} 日期格式非法: {value!r}", (ref,))
        )
        return None


def _read_table(path: Path, errors: list[DataIssue]) -> list[dict]:
    if not path.exists():
        errors.append(DataIssue("error", "missing_file", f"缺少资料文件 {path.name}", (path.name,)))
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(
            DataIssue("error", "bad_json", f"{path.name} 不是合法 JSON: {exc.msg}", (path.name,))
        )
        return []
    if not isinstance(raw, list):
        errors.append(DataIssue("error", "bad_shape", f"{path.name} 顶层必须是数组", (path.name,)))
        return []
    return raw


def _check_fields(
    table_name: str, records: list[dict], errors: list[DataIssue]
) -> list[dict]:
    required = _TABLE_FIELDS[table_name]
    valid: list[dict] = []
    for index, record in enumerate(records):
        ref = f"{table_name}[{index}]"
        if not isinstance(record, dict):
            errors.append(DataIssue("error", "bad_record", f"{ref} 不是对象", (ref,)))
            continue
        missing = [field for field in required if field not in record]
        if missing:
            errors.append(
                DataIssue(
                    "error",
                    "missing_field",
                    f"{ref} 缺少字段: {', '.join(missing)}",
                    (ref,),
                )
            )
            continue
        valid.append(record)
    return valid


def load_dataset(fixtures_dir: str | Path) -> tuple[Dataset, list[DataIssue]]:
    """从目录加载四张表，返回数据集与非阻断性问题列表。

    阻断性错误累积后一次性抛出 :class:`DataValidationError`。
    """

    fixtures_dir = Path(fixtures_dir)
    errors: list[DataIssue] = []
    warnings: list[DataIssue] = []

    raw_tables = {
        name: _check_fields(name, _read_table(fixtures_dir / name, errors), errors)
        for name in _TABLE_FIELDS
    }
    if errors:
        raise DataValidationError(errors)

    # ---- cases -----------------------------------------------------------
    cases: list[Case] = []
    case_ids: set[str] = set()
    for record in raw_tables["cases.json"]:
        ref = record["id"]
        if not isinstance(ref, str) or not ref:
            errors.append(DataIssue("error", "bad_id", "存在空的案件 id"))
            continue
        if ref in case_ids:
            errors.append(DataIssue("error", "duplicate_id", f"案件 id 重复: {ref}", (ref,)))
            continue
        case_ids.add(ref)
        cases.append(
            Case(
                id=ref,
                grid=str(record["grid"]),
                service=str(record["service"]),
                closed_at=_parse_date(record["closed_at"], field="closed_at", ref=ref, errors=errors),
                outcome=str(record["outcome"]),
            )
        )

    # ---- invitations -----------------------------------------------------
    invitations: list[Invitation] = []
    invitation_ids: set[str] = set()
    for record in raw_tables["invitations.json"]:
        ref = record["id"]
        if not isinstance(ref, str) or not ref:
            errors.append(DataIssue("error", "bad_id", "存在空的邀请 id"))
            continue
        if ref in invitation_ids:
            errors.append(DataIssue("error", "duplicate_id", f"邀请 id 重复: {ref}", (ref,)))
            continue
        invitation_ids.add(ref)
        if record["case"] not in case_ids:
            errors.append(
                DataIssue(
                    "error",
                    "dangling_ref",
                    f"邀请 {ref} 引用了不存在的案件 {record['case']}",
                    (ref, record["case"]),
                )
            )
            continue
        eligible_text = str(record["eligible"]).strip().lower()
        delivered_text = str(record["delivered"]).strip().lower()
        if eligible_text not in _BOOL_TEXT:
            errors.append(
                DataIssue(
                    "error", "bad_enum", f"邀请 {ref} 的 eligible 取值非法: {record['eligible']!r}", (ref,)
                )
            )
            continue
        if delivered_text not in _BOOL_TEXT:
            errors.append(
                DataIssue(
                    "error", "bad_enum", f"邀请 {ref} 的 delivered 取值非法: {record['delivered']!r}", (ref,)
                )
            )
            continue
        eligible, delivered = _BOOL_TEXT[eligible_text], _BOOL_TEXT[delivered_text]
        invitation = Invitation(
            id=ref,
            case_id=record["case"],
            channel=str(record["channel"]),
            eligible=eligible,
            delivered=delivered,
            sent_at=_parse_date(record["sent_at"], field="sent_at", ref=ref, errors=errors),
        )
        if not eligible and delivered:
            warnings.append(
                DataIssue(
                    "warning",
                    "ineligible_but_delivered",
                    f"邀请 {ref} 标记为不符合邀请条件却已送达，该条不计入邀请分母，"
                    "仅保留原始事实供核查",
                    (ref,),
                )
            )
        invitations.append(invitation)

    # ---- responses -------------------------------------------------------
    responses: list[Response] = []
    response_ids: set[str] = set()
    for record in raw_tables["responses.json"]:
        ref = record["id"]
        if not isinstance(ref, str) or not ref:
            errors.append(DataIssue("error", "bad_id", "存在空的评价 id"))
            continue
        if ref in response_ids:
            errors.append(DataIssue("error", "duplicate_id", f"评价 id 重复: {ref}", (ref,)))
            continue
        response_ids.add(ref)
        if record["invitation"] not in invitation_ids:
            errors.append(
                DataIssue(
                    "error",
                    "dangling_ref",
                    f"评价 {ref} 引用了不存在的邀请 {record['invitation']}",
                    (ref, record["invitation"]),
                )
            )
            continue
        score = record["score"]
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            errors.append(
                DataIssue("error", "bad_score", f"评价 {ref} 的分值必须是 1-5 的整数: {score!r}", (ref,))
            )
            continue
        supersedes = record["supersedes"]
        if not isinstance(supersedes, str):
            errors.append(
                DataIssue("error", "bad_field", f"评价 {ref} 的 supersedes 必须是字符串", (ref,))
            )
            continue
        supersedes = supersedes or None
        responses.append(
            Response(
                id=ref,
                invitation_id=record["invitation"],
                respondent=str(record["respondent"]),
                score=score,
                received_at=_parse_date(
                    record["received_at"], field="received_at", ref=ref, errors=errors
                ),
                supersedes=supersedes,
            )
        )

    # supersedes 引用完整性（循环链在 feedback 解析时检测）
    for resp in responses:
        if resp.supersedes is not None and resp.supersedes not in response_ids:
            errors.append(
                DataIssue(
                    "error",
                    "dangling_ref",
                    f"评价 {resp.id} 的 supersedes 指向不存在的评价 {resp.supersedes}",
                    (resp.id, resp.supersedes),
                )
            )

    # ---- periods ---------------------------------------------------------
    periods: list[Period] = []
    period_ids: set[str] = set()
    for record in raw_tables["periods.json"]:
        ref = record["id"]
        if ref in period_ids:
            errors.append(DataIssue("error", "duplicate_id", f"时期 id 重复: {ref}", (ref,)))
            continue
        period_ids.add(ref)
        start = _parse_date(record["start"], field="start", ref=ref, errors=errors)
        end = _parse_date(record["end"], field="end", ref=ref, errors=errors)
        if start and end and end <= start:
            errors.append(DataIssue("error", "bad_range", f"时期 {ref} 的结束日期必须晚于开始日期", (ref,)))
        if start and end:
            periods.append(Period(id=ref, start=start, end=end, sampling=str(record["sampling"])))

    if errors:
        raise DataValidationError(errors)

    dataset = Dataset(cases, invitations, responses, periods)
    return dataset, warnings
