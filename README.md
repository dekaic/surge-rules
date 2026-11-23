# Surge rules

一个 Python 标准库脚本，只负责同步 `rules/*.list`。

- 从 [blackmatrix7 Surge README](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Surge/README.md) 读取分类，每个来源目录选主 `.list`，分类内去重。
- `rules/OpenAI.list` 和 `rules/Anthropic.list` 由 [VPSDance](https://github.com/VPSDance/ai-proxy-rules/tree/main/rules/surge) 同步内容和 `local-rules/` 中同名文件合并生成。新增依赖、来源和网络说明写入本地维护文件，`# Exclude upstream: <规则>` 可屏蔽指定上游规则。同步保留本地补充并对相同规则去重。
- AI 目的 IP 规则由本地维护文件提供。目前仅启用 Anthropic 官方入站网段。服务端出站网段用于接收方防火墙，ChatGPT Voice 需按 OpenAI 发布的目的 IP 单独允许 UDP 3478。
- 不生成 Media：IPTV 来源并入国内/海外媒体，通用 Tencent 留在 Mainland。国内媒体排除 ChinaMax，广告排除 Direct，Other 排除 LAN/直连例外。
- Global 排除宽泛的 `DOMAIN-SUFFIX,aliyuncs.com`，保留单独列出的其他阿里云子域名规则。
- 不做跨分类去重、发布打包或审计报告。分类优先级由客户端决定。

GitHub、npm、Homebrew、字体和 CDN 等共享依赖在有明确用途时按主机写入 AI 规则，OpenAI 的 Apple 端点也只列出文档指定的主机。客户端按规则顺序匹配；若共享流量由 Global、Microsoft、Google 或 Apple 统一分流，请按现有策略安排顺序。

```bash
python3 sync.py
```

需要 Python 3.10+，无需安装依赖。全部下载成功后替换 `rules/`，失败保留旧列表。上游原有的 RemoteDesktop、ChemeQuations、Zoom 三个缺失来源会打印提示，并在 Global 文件头标记不完整。

现有 GitHub Actions 每周一 02:30 UTC（台北时间 10:30） 执行同一个脚本，也可手动运行。客户端统一使用：

```text
https://raw.githubusercontent.com/dekaic/surge-rules/main/rules/Anthropic.list
```

其他分类替换文件名即可。每次同步读取上游分支的当前提交，保证当次下载来自同一版本。上游许可证保留在 `LICENSE` 和 `licenses/`。
