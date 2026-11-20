"""报告渲染：文本（控制台）、JSON、自包含 HTML。

所有动态内容在 HTML 中均经转义；文本表格按显示宽度对齐（中日韩字符按双宽
计算）。JSON 输出为可直接复查的纯数据结构，不夹带渲染格式。
"""

from __future__ import annotations

import html
import json
import unicodedata
from dataclasses import asdict
from typing import Any

from .analysis import Analysis
from .guards import FRAME_REGISTRY
from .metrics import GroupMetrics

_DIMENSION_LABELS = {
    "overall": "总体",
    "grid": "网格",
    "service": "服务类别",
    "period": "时期",
}


# --------------------------------------------------------------------------- #
# 通用辅助
# --------------------------------------------------------------------------- #
def _display_width(text: Any) -> int:
    return sum(
        2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        for ch in str(text)
    )


def _pad(text: Any, width: int, align: str = "left") -> str:
    text = str(text)
    gap = width - _display_width(text)
    if gap <= 0:
        return text
    return text + " " * gap if align == "left" else " " * gap + text


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _num(value: float | int | None) -> str:
    return "—" if value is None else str(value)


def _mean(value: float | None) -> str:
    return "未知" if value is None else f"{value:.2f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [_display_width(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], _display_width(cell))
    border = "-" * (sum(widths) + 3 * (len(widths) - 1))
    lines = [
        "  ".join(_pad(header, widths[index]) for index, header in enumerate(headers)),
        border,
    ]
    for row in rows:
        lines.append(
            "  ".join(_pad(cell, widths[index]) for index, cell in enumerate(row))
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #
def to_dict(analysis: Analysis) -> dict[str, Any]:
    data = asdict(analysis)
    data["frame_registry"] = {code: asdict(info) for code, info in FRAME_REGISTRY.items()}
    return data


def render_json(analysis: Analysis) -> str:
    return json.dumps(to_dict(analysis), ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# 文本报告
# --------------------------------------------------------------------------- #
def _issues_block(analysis: Analysis) -> list[str]:
    lines = ["一、数据质量与口径提示"]
    if not analysis.issues:
        lines.append("  （无）")
        return lines
    for issue in analysis.issues:
        refs = f"（{', '.join(issue.refs)}）" if issue.refs else ""
        lines.append(f"  [{issue.level}] {issue.code}: {issue.message}{refs}")
    return lines


def _case_detail_block(analysis: Analysis) -> list[str]:
    headers = [
        "案件", "网格", "服务", "符合邀请", "实际送达", "已评价",
        "有效评分", "办理结果", "办结时间", "渠道",
    ]
    rows = []
    for view in analysis.views:
        rows.append(
            [
                view.case_id,
                view.grid,
                view.service,
                "是" if view.eligible else "否",
                "是" if view.delivered else "否",
                "是" if view.responded else "否",
                _num(view.current_score) if view.responded else "未知",
                view.outcome,
                view.closed_at or "未办结",
                ",".join(view.channels) if view.channels else "—",
            ]
        )
    return ["二、案件级链路明细（未评价评分为“未知”，不是零分）", _table(headers, rows)]


def _funnel_rows(groups: list[GroupMetrics]) -> tuple[list[str], list[list[str]]]:
    headers = [
        "组别", "案件数", "符合邀请", "实际送达", "已评价", "未回应·未知",
        "未纳入邀请", "送达率", "回收率", "覆盖率",
    ]
    rows = []
    for group in groups:
        funnel = group.funnel
        rows.append(
            [
                group.key,
                str(funnel.cases),
                str(funnel.eligible),
                str(funnel.delivered),
                str(funnel.responded),
                str(funnel.unknown),
                str(funnel.not_invited),
                _pct(funnel.delivery_rate),
                _pct(funnel.response_rate_eligible),
                _pct(funnel.coverage_rate),
            ]
        )
    return headers, rows


def _rating_rows(analysis: Analysis, groups: list[GroupMetrics], dimension: str) -> tuple[list[str], list[list[str]]]:
    headers = [
        "组别", "票数", "平均分", "1分", "2分", "3分", "4分", "5分",
        "不满≤2", "中性3", "满意≥4", "已办结率", "完结占比", "排名资格",
    ]
    rows = []
    for group in groups:
        verdict = analysis.verdict_for(dimension, group.key)
        rating = group.rating
        fulfillment = group.fulfillment
        rows.append(
            [
                group.key,
                str(rating.rated_cases),
                _mean(rating.mean),
                *[str(rating.distribution[score]) for score in range(1, 6)],
                str(rating.negative),
                str(rating.neutral),
                str(rating.positive),
                _pct(fulfillment.closed_rate),
                _pct(fulfillment.completion_rate),
                "可排名" if verdict and verdict.rank_allowed else "受限",
            ]
        )
    return headers, rows


def _group_blocks(analysis: Analysis) -> list[str]:
    lines = ["三、分组比较：覆盖漏斗、评价分布与独立履约"]
    for dimension in ("grid", "service", "period", "overall"):
        groups = analysis.grouped_metrics[dimension]
        label = _DIMENSION_LABELS[dimension]
        lines.append(f"【按{label}】覆盖与漏斗（回收率=已评价/符合邀请；覆盖率=已评价/全部案件）")
        headers, rows = _funnel_rows(groups)
        lines.append(_table(headers, rows))
        lines.append(f"【按{label}】评价分布与履约（完结占比=completed/已办结；未回应不进分布）")
        headers, rows = _rating_rows(analysis, groups, dimension)
        lines.append(_table(headers, rows))
        lines.append("")
    return lines


def _drift_block(analysis: Analysis) -> list[str]:
    lines = ["四、样本构成与跨期可比性"]
    for period_id, sampling in analysis.period_sampling.items():
        frame = FRAME_REGISTRY.get(sampling)
        frame_label = frame.label if frame else "未登记框架"
        mix = analysis.period_channel_mix.get(period_id, {})
        mix_text = ", ".join(f"{channel} {count}案" for channel, count in mix.items()) or "无邀请记录"
        lines.append(f"  {period_id}: 框架={sampling}（{frame_label}）；渠道构成：{mix_text}")
    if analysis.drifts:
        lines.append("  跨期变化：")
        for drift in analysis.drifts:
            lines.append(f"  - [{drift.kind}] {drift.left_period} → {drift.right_period}：{drift.detail}")
    else:
        lines.append("  相邻时期框架与渠道集合未发生变化。")
    return lines


def _guard_block(analysis: Analysis) -> list[str]:
    lines = ["五、推断限制（逐组说明；受限组只给描述性统计，不进入排名）"]
    any_limited = False
    for dimension in ("overall", "grid", "service", "period"):
        for verdict in analysis.verdicts[dimension]:
            label = _DIMENSION_LABELS[dimension]
            if verdict.rank_allowed:
                target = f"，推断目标：{verdict.frame_target}" if verdict.frame_target else ""
                lines.append(f"  [{label}] {verdict.group_key}: 通过推断守卫{target}")
            else:
                any_limited = True
                lines.append(f"  [{label}] {verdict.group_key}: 限制结论，不参与排名")
                for reason in verdict.reasons:
                    lines.append(f"      · {reason}")
            for note in verdict.notes:
                lines.append(f"      注：{note}")
    if not any_limited:
        lines.append("  （所有组均通过守卫）")
    return lines


def _ranking_block(analysis: Analysis) -> list[str]:
    lines = ["六、满意度排名（仅限通过推断守卫的组；其余组的平均分仅为描述性统计）"]
    for dimension in ("overall", "grid", "service", "period"):
        label = _DIMENSION_LABELS[dimension]
        entries = analysis.rankings[dimension]
        lines.append(f"【按{label}】")
        if not entries:
            lines.append("  无组通过推断守卫，不生成排名。")
            continue
        for entry in entries:
            lines.append(
                f"  {entry['rank']}. {entry['group_key']}  平均分 {entry['mean']:.2f}"
                f"（{entry['rated_cases']} 票；适用总体：{entry['frame_target']}）"
            )
    return lines


def render_text(analysis: Analysis) -> str:
    title = "居民反馈覆盖与服务体验分析报告"
    header = [
        title,
        "=" * _display_width(title),
        f"资料目录: {analysis.fixtures_dir}    案件总数: {analysis.total_cases}",
        (
            f"推断门槛: 最少有效评价 {analysis.min_responses} 票、"
            f"最低回收率 {analysis.min_response_rate:.0%}；"
            "未回应一律按未知处理，不计零分"
        ),
        "",
    ]
    blocks = [
        header,
        _issues_block(analysis),
        [""],
        _case_detail_block(analysis),
        [""],
        _group_blocks(analysis),
        _drift_block(analysis),
        [""],
        _guard_block(analysis),
        [""],
        _ranking_block(analysis),
    ]
    return "\n".join(line for block in blocks for line in block)


# --------------------------------------------------------------------------- #
# HTML（自包含，无外部依赖）
# --------------------------------------------------------------------------- #
_CSS = """
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       margin: 2rem; color: #1f2933; background: #fafbfc; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 1.8rem;
     border-left: 4px solid #3b6ea5; padding-left: .5rem; }
table { border-collapse: collapse; margin: .6rem 0 1.2rem; background: #fff;
        font-size: .86rem; }
th, td { border: 1px solid #d6dbe0; padding: .35rem .6rem; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { background: #eef2f6; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 10px;
         font-size: .78rem; }
.ok { background: #e3f4e8; color: #1d6f3c; }
.limited { background: #fdecec; color: #a33; }
.warn { background: #fff6e0; color: #8a6116; }
.info { background: #eef2f6; color: #445; }
ul { margin: .4rem 0; } li { margin: .25rem 0; }
.meta { color: #52606d; font-size: .9rem; }
.drift { background: #fff; border: 1px solid #e0c68a; padding: .6rem 1rem;
         border-radius: 6px; }
code { background: #eef2f6; padding: 0 .25rem; border-radius: 3px; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _html_table(
    headers: list[str],
    rows: list[list[str]],
    badge_cols: dict[int, str] | None = None,
    badge_cell_class: dict[tuple[int, str], str] | None = None,
) -> str:
    badge_cols = badge_cols or {}
    badge_cell_class = badge_cell_class or {}
    parts = ["<table>", "<tr>"]
    parts.extend(f"<th>{_esc(h)}</th>" for h in headers)
    parts.append("</tr>")
    for row in rows:
        parts.append("<tr>")
        for index, cell in enumerate(row):
            if index in badge_cols:
                css = badge_cell_class.get((index, cell), badge_cols[index])
                parts.append(f'<td><span class="badge {css}">{_esc(cell)}</span></td>')
            else:
                parts.append(f"<td>{_esc(cell)}</td>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def render_html(analysis: Analysis) -> str:
    out: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        "<title>居民反馈覆盖与服务体验分析报告</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>居民反馈覆盖与服务体验分析报告</h1>",
        f'<p class="meta">资料目录：{_esc(analysis.fixtures_dir)} ｜ 案件总数：{analysis.total_cases} ｜ '
        f"推断门槛：最少有效评价 {analysis.min_responses} 票、最低回收率 "
        f"{analysis.min_response_rate:.0%} ｜ 未回应按未知处理，不计零分</p>",
    ]

    # 数据质量
    out.append("<h2>一、数据质量与口径提示</h2>")
    if analysis.issues:
        out.append("<ul>")
        for issue in analysis.issues:
            refs = f"（{_esc(', '.join(issue.refs))}）" if issue.refs else ""
            css = "warn" if issue.level == "warning" else "info"
            out.append(
                f'<li><span class="badge {css}">{_esc(issue.level)}</span> '
                f"<code>{_esc(issue.code)}</code> {_esc(issue.message)}{refs}</li>"
            )
        out.append("</ul>")
    else:
        out.append('<p class="meta">（无）</p>')

    # 案件明细
    out.append("<h2>二、案件级链路明细</h2>")
    headers = ["案件", "网格", "服务", "符合邀请", "实际送达", "已评价", "有效评分", "办理结果", "办结时间", "渠道"]
    rows = []
    for view in analysis.views:
        rows.append([
            view.case_id, view.grid, view.service,
            "是" if view.eligible else "否",
            "是" if view.delivered else "否",
            "是" if view.responded else "否",
            str(view.current_score) if view.responded else "未知",
            view.outcome, view.closed_at or "未办结",
            ",".join(view.channels) if view.channels else "—",
        ])
    out.append(_html_table(headers, rows))

    # 分组
    out.append("<h2>三、分组比较</h2>")
    for dimension in ("grid", "service", "period", "overall"):
        groups = analysis.grouped_metrics[dimension]
        out.append(f"<h3>按{_esc(_DIMENSION_LABELS[dimension])}</h3>")
        funnel_headers, funnel_rows = _funnel_rows(groups)
        out.append(_html_table(funnel_headers, funnel_rows))
        rating_headers, rating_rows = _rating_rows(analysis, groups, dimension)
        last_col = len(rating_headers) - 1
        out.append(
            _html_table(
                rating_headers,
                rating_rows,
                badge_cols={last_col: "ok"},
                badge_cell_class={(last_col, "受限"): "limited"},
            )
        )

    # 漂移
    out.append("<h2>四、样本构成与跨期可比性</h2><div class=\"drift\"><ul>")
    for period_id, sampling in analysis.period_sampling.items():
        frame = FRAME_REGISTRY.get(sampling)
        frame_label = frame.label if frame else "未登记框架"
        mix = analysis.period_channel_mix.get(period_id, {})
        mix_text = ", ".join(f"{c} {n}案" for c, n in mix.items()) or "无邀请记录"
        out.append(
            f"<li>{_esc(period_id)}：框架 <code>{_esc(sampling)}</code>"
            f"（{_esc(frame_label)}）；渠道构成：{_esc(mix_text)}</li>"
        )
    if analysis.drifts:
        for drift in analysis.drifts:
            out.append(f"<li><strong>{_esc(drift.kind)}</strong>：{_esc(drift.detail)}</li>")
    out.append("</ul></div>")

    # 守卫
    out.append("<h2>五、推断限制</h2><ul>")
    for dimension in ("overall", "grid", "service", "period"):
        for verdict in analysis.verdicts[dimension]:
            label = _DIMENSION_LABELS[dimension]
            if verdict.rank_allowed:
                out.append(
                    f'<li><span class="badge ok">可排名</span> [{_esc(label)}] '
                    f"{_esc(verdict.group_key)}（推断目标：{_esc(verdict.frame_target or '—')}）</li>"
                )
            else:
                out.append(
                    f'<li><span class="badge limited">受限</span> [{_esc(label)}] '
                    f"{_esc(verdict.group_key)}<ul>"
                )
                for reason in verdict.reasons:
                    out.append(f"<li>{_esc(reason)}</li>")
                for note in verdict.notes:
                    out.append(f'<li class="meta">{_esc(note)}</li>')
                out.append("</ul></li>")
    out.append("</ul>")

    # 排名
    out.append("<h2>六、满意度排名（仅限通过推断守卫的组）</h2>")
    for dimension in ("overall", "grid", "service", "period"):
        entries = analysis.rankings[dimension]
        out.append(f"<h3>按{_esc(_DIMENSION_LABELS[dimension])}</h3>")
        if not entries:
            out.append('<p class="meta">无组通过推断守卫，不生成排名；平均分仅为描述性统计。</p>')
            continue
        out.append("<ol>")
        for entry in entries:
            out.append(
                f"<li>{_esc(entry['group_key'])}：平均分 {entry['mean']:.2f}"
                f"（{entry['rated_cases']} 票；适用总体：{_esc(entry['frame_target'])}）</li>"
            )
        out.append("</ol>")

    out.append("</body></html>")
    return "".join(out)
