#!/usr/bin/env python3
"""Synchronize the two VPSDance Surge lists and update the Global exclusions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.request import Request, urlopen

from aggregate import validate_rule
from prepare_release import classify

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://github.com/VPSDance/ai-proxy-rules"
API = "https://api.github.com/repos/VPSDance/ai-proxy-rules/commits/main"
MAX_FILE = 2_000_000


def fetch(url: str, *, api: bool = False) -> bytes:
    headers = {"User-Agent": "dekaic-surge-rules-sync", "Accept": "application/vnd.github+json" if api else "text/plain"}
    token = os.environ.get("GITHUB_TOKEN")
    if api and token:
        headers["Authorization"] = "Bearer " + token
    with urlopen(Request(url, headers=headers), timeout=45) as response:
        data = response.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError(f"上游文件超出大小限制: {url}")
    return data


def parse_source(data: bytes, name: str) -> tuple[list[str], list[str]]:
    text = data.decode("utf-8-sig")
    section = ""
    rules, core = [], []
    found_core = False
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            header = line[1:].strip()
            if header in {"Core", "Network", "Third-Party"}:
                section = header
                found_core |= section == "Core"
            continue
        try:
            validate_rule(line)
        except ValueError as exc:
            raise ValueError(f"{name}:{number}: {exc}") from exc
        rules.append(line)
        if section == "Core" and line.startswith(("DOMAIN,", "DOMAIN-SUFFIX,")):
            core.append(line)
    if not rules or not found_core or not core:
        raise ValueError(f"{name}: 上游规则为空或缺少 Core 域名")
    return rules, core


def stage_outputs(root: Path, sha: str, data: dict[str, bytes]) -> dict[Path, bytes]:
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("上游提交 SHA 无效")
    if set(data) != {"OpenAI", "Anthropic"}:
        raise ValueError("缺少 OpenAI 或 Anthropic 上游列表")
    parsed = {name: parse_source(content, name) for name, content in data.items()}
    baseline = (root / "inputs" / "Global.unfiltered.list").read_bytes()
    baseline_info = json.loads((root / "config" / "global-baseline.json").read_text(encoding="utf-8"))
    if hashlib.sha256(baseline).hexdigest() != baseline_info["sha256"]:
        raise ValueError("Global 原始基线 SHA-256 不匹配")
    curated = json.loads((root / "config" / "ai_rules.json").read_text(encoding="utf-8"))
    # Treat provider-branded domains from any upstream section as dedicated;
    # shared third-party domains remain in Global for other consumers.
    branded = {"OpenAI": ("openai", "chatgpt"), "Anthropic": ("anthropic", "claude")}
    filters = {}
    networks: dict[str, str] = {}
    for name in data:
        names = [rule for rule in parsed[name][0]
                 if rule.startswith(("DOMAIN,", "DOMAIN-SUFFIX,"))
                 and any(token in rule.partition(",")[2].lower() for token in branded[name])]
        filters[name] = list(dict.fromkeys(curated[name] + parsed[name][1] + names))
        for rule in parsed[name][0]:
            if rule.startswith(("IP-CIDR,", "IP-CIDR6,", "IP-ASN,")):
                networks.setdefault(rule, name)
    removed = {"OpenAI": [], "Anthropic": [], "quarantine": []}
    global_lines = []
    for raw in baseline.decode("utf-8").splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        group = (classify(line, filters) or networks.get(line)) if line and not line.startswith("#") else None
        if group:
            removed[group].append(line)
        else:
            global_lines.append(raw)
    global_bytes = "".join(global_lines).encode("utf-8")
    shared = sorted(set(parsed["OpenAI"][0]) & set(parsed["Anthropic"][0]))
    manifest = {"repository": SOURCE, "branch": "main", "commit": sha,
                "files": {name: {"path": f"rules/surge/{name.lower()}.list",
                                 "sha256": hashlib.sha256(content).hexdigest(),
                                 "rules": len(parsed[name][0])} for name, content in data.items()},
                "shared_exact_rules": shared, "global_removed": removed,
                "warning": "原样同步上游；第三方域名、关键词、进程与 IP 规则可能影响共享服务。OpenAI 与 Anthropic 列表存在重叠，按 Surge 规则顺序先匹配者生效。"}
    report_path = root / "reports" / "release-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["global_removed"] = removed
    report["ai_source"] = {"repository": SOURCE, "branch": "main", "commit": sha}
    for name, content in {**data, "Global": global_bytes}.items():
        report["sha256"][name + ".list"] = hashlib.sha256(content).hexdigest()
    return {root / "rules" / "OpenAI.list": data["OpenAI"], root / "rules" / "Anthropic.list": data["Anthropic"],
            root / "rules" / "Global.list": global_bytes,
            root / "reports" / "ai-sync.json": (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
            report_path: (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()}


def write_outputs(outputs: dict[Path, bytes]) -> int:
    changed = {p: b for p, b in outputs.items() if not p.exists() or p.read_bytes() != b}
    previous = {p: p.read_bytes() if p.exists() else None for p in changed}
    replaced = []
    try:
        for path, content in changed.items():
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".ai-sync-", delete=False) as tmp:
                temp = Path(tmp.name)
                try:
                    tmp.write(content)
                except BaseException:
                    temp.unlink(missing_ok=True)
                    raise
            try:
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            replaced.append(path)
    except BaseException:
        for path in reversed(replaced):
            if previous[path] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous[path])
        raise
    return len(changed)


def main() -> int:
    try:
        sha = json.loads(fetch(API, api=True))["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("上游 API 返回的 SHA 无效")
        raw = f"https://raw.githubusercontent.com/VPSDance/ai-proxy-rules/{sha}/rules/surge/"
        data = {name: fetch(raw + name.lower() + ".list") for name in ("OpenAI", "Anthropic")}
        changed = write_outputs(stage_outputs(ROOT, sha, data))
        print(f"已同步 VPSDance {sha}；变化文件 {changed} 个")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"AI 规则同步失败，未采用不完整输入: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
