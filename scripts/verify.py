#!/usr/bin/env python3
"""Independently reread every generated file and check syntax, uniqueness and counts."""
import argparse
import json
import hashlib
import sys
from pathlib import Path
from aggregate import ROOT, git, parse_readme, source_files, validate_rule


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "sources" / "ios_rule_script")
    args = parser.parse_args()
    report = json.loads((ROOT / "reports" / "summary.json").read_text(encoding="utf-8"))
    repo = args.source.resolve()
    if git(repo, "rev-parse", "HEAD") != report["source"]["commit"] or git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("上游提交或工作树与报告不一致")
    surge = repo / "rule" / "Surge"
    categories = parse_readme((surge / "README.md").read_text(encoding="utf-8"))
    if set(categories) != set(report["categories"]):
        raise ValueError("README 分类与报告不一致")
    generated = ROOT / "generated" / "surge"
    expected = {name + ".list" for name in report["categories"]}
    actual = {file.name for file in generated.glob("*.list")}
    if expected != actual:
        raise ValueError(f"生成文件不匹配: missing={expected - actual}; extra={actual - expected}")
    for name, stats in report["categories"].items():
        if categories[name] != stats["directories"]:
            raise ValueError(f"{name}: 来源目录与 README 不一致")
        missing = [directory for directory in categories[name] if not (surge / directory).is_dir() or not any((surge / directory).rglob("*.list"))]
        if missing != stats["missing_directories"]:
            raise ValueError(f"{name}: 缺失目录与报告不一致")
        available = [directory for directory in categories[name] if directory not in missing]
        actual_sources = ["rule/Surge/" + file.relative_to(surge).as_posix() for file in source_files(surge, available)]
        if actual_sources != [item["path"] for item in stats["sources"]] or len(actual_sources) != stats["file_count"]:
            raise ValueError(f"{name}: 来源文件清单不一致")
        for item in stats["sources"]:
            with (repo / item["path"]).open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                    raise ValueError(f"{name}: 来源 SHA-256 不匹配: {item['path']}")
        if sum(item["rules"] for item in stats["sources"]) != stats["before"]:
            raise ValueError(f"{name}: 来源规则数量不一致")
        seen = set()
        with (generated / (name + ".list")).open(encoding="utf-8") as source:
            for lineno, raw in enumerate(source, 1):
                line = raw.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                try:
                    validate_rule(line)
                except ValueError as exc:
                    raise ValueError(f"{name}.list:{lineno}: {exc}") from exc
                if line in seen:
                    raise ValueError(f"{name}.list:{lineno}: 重复规则")
                seen.add(line)
        if len(seen) != stats["after"] or stats["before"] - stats["duplicates"] != stats["after"]:
            raise ValueError(f"{name}: 规则数量不一致")
        print(f"{name}: {len(seen)} 条规则校验通过", flush=True)
    if not report["complete"]:
        print(f"规则语法和去重通过，但来源不完整: {report['missing_directories']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f"验证失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
