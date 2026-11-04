#!/usr/bin/env python3
"""Aggregate upstream Surge README category tables without altering upstream."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/blackmatrix7/ios_rule_script"
HEADER = re.compile(r"^\|\s*([^|\[\]]+?)\s*\|(?:\s*\|)+\s*$")
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
NAME = re.compile(r"([A-Za-z][A-Za-z0-9_-]*)$")
SIMPLE = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "USER-AGENT", "PROCESS-NAME", "URL-REGEX"}
NETWORK = {"IP-CIDR", "IP-CIDR6", "IP-ASN"}


def parse_readme(content: str) -> dict[str, list[str]]:
    """Read category table headings and all rule-directory links, in source order."""
    categories: dict[str, list[str]] = {}
    current: str | None = None
    in_section = False
    for lineno, line in enumerate(content.splitlines(), 1):
        if re.match(r"^##\s+分类\s*$", line):
            in_section = True
            continue
        if in_section and re.match(r"^#{1,2}\s+", line):
            break
        if not in_section:
            continue
        match = HEADER.match(line)
        if match:
            name_match = NAME.search(match.group(1).strip())
            if not name_match:
                raise ValueError(f"README:{lineno}: 无法识别分类名称")
            current = name_match.group(1)
            if current in categories:
                raise ValueError(f"README:{lineno}: 分类重复: {current}")
            categories[current] = []
            continue
        for target in LINK.findall(line):
            url = urlsplit(target)
            marker = "/rule/Surge/"
            if marker not in url.path:
                continue
            if current is None or url.netloc.lower() != "github.com" or not url.path.startswith("/blackmatrix7/ios_rule_script/tree/"):
                raise ValueError(f"README:{lineno}: 不支持的规则链接: {target}")
            directory = unquote(url.path.split(marker, 1)[1]).rstrip("/")
            parts = directory.split("/")
            if any(not part or part in {".", ".."} or re.search(r"[\x00-\x1f\\]", part) for part in parts):
                raise ValueError(f"README:{lineno}: 无效规则目录: {target}")
            if directory not in categories[current]:
                categories[current].append(directory)
    if not categories:
        raise ValueError("README 中未发现分类表格")
    for category, dirs in categories.items():
        if not dirs:
            raise ValueError(f"分类 {category} 没有可识别的规则目录")
    return categories


def validate_rule(line: str) -> None:
    """Validate supported upstream RULE-SET syntax, retaining all parameters."""
    kind, sep, value = line.partition(",")
    if not sep or not value or line != line.strip():
        raise ValueError("缺少规则类型或内容")
    if kind in SIMPLE:
        if kind != "URL-REGEX" and "," in value:
            raise ValueError("不支持的额外参数")
        if kind.startswith("DOMAIN") and any(c.isspace() for c in value):
            raise ValueError("域名规则包含空白")
    elif kind in NETWORK:
        fields = value.split(",")
        if len(fields) > 2 or (len(fields) == 2 and fields[1] != "no-resolve"):
            raise ValueError("无效的 IP/ASN 参数")
        if kind == "IP-ASN":
            if not fields[0].isdigit():
                raise ValueError("无效的 ASN")
        else:
            network = ipaddress.ip_network(fields[0], strict=False)
            if network.version != (4 if kind == "IP-CIDR" else 6):
                raise ValueError("IP 地址族不匹配")
    elif kind in {"AND", "OR", "NOT"}:
        if not (value.startswith("((") and value.endswith("))")):
            raise ValueError("逻辑规则结构无效")
        inner = value[1:-1]
        pos = 0
        count = 0
        while pos < len(inner):
            if inner[pos] != "(":
                raise ValueError("逻辑子规则结构无效")
            start = pos + 1
            depth = 1
            pos += 1
            while pos < len(inner) and depth:
                if inner[pos] == "(":
                    depth += 1
                elif inner[pos] == ")":
                    depth -= 1
                pos += 1
            if depth:
                raise ValueError("逻辑规则括号不匹配")
            validate_rule(inner[start:pos - 1])
            count += 1
            if pos < len(inner):
                if inner[pos] != ",":
                    raise ValueError("逻辑子规则分隔符无效")
                pos += 1
                if pos == len(inner):
                    raise ValueError("逻辑规则结尾无效")
        if (kind == "NOT" and count != 1) or (kind in {"AND", "OR"} and count < 2):
            raise ValueError("逻辑子规则数量无效")
    else:
        raise ValueError(f"不支持的规则类型: {kind}")


def normalize_source_line(line: str, filename: str) -> tuple[str, bool]:
    """Convert upstream DOMAIN-SET variants to equivalent RULE-SET declarations."""
    if "," not in line and filename.endswith("_Domain.list"):
        suffix = line.startswith(".")
        host = line[1:] if suffix else line
        if not host or re.search(r"[\s/*]", host):
            raise ValueError("DOMAIN-SET 域名无效")
        return ("DOMAIN-SUFFIX," if suffix else "DOMAIN,") + host, True
    return line, False


def source_files(surge: Path, directories: list[str]) -> list[Path]:
    result: list[Path] = []
    encountered: set[Path] = set()
    for name in directories:
        directory = surge / name
        if directory.is_symlink() or not directory.is_dir():
            raise FileNotFoundError(f"规则目录不存在或为符号链接: {directory}")
        files = sorted(directory.rglob("*.list"))
        if not files:
            raise FileNotFoundError(f"规则目录没有 .list 文件: {directory}")
        for file in files:
            if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(directory.resolve()):
                raise ValueError(f"无效规则文件: {file}")
            if file not in encountered:
                encountered.add(file)
                result.append(file)
    return result


def aggregate_category(surge: Path, directories: list[str], output: Path, metadata: dict) -> dict:
    seen: set[str] = set()
    sources = []
    total = 0
    converted_total = 0
    with output.open("w", encoding="utf-8", newline="\n") as dest:
        dest.write(f"# Source: {REPO_URL}\n# Branch: {metadata['branch']}\n# Commit: {metadata['commit']}\n")
        if metadata.get("missing_directories"):
            dest.write("# INCOMPLETE: missing upstream directories: " + ", ".join(metadata["missing_directories"]) + "\n")
        for file in source_files(surge, directories):
            relative = file.relative_to(surge).as_posix()
            count = 0
            converted = 0
            digest = hashlib.sha256()
            try:
                with file.open("rb") as source:
                    for lineno, raw in enumerate(source, 1):
                        digest.update(raw)
                        line = raw.decode("utf-8-sig" if lineno == 1 else "utf-8").strip()
                        if not line or line.startswith(("#", "//", ";")):
                            continue
                        try:
                            line, was_converted = normalize_source_line(line, file.name)
                            validate_rule(line)
                        except ValueError as exc:
                            raise ValueError(f"{relative}:{lineno}: {exc}: {line[:180]}") from exc
                        count += 1
                        total += 1
                        converted += was_converted
                        converted_total += was_converted
                        if line not in seen:
                            seen.add(line)
                            dest.write(line + "\n")
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"读取失败 {relative}: {exc}") from exc
            sources.append({"path": f"rule/Surge/{relative}", "sha256": digest.hexdigest(), "rules": count, "domain_set_converted": converted})
    return {"directory_count": len(directories), "file_count": len(sources), "before": total,
            "duplicates": total - len(seen), "after": len(seen), "domain_set_converted": converted_total,
            "directories": directories, "sources": sources}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def run(repo: Path, root: Path, allow_missing: bool = False) -> dict:
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("上游工作区有未提交或未跟踪文件，无法保证结果对应 commit")
    metadata = {"repository": REPO_URL, "branch": git(repo, "branch", "--show-current") or "DETACHED",
                "commit": git(repo, "rev-parse", "HEAD"), "generated_at_utc": datetime.now(timezone.utc).isoformat()}
    surge = repo / "rule" / "Surge"
    categories = parse_readme((surge / "README.md").read_text(encoding="utf-8"))
    missing: dict[str, list[str]] = {}
    for name, dirs in categories.items():
        for directory in dirs:
            candidate = surge / directory
            if candidate.is_symlink():
                raise ValueError(f"规则目录是符号链接: {candidate}")
            if not candidate.is_dir() or not any(candidate.rglob("*.list")):
                missing.setdefault(name, []).append(directory)
    if missing and not allow_missing:
        details = "; ".join(f"{name}: {', '.join(dirs)}" for name, dirs in missing.items())
        raise ValueError(f"README 引用的目录缺失或没有 .list: {details}")
    tracked = set(git(repo, "ls-files", "-z", "--", "rule/Surge").split("\0"))
    for name, dirs in categories.items():
        available = [directory for directory in dirs if directory not in missing.get(name, [])]
        for file in source_files(surge, available):
            relative = file.relative_to(repo).as_posix()
            if relative not in tracked:
                raise ValueError(f"{name}: 来源文件不属于上游 Git 提交: {relative}")
    root.joinpath("generated").mkdir(parents=True, exist_ok=True)
    root.joinpath("reports").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aggregate-", dir=root) as tmp:
        stage = Path(tmp) / "surge"
        stage.mkdir()
        results = {}
        for name, dirs in categories.items():
            print(f"聚合 {name}: {len(dirs)} 个来源目录", flush=True)
            available = [directory for directory in dirs if directory not in missing.get(name, [])]
            if not available:
                raise ValueError(f"分类 {name} 没有可读取的来源")
            category_metadata = {**metadata, "missing_directories": missing.get(name, [])}
            results[name] = aggregate_category(surge, available, stage / f"{name}.list", category_metadata)
            results[name]["directory_count"] = len(dirs)
            results[name]["directories"] = dirs
            results[name]["missing_directories"] = missing.get(name, [])
        if git(repo, "status", "--porcelain", "--untracked-files=all") or git(repo, "rev-parse", "HEAD") != metadata["commit"]:
            raise ValueError("上游在运行期间发生变化，停止输出")
        report = {"source": metadata, "complete": not bool(missing), "missing_directories": missing, "categories": results,
                  "warning": "按 README 分类聚合全部 .list 变体，可能包含直连、去广告及 no-resolve 冲突；跨分类可能重叠。使用前必须人工检查策略优先级。"}
        report_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        report_path = Path(tmp) / "summary.json"
        report_path.write_text(report_text, encoding="utf-8")
        table = ["# Surge 分类聚合报告", "", f"- 来源：{REPO_URL}",
                 f"- 分支：{metadata['branch']}", f"- Commit：`{metadata['commit']}`",
                 f"- 生成时间：{metadata['generated_at_utc']}",
                 f"- 完整性：{'完整' if report['complete'] else '不完整，存在缺失来源'}", "",
                 "| 分类 | 来源目录 | .list 文件 | 合并前 | 重复 | 最终 | DOMAIN-SET 转换 |",
                 "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for name, row in results.items():
            table.append(f"| {name} | {row['directory_count']} | {row['file_count']} | {row['before']} | {row['duplicates']} | {row['after']} | {row['domain_set_converted']} |")
        table.extend(["", "## 缺失目录", ""])
        if missing:
            for name, dirs in missing.items():
                table.append(f"- {name}: " + ", ".join(f"`{directory}`" for directory in dirs))
        else:
            table.append("无。")
        table.extend(["", "## 注意", "", report["warning"], "",
                      "逐文件来源、SHA-256、计数及转换数见同目录 `summary.json`。", ""])
        markdown_path = Path(tmp) / "summary.md"
        markdown_path.write_text("\n".join(table), encoding="utf-8")
        dest = root / "generated" / "surge"
        old = Path(tmp) / "previous"
        if dest.exists():
            if dest.is_symlink() or not dest.is_dir():
                raise ValueError(f"生成目录无效: {dest}")
            present = {file.name for file in dest.iterdir()}
            if present:
                previous_report = root / "reports" / "summary.json"
                if not previous_report.is_file():
                    raise ValueError("生成目录非空但没有上次报告，拒绝覆盖")
                previous = json.loads(previous_report.read_text(encoding="utf-8"))
                managed = {f"{name}.list" for name in previous["categories"]}
                if present - managed:
                    raise ValueError(f"生成目录包含未知文件，拒绝覆盖: {sorted(present - managed)}")
            os.replace(dest, old)
        try:
            os.replace(stage, dest)
            os.replace(report_path, root / "reports" / "summary.json")
            os.replace(markdown_path, root / "reports" / "summary.md")
        except BaseException:
            if dest.exists():
                shutil.rmtree(dest)
            if old.exists():
                os.replace(old, dest)
            raise
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "sources" / "ios_rule_script")
    parser.add_argument("--allow-missing", action="store_true", help="生成明确标记为不完整的诊断结果，并以状态 2 退出")
    args = parser.parse_args()
    try:
        report = run(args.source.resolve(), ROOT, args.allow_missing)
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"聚合失败: {exc}", file=sys.stderr)
        return 1
    print("\n分类 目录 文件 合并前 重复 最终")
    for name, row in report["categories"].items():
        print(f"{name} {row['directory_count']} {row['file_count']} {row['before']} {row['duplicates']} {row['after']}")
    print(f"\n报告: {ROOT / 'reports' / 'summary.json'}")
    if not report["complete"]:
        print(f"警告：结果不完整，缺失目录: {report['missing_directories']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
