# Data Insight Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个你自己部署、自己掌控的 AI 数据分析工具。上传一份表格，用中文说你想看什么，它会自动取数、画图，生成一份**每条结论都能核对**的分析报告，并可导出 PDF。

零售经营分析是首个内置场景。

## 为什么用它

- **你的数据你做主**：自己用 Docker 部署，产品方不托管你的数据。
- **每个结论都能核对**：报告里每条结论都附带它依据的数据来源和查询，不是一段看不清来路的黑盒摘要。
- **用你自己的 AI 模型**：自己配置模型接口，不绑定任何一家厂商；不配模型也能先用内置样例体验完整流程。

## 它能做什么

1. 上传一份 CSV 或 Excel 表格（也可以一键载入内置的零售样例）。
2. 用一句中文说出你想分析什么，比如「本周和上周比，看销售变化和哪些店表现异常」。
3. 它自动完成取数、逐步分析、配图，产出一份带核心指标、关键洞察、下一步建议和**可核对依据**的报告。
4. 报告可在页面查看，也可导出为 PDF 分享。

## 快速开始

需要 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。

```bash
docker compose up -d
```

- 打开应用：<http://localhost:8000>（前端与 API 同在 8000，单容器）
- 健康检查：<http://localhost:8000/health>

首次启动会从 ghcr 拉取预构建镜像，稍候即可。启动后**不配置模型也能用**：在首页点「先看一份示例」即可用内置零售样例跑通完整流程、看到一份示例报告（体验模式）。

## 配置你自己的 AI 模型

想分析自己的数据、用自然语言定制分析，需要配置一个 AI 模型接口（任何 OpenAI 兼容的服务都可以，如 OpenAI、DeepSeek、通义千问、本地 Ollama 等）：

```bash
cp .env.example .env
# 编辑 .env，填入你的模型接口信息：
#   LLM_API_KEY   你的密钥
#   LLM_PROVIDER  服务商预设名（如 deepseek / openai / openrouter），或留空配合下一行
#   LLM_BASE_URL  自定义接口地址（用预设时可不填）
#   LLM_MODEL     模型名
docker compose up -d   # 重启生效
```

## 数据与隐私

- 产品方不托管你的数据。应用在你自己的机器上运行，分析数据只存放在本地（SQLite 文件与上传的临时文件）。
- 当你配置了远程模型接口，分析过程中的数据结构、聚合统计结果与提示文本会**按你选择的模型服务商**的路径发送给该服务商；原始单行明细不会发送。
- 不配置模型时（体验模式）完全本地运行，不向外发送任何数据。

## 环境要求

- Docker Desktop（推荐方式，唯一硬性要求）。
- 本地开发（可选）：Python 3.11+、Node 20+、`uv`、`pnpm`。

## 本地开发（可选）

```bash
make dev            # 同时启动前后端
make backend-dev    # 仅后端
make frontend-dev   # 仅前端
make check          # 跑后端 lint+测试、前端类型检查+lint+构建
```

`http://localhost:5173` 不是静态页面，必须先启动前端服务；报告生成、样例与上传接口还需后端运行。本机 `pnpm dev` 默认把 `/api` 代理到 `http://127.0.0.1:8000`。

## 常见问题

- **打开 8000 是空白/连不上**：确认 `docker compose up -d` 已成功、容器在运行（首次会从 ghcr 拉镜像，需稍候）；应用在 `http://localhost:8000`。
- **报告生成报错或提示未配置模型**：未配置模型时仅内置零售样例可跑通（体验模式）；要分析自己的数据，请按上文配置 AI 模型。
- **上传文件失败**：当前支持普通的 CSV 和 `.xlsx`（首行表头的二维表）；复杂表头、合并单元格、透视表暂不支持。

## 架构

三层结构：确定性 workflow 外壳（调度、数据连接、报告组装）+ 有界分析内核（固定工具集、硬迭代上限、每条 SQL 过执行控制层校验）+ 行业知识包（承载行业语义）。契约见 [docs/architecture.md](docs/architecture.md)。

## License

[MIT](LICENSE)
