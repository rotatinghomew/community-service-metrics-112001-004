"""命令行入口。

用法：
    python -m community_feedback report --fixtures fixtures --format text
    python -m community_feedback report -f fixtures --format json -o report.json
    python -m community_feedback report -f fixtures --format html -o report.html
    python -m community_feedback validate -f fixtures
    python -m community_feedback cases -f fixtures          # 案件级链路明细（JSON）
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from .analysis import run_analysis
from .guards import DEFAULT_MIN_RESPONSE_RATE, DEFAULT_MIN_RESPONSES
from .loading import DataValidationError, load_dataset
from .reporting import render_html, render_json, render_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="community_feedback",
        description="居民反馈覆盖与服务体验分析（口径见 DATA.md）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "-f", "--fixtures", default="fixtures",
            help="资料目录（默认 fixtures）",
        )

    report = sub.add_parser("report", help="生成完整分析报告")
    add_common(report)
    report.add_argument(
        "--format", choices=("text", "json", "html"), default="text",
        help="输出格式（默认 text）",
    )
    report.add_argument("-o", "--output", help="输出文件；缺省输出到标准输出")
    report.add_argument(
        "--min-responses", type=int, default=DEFAULT_MIN_RESPONSES,
        help=f"最小有效评价票数（默认 {DEFAULT_MIN_RESPONSES}）",
    )
    report.add_argument(
        "--min-response-rate", type=float, default=DEFAULT_MIN_RESPONSE_RATE,
        help=f"最低回收率，0-1 之间（默认 {DEFAULT_MIN_RESPONSE_RATE}）",
    )

    validate = sub.add_parser("validate", help="只做资料结构校验")
    add_common(validate)

    cases = sub.add_parser("cases", help="输出案件级邀请—送达—回应—履约链路（JSON）")
    add_common(cases)
    return parser


def _emit(content: str, output: str | None) -> None:
    if output:
        Path(output).write_text(content, encoding="utf-8")
        print(f"已写入 {output}")
    else:
        try:
            sys.stdout.write(content + "\n")
        except BrokenPipeError:  # 管道场景（如 head）静默收尾
            sys.stderr.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            dataset, warnings = load_dataset(args.fixtures)
            print(f"结构校验通过：{len(dataset.cases)} 件案件、"
                  f"{len(dataset.invitations)} 次邀请、"
                  f"{len(dataset.responses)} 条评价、"
                  f"{len(dataset.periods)} 个时期。")
            for issue in warnings:
                print(f"[{issue.level}] {issue.code}: {issue.message}")
            return 0

        if args.command == "cases":
            analysis = run_analysis(args.fixtures)
            import json
            _emit(
                json.dumps([asdict(view) for view in analysis.views],
                           ensure_ascii=False, indent=2),
                None,
            )
            return 0

        if args.command == "report":
            if args.min_responses < 1:
                parser.error("--min-responses 必须 >= 1")
            if not 0 < args.min_response_rate <= 1:
                parser.error("--min-response-rate 必须在 (0, 1] 之间，例如 0.5 表示 50%")
            analysis = run_analysis(
                args.fixtures,
                min_responses=args.min_responses,
                min_response_rate=args.min_response_rate,
            )
            renderer = {
                "text": render_text,
                "json": render_json,
                "html": render_html,
            }[args.format]
            _emit(renderer(analysis), args.output)
            return 0

    except DataValidationError as exc:
        print("资料结构校验失败：", file=sys.stderr)
        for issue in exc.issues:
            print(f"  [{issue.level}] {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"找不到资料：{exc}", file=sys.stderr)
        return 2

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
