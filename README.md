# Surge 分类规则 · 测试版

从 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) 的 Surge 分类表生成，来源为 `master`、提交 `0b6897dc17e0c513d25449c935a9694818e32f0c`。上游 LICENSE 和项目声明分别保存在本仓库的 `LICENSE`、`UPSTREAM-NOTICE.md`。

**这是测试数据，并非完整或已经生产验证的规则。** 上游 README 的 Global 分类引用的 `RemoteDesktop`、`ChemeQuations`、`Zoom` 对应目录在该提交中缺失；`rules/Global.list` 明确标记为不完整。不要依赖这些列表实现安全控制或未经检查地替换现有配置。

`rules/` 包含每个上游一级分类的一份聚合规则，以及独立的 `OpenAI.list`、`Anthropic.list`。两份 AI 列表逐字节同步 [VPSDance/ai-proxy-rules](https://github.com/VPSDance/ai-proxy-rules) 的 Surge 列表；上游 MIT 许可保存在 `licenses/VPSDance-MIT.txt`。来源版本、SHA-256 和同步结果见 `reports/ai-sync.json`。

Global 从 `inputs/Global.unfiltered.list` 固定基线重新生成，剔除已识别的 AI 核心、品牌域名、完全相同的 IP / ASN 规则及过宽的原始品牌关键词。共享第三方域名保留在 Global；来源、移除规则及各文件 SHA-256 见 `reports/release-report.json`。

上游 AI 列表原样包含 `PROCESS-NAME,Codex`、`PROCESS-NAME,Claude`、`DOMAIN-KEYWORD,sentry`、`storage.googleapis.com`、`stripe.com` 等进程、宽泛关键词和共享第三方规则；这些也会进入对应 AI 策略。两份列表均包含 `intercom.io`、`intercomcdn.com`、`sentry.io` 和 `statsigapi.net`，由 Surge 中先出现的规则集决定出口。`openai.org`、`anthropic.team`、`claude.new`、`claude.site` 等域名根据上游规则分流，注册主体未在此逐一核验；规则归类不构成官方网站或安全认证。

为避免 OpenAI 列表中的 `PROCESS-NAME,Codex` 抢先匹配 Claude 域名，`support/Anthropic-Domains.list` 从同一上游提交提取 Anthropic Core 域名及品牌域名，不含进程、IP、关键词或通用第三方规则；上游 Core 中的 `modelcontextprotocol` 共享域名也排除在优先列表之外。可在完整 OpenAI 列表之前引用这个辅助列表，并指向现有 Anthropic 策略组；它不是新的分类策略组。该文件随 AI 同步工作流一起更新。

上游每个目录的所有 `.list` 变体都参与聚合，包括 Resolve 和 No Resolve；分类之间可能重叠，规则顺序可能改变命中结果。上游 `Advertising` 分类还包含 `Direct` 目录，因此**不要直接将它整体绑定到 REJECT**。`URL-REGEX` 等规则受 Surge 的功能与运行设置约束。

原始分类聚合及逐文件来源见 `reports/summary.md`、`reports/summary.json`。`scripts/`、`tests/` 和 `config/` 保存生成程序及 Global 排除范围。工具不包含用户代理配置或凭据。

## AI 规则同步

仓库的 `Sync AI rules` 工作流每天 02:30 UTC（台北时间 10:30）执行，也可在 GitHub Actions 页面手动运行。它先读取 VPSDance `main` 的提交 SHA，再从同一提交下载并校验两份规则，保持原始字节，重算 Global 排除项和 Anthropic 优先域名，并仅在内容变化时提交；GitHub 定时任务可能延迟。上游不可访问或格式校验失败时任务会失败，不使用部分结果。

本地手动同步可运行 `uv run --locked python scripts/sync_ai.py`，再执行 `uv run --locked python -m unittest discover -s tests -v` 并检查差异。同步脚本只读取 GitHub，无需修改 VPSDance 克隆。分类基线的 SHA-256 固定在 `config/global-baseline.json`；更新 blackmatrix7 分类时需同时更新 `inputs/Global.unfiltered.list` 和该摘要，再重新同步 AI。

重新生成时，在项目根目录将上游克隆至 `sources/ios_rule_script/`，并使用 uv 运行：

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/blackmatrix7/ios_rule_script.git sources/ios_rule_script
git -C sources/ios_rule_script sparse-checkout set rule/Surge
uv run --locked python scripts/aggregate.py --allow-missing
uv run --locked python scripts/prepare_release.py
uv run --locked python scripts/verify.py
uv run --locked python -m unittest discover -s tests -v
```

当前上游有缺失来源，聚合和验证命令会以退出码 `2` 提醒结果不完整；更换上游提交后务必复核缺失、来源、规则冲突和生成报告。`prepare_release.py` 的结果在 `release/rules/`，发布前需审查并复制到 `rules/`；然后执行 `scripts/sync_ai.py` 重新应用 VPSDance 列表及 Global 排除规则。每日工作流只同步两份 AI 列表及 Global 排除，不会更新其他分类。
