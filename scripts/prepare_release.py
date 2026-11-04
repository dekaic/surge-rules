#!/usr/bin/env python3
"""Prepare public test rules without exposing any local Surge configuration."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from aggregate import ROOT, validate_rule

KEYWORDS = {"openai", "anthropic", "claude"}


def classify(rule, curated):
    kind, _, value = rule.partition(",")
    if kind == "DOMAIN-KEYWORD" and value.lower() in KEYWORDS:
        return "quarantine"
    if kind not in {"DOMAIN", "DOMAIN-SUFFIX"}:
        return None
    host = value.lower().rstrip(".")
    for provider, rules in curated.items():
        for candidate in rules:
            typ, _, domain = candidate.partition(",")
            domain = domain.lower().rstrip(".")
            if host == domain or (typ == "DOMAIN-SUFFIX" and host.endswith("." + domain)):
                return provider
    return None


def prepare(root=ROOT):
    source = root / "generated" / "surge"
    report = json.loads((root / "reports" / "summary.json").read_text())
    curated = json.loads((root / "config" / "ai_rules.json").read_text())
    if set(curated) != {"OpenAI", "Anthropic"}:
        raise ValueError("AI 配置必须包含 OpenAI 和 Anthropic")
    for rules in curated.values():
        for rule in rules:
            validate_rule(rule)
    expected = {f"{name}.list" for name in report["categories"]}
    if {x.name for x in source.glob("*.list")} != expected:
        raise ValueError("生成文件与聚合报告不一致")
    dest = root / "release" / "rules"
    dest.parent.mkdir(exist_ok=True)
    counts = {"OpenAI": [], "Anthropic": [], "quarantine": []}
    with tempfile.TemporaryDirectory(prefix=".release-", dir=dest.parent) as td:
        stage = Path(td) / "rules"
        stage.mkdir()
        for file in sorted(source.glob("*.list")):
            if file.name != "Global.list":
                shutil.copyfile(file, stage / file.name)
                continue
            with file.open(encoding="utf-8") as inp, (stage / file.name).open("w", encoding="utf-8", newline="\n") as out:
                for line in inp:
                    raw = line.rstrip("\n")
                    group = classify(raw, curated) if raw and not raw.startswith("#") else None
                    if group:
                        counts[group].append(raw)
                    else:
                        out.write(line)
        for provider, initial in curated.items():
            entries = list(dict.fromkeys(initial + counts[provider]))
            (stage / f"{provider}.list").write_text(
                "# Curated provider rules; source and exclusions: ../reports/release-report.json\n" + "\n".join(entries) + "\n", encoding="utf-8")
        report_out = {"source": report["source"], "complete": report["complete"],
                      "missing_directories": report["missing_directories"], "global_removed": counts,
                      "warning": report["warning"], "sha256": {}}
        for file in sorted(stage.glob("*.list")):
            report_out["sha256"][file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
        (stage / "release-report.json").write_text(json.dumps(report_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        old = Path(td) / "old"
        if dest.exists():
            dest.rename(old)
        try:
            stage.rename(dest)
        except BaseException:
            if old.exists():
                old.rename(dest)
            raise
    return report_out


if __name__ == "__main__":
    result = prepare()
    print("生成发布候选；完整性:", result["complete"])
    for name, rules in result["global_removed"].items():
        print(name, "移除", len(rules), "条")
    print("已移除宽泛关键词，未添加到专用规则集；缺失来源:", result["missing_directories"])
