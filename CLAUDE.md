# Data Insight Agent — 工程约定

AI 经营分析 Agent：连接 CSV / Excel，用户自配 OpenAI-compatible 模型（BYOM），用自然语言发起分析，自动完成取数、分析、制图，产出每条结论可核对（SQL / 数据源 / 运行时间）的经营诊断报告。分析任务可保存，用同结构的新数据重跑时报告自动对比上期。开源自部署（Docker）。零售经营分析为首个内置场景。

> 本文件是公开仓库的工程约定（技术栈、目录约定、验证、协作纪律）。面向贡献者与自部署者。

## 技术栈与版本
- 后端：Python 3.11 + FastAPI + SQLAlchemy 2.0 + openai SDK + pandas/openpyxl + sqlglot；包管理 uv（锁文件 `uv.lock` 必须提交）
- 前端：Node 22.13+ + Vite + React + TypeScript；包管理 pnpm（锁文件 `pnpm-lock.yaml` 必须提交）；单测 Vitest
- 工具链版本：pnpm 版本只在 `frontend/package.json` 的 `packageManager` 定义，CI 与 Dockerfile 都从这里读取；Node 用维护期内的 LTS（当前 22），升级时 CI、Dockerfile 与文档一起改
- 数据库：SQLite 是唯一支持的应用库（默认 `./data/app.db`；`APP_DB_URL` 指向非 SQLite 时启动即报错）。MySQL / PostgreSQL 只读直连是规划中的数据源能力，不是应用库选项
- 可视化：Web 用 ECharts
- 规划能力：定时调度（APScheduler）、邮件推送（`emails` + SMTP）与邮件内嵌图表（Matplotlib）的依赖已预置，功能尚未启用
- 部署：Docker Compose v2（单容器：后端托管前端静态产物）

## 仓库结构
```
data-insight-agent/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI 入口 + 路由装配 + 托管前端静态产物（SPA fallback）
│   │   ├── config.py           # 配置（LLM_* 等，pydantic-settings）
│   │   ├── timestamps.py       # 时刻唯一出口：UTC 生成、带偏移序列化、历史报告时间换算（architecture §2.4）
│   │   ├── api/                # FastAPI 路由层（上传 / 任务 / 报告 / 数据源 / 业务口径 / 反馈 / 模型配置）
│   │   ├── modules/            # 分析引擎 + 有界 agentic 循环工具（契约见 docs/architecture.md）
│   │   ├── scheduler/          # 定时调度（规划中，当前为占位包）
│   │   ├── db/                 # 数据模型 + 启动期结构升级（不使用迁移框架：启动时建表，并为既有表补可空列）
│   │   ├── llm/                # 厂商中立 OpenAI-compatible 客户端与 provider preset
│   │   ├── context_packs/      # 内置出厂 Context Pack JSON（新部署种子与「恢复默认」；运行时以数据库中的活动包为准）
│   │   └── sample_data/        # 内置零售样例数据
│   ├── eval/                   # 报告质量 eval：golden questions / runner / 断言 / 基线 / fixtures（make eval）
│   ├── scripts/                # 样例数据生成脚本
│   └── tests/                  # 后端测试（含 eval 确定性断言层，随 make check 运行）
├── frontend/src/
│   ├── AppShell.tsx            # 三栏外壳 + 状态机入口
│   ├── components/             # 组件（对话 / 报告 / 分析任务 / 业务口径编辑 / 反馈 / 模型配置 / charts）
│   ├── api/ · lib/ · styles/   # API 客户端 / 状态机、视图与时间格式化工具 / 样式（app.css 含 @media print）
│   ├── pages/                  # 预留
│   └── **/*.test.ts(x)         # Vitest 单测，与被测文件同目录（随 make check 与 CI 运行）
├── docs/architecture.md        # 架构契约
├── Dockerfile                  # 单容器多阶段构建（前端 build → 后端托管 dist）
├── docker-compose.yml          # 用户态（拉预构建镜像一行起）
├── docker-compose.dev.yml      # 源码构建覆盖文件
├── Makefile, .github/workflows/  # 验证入口 / CI + 镜像构建推送
└── .env.example
```

## 架构方向
- **两层结构**：确定性 workflow 外壳（数据连接、报告组装；规划中的调度与推送）+ 有界 agentic 分析内核（固定工具集、硬迭代上限、每轮 SQL 过执行控制层）。
- 分析内核按有界 agentic 循环实现，不做开放 skill 体系、不做多 Agent。
- 每个分析任务保存为结构化可复用 workflow：同结构新数据可重跑，报告归入任务报告链并自动对比上期。
- 用户交互：引导式对话 → 结构化展示 → 确认执行，不做开放式聊天。
- 通用产品底座，用 Context Pack 承载行业差异。

## 关键术语
- **BYOM（自配模型）**：用户自带 OpenAI-compatible 模型 API Key，产品方不绑定模型。两种配置方式：Web 界面模型配置（保存在 `data/llm_config.json`，文件权限 600，**优先于 `.env`**）与 `.env` 的 `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`；支持 provider preset 和 custom base_url。注意：数据仍发给用户所配模型服务商。
- **Context Pack**：垂直场景的结构化业务知识包（指标口径、字段别名、维度定义、异常阈值、分析模板、校验规则）。活动包存于 SQLite，可在 Web「业务口径设置」或经 `/api/v1/context-pack` 编辑，保存前经服务端校验；每份报告记录生成时的口径版本（编辑后为 `{出厂版本}-local.{N}`）。内置 JSON 是出厂镜像，只用于新部署种子与「恢复默认」。详见 `docs/architecture.md`。
- **有界 agentic 循环**：模型在 while 循环里自主决定下一步（取数/下钻/停止），但被硬约束包裹（迭代上限、token 预算、执行控制层全程校验）。

## 命名约定
- Python：snake_case（函数/变量/模块）；PascalCase（类）
- TS/React：PascalCase（组件文件名+组件名）；camelCase（函数/变量）；kebab-case（非组件文件名）
- API 路径：`/api/v1/{resource}`，资源名复数
- 文档文件：中文命名，清晰表达内容

## 验证清单（每次改完必跑）
- 统一入口：`make check` 跑完整代码验证（后端 ruff + pytest，前端 typecheck + lint + test + build）
- 后端：`cd backend && uv run ruff check . && uv run pytest`
- 前端：`cd frontend && pnpm typecheck && pnpm lint && pnpm test && pnpm build`
- 报告质量 eval：`make eval` 用真实模型在隔离临时库运行 golden questions（需先配置模型；不进 `make check` 与 CI）。改动分析链路、prompt 或业务口径逻辑时运行；基线只经 `make eval-baseline` 显式更新，并说明原因
- 启动冒烟：`make smoke`（源码构建并启动单容器，`/health` 与 `/` 均 200；前端与 API 同在 `localhost:8000`）
- 浏览器验收：涉及前端页面、上传、图表、报告预览、交互状态的改动，必须用浏览器打开页面验证，并在汇报中说明访问 URL、页面状态、关键证据

## 协作纪律
1. **规划驱动**：跨文件/跨模块改动先出方案；SQL/调度/邮件相关改动一律先规划
2. **边界先行**：每个任务说明书有「目标/范围/禁区/验证标准」四段
3. **接口先行**：跨层改动前必须先读 `docs/architecture.md`；契约变更先改文档再改代码
4. **模块完成切会话**：完成一个模块就清理上下文，避免污染
5. **断言分级确认**：涉及业务口径、阈值、预期数值的断言由维护者确认；技术性断言由 Reviewer 视角把关
6. **Debug 三件套**：报 bug 必须给「预期/实际/最小复现」
7. **能抄不写**：新功能先查现成开源方案，不重复造轮子
8. **执行控制硬约束不可绕过**：见 `docs/architecture.md`「执行控制层」段

## Agent 工作流
- Implementer 按任务边界实现最小可运行变更，并主动跑对应验证命令
- Tester 复现失败、补验证路径、读报错与浏览器状态，不扩大范围
- Reviewer 检查架构边界、无关改动、风险遗漏、测试缺口、文档同步
- Orchestrator 拆解任务、分配上下文、收敛 review、判断 done 标准
- 多 Agent 只用于任务可拆、写入范围清晰且互不冲突的场景

## Done 标准
- 每个变更完成必须汇报：变更摘要、验证命令与结果、浏览器/Docker 状态、review 结论、剩余风险
- 跨后端/前端/契约的改动，先完成实现侧自检，再做 review 侧检查
- 完成结论必须有新鲜验证证据支撑；环境不可用时按「代码验证完成 / 环境验证未完成」分层说明

## 规则文件同步
- `CLAUDE.md` 与 `AGENTS.md` 内容一致（供不同工具读取），改其一须同步另一。

## 上下文索引
- 架构契约：`docs/architecture.md`（workflow 外壳 + agentic 内核 + API 与 eval 契约 + Context Pack Schema 与存储 + 执行控制硬约束）
