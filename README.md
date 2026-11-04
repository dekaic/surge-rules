# Surge 分类规则 · 测试版

从 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) 的 Surge 分类表生成，来源为 `master`、提交 `0b6897dc17e0c513d25449c935a9694818e32f0c`。上游 LICENSE 和项目声明分别保存在本仓库的 `LICENSE`、`UPSTREAM-NOTICE.md`。

**这是测试数据，并非完整或已经生产验证的规则。** 上游 README 的 Global 分类引用的 `RemoteDesktop`、`ChemeQuations`、`Zoom` 对应目录在该提交中缺失；`rules/Global.list` 明确标记为不完整。不要依赖这些列表实现安全控制或未经检查地替换现有配置。

`rules/` 包含每个上游一级分类的一份聚合规则，以及独立的 `OpenAI.list`、`Anthropic.list`。`Global.list` 中明确归属上述两家的域名已转移到对应专用列表；三个过宽的品牌关键词已移除，未扩散到专用列表。名称相似但未确认归属的第三方域名保留在 Global。来源、移除规则及各文件 SHA-256 见 `reports/release-report.json`。

上游每个目录的所有 `.list` 变体都参与聚合，包括 Resolve 和 No Resolve；分类之间可能重叠，规则顺序可能改变命中结果。上游 `Advertising` 分类还包含 `Direct` 目录，因此**不要直接将它整体绑定到 REJECT**。`URL-REGEX` 等规则受 Surge 的功能与运行设置约束。

原始分类聚合及逐文件来源见 `reports/summary.md`、`reports/summary.json`。`scripts/`、`tests/` 和 `config/` 保存生成程序及手工维护的 AI 专用域名。工具不包含用户代理配置或凭据。

重新生成时，在项目根目录将上游克隆至 `sources/ios_rule_script/`，并使用 uv 运行：

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/blackmatrix7/ios_rule_script.git sources/ios_rule_script
git -C sources/ios_rule_script sparse-checkout set rule/Surge
uv run --locked python scripts/aggregate.py --allow-missing
uv run --locked python scripts/prepare_release.py
uv run --locked python scripts/verify.py
uv run --locked python -m unittest discover -s tests -v
```

当前上游有缺失来源，聚合和验证命令会以退出码 `2` 提醒结果不完整；更换上游提交后务必复核缺失、来源、规则冲突和生成报告。`prepare_release.py` 的结果在 `release/rules/`，发布前需审查并复制到 `rules/`。本仓库不自动更新。
