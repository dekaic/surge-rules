# Surge rules

一个 Python 标准库脚本，只负责同步 `rules/*.list`。

- 从 [blackmatrix7 Surge README](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Surge/README.md) 读取分类，每个来源目录选主 `.list`，分类内去重。
- [OpenAI](https://github.com/VPSDance/ai-proxy-rules/blob/main/rules/surge/openai.list) 原样同步；[Anthropic](https://github.com/VPSDance/ai-proxy-rules/blob/main/rules/surge/anthropic.list) 保留上游内容，并补充 `IP-CIDR,153.61.224.0/22,no-resolve`。
- 不生成 Media：IPTV 来源并入国内/海外媒体，通用 Tencent 留在 Mainland。国内媒体排除 ChinaMax，广告排除 Direct，Other 排除 LAN/直连例外。
- Global 排除宽泛的 `DOMAIN-SUFFIX,aliyuncs.com`，保留单独列出的其他阿里云子域名规则。
- 不做跨分类去重、AI 排除、发布打包、审计报告或辅助列表；分类优先级由客户端决定。

```bash
python3 sync.py
```

需要 Python 3.10+，无需安装依赖。全部下载成功后替换 `rules/`，失败保留旧列表。上游原有的 RemoteDesktop、ChemeQuations、Zoom 三个缺失来源会打印提示，并在 Global 文件头标记不完整。

现有 GitHub Actions 每周一 02:30 UTC（台北时间 10:30） 执行同一个脚本，也可手动运行。客户端统一使用：

```text
https://raw.githubusercontent.com/dekaic/surge-rules/main/rules/Anthropic.list
```

其他分类替换文件名即可。每次同步读取上游分支的当前提交，保证当次下载来自同一版本。上游许可证保留在 `LICENSE` 和 `licenses/`。
