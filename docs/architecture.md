# Data Insight Agent 架构契约

> 状态：v0.18（2026-09-23）。公开架构契约：描述当前自部署版本的系统分层、API 合约、执行控制与数据模型边界；各版本变更见 §8 版本历史。
> 用途：所有跨层 / 跨模块改动前必须先读本文件。
> 维护：任何契约变更必须同步更新本文件；模块输入 / 输出契约先改本文件、再改实现（§8）。

---

## 1. 架构总览：Workflow 外壳 + 有界 Agentic 分析内核

```
┌──────────────────────────────────────────────────────────────┐
│  确定性 Workflow 外壳（代码持有编排权）                         │
│                                                              │
│  任务确认 ──► 加载上下文 ──► ┌─────────────────┐ ──► 报告组装 ──► Web 预览/历史 │
│                            │ 有界 Agentic    │                │
│                            │ 分析循环        │                │
│                            │ (模型持有控制权) │                │
│                            └────────┬────────┘                │
│                                     │                        │
│  ═══════════════ 执行控制层（全程包裹）═══════════════════════  │
│  SQL 安全 / 数据脱敏 / Token 预算 / 迭代上限 / 降级策略       │
└──────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
 CSV/XLSX/数据库连接   用户 AI API (BYOM)     通知投递通道
```

图中数据库连接与通知投递（SMTP / Webhook）为规划能力（见 §2）。

**核心设计原则**：

| 原则 | 含义 |
|------|------|
| 外壳确定性 | 上传/连接、任务确认、报告组装、历史写入——代码写死顺序，可预测、可追溯 |
| 内核 agentic | 分析步骤中模型自主决定取数/下钻/停止——数据分析本质是探索性的 |
| 有界 | 迭代上限 + Token 预算 + 时间上限 + 降级策略——无人值守场景下不能放飞 |
| 工具集固定 | 5 个工具，不可扩展——有界任务空间不需要开放 skill 体系 |
| 执行控制层包裹 | 每一轮 SQL 都过安全校验，不是只验一次 |

**与 v0.1 的关键差异**：

v0.1 的 8 模块单趟流水线（固定编排器按序调用）被替代。分析步骤不是一条直线——"销售额掉了"需要逐层下钻找根因，下一步取决于上一步返回什么。这种数据依赖的分支需要 agentic 循环，所有数据分析竞品（Julius AI、Dot、ThoughtSpot）验证了这一点。

---

## 2. 业务产品层

承接对象：前端 React + Vite 应用。

**能力分层**：
- 文件分析（§2.1）：CSV/XLSX 数据源上传、样例数据、分析任务配置（对话式 + 结构化确认）、报告预览、模型状态展示。
- 配置与历史（§2.2）：单模型配置 UI、报告历史、数据源查看。
- 任务复用与业务口径（§2.3）：保存分析任务、同结构手动重跑、报告「对比上期」、Context Pack Web 编辑（业务口径设置）、报告反馈。
- 规划中：数据库直连、定时调度与通知投递（SMTP/Webhook/IM 卡片）、任务模板。

**REST API 约定**：
- 路径前缀 `/api/v1/`
- 现行端点以 §2.1 / §2.2 / §2.3 表格为准；长期资源名可向 `/datasources`、`/tasks`、`/reports`、`/settings`、`/context-packs` 收敛。
- 列表分页统一使用 `?limit=&offset=`（默认 20，上限 50）：历史/数据源与任务/反馈列表均沿用。`limit` 与 `offset` 均夹逼后原样回显，不因越界入参报错：`limit` 夹到 `[0, 50]`，`offset` 夹到 `[0, 2^63-1]`（应用库 SQLite 绑定参数为有符号 64 位整数，越界会在驱动层抛 `OverflowError`）；`offset` 超过总行数等价于翻过所有行，返回空列表且响应恒 200。
- 错误响应统一：`{code: str, message: str, details?: object}`
- 时刻字段统一为带 `+00:00` 偏移的 UTC ISO 串，前端按查看者本地时区展示；业务日期保持 `YYYY-MM-DD`（§2.4）。
- **请求体边界校验**：所有 `/api/v1/*` 的 JSON 请求体在进入业务处理前统一扫描一遍，含无法以 UTF-8 编码的字符串（JSON 允许 `\uD800`-`\uDFFF` 转义出孤立代理项，解码所得 str 无法再编码回 UTF-8）即返回 400 `REQUEST_BODY_INVALID`，不做任何写入、不发起模型调用。字典键与任意深度的嵌套值同查；multipart（上传）不解析；请求体不是合法 JSON 仍沿用框架 422。字段级校验（title 长度、comment 长度、Context Pack 四层校验等）保持不变，各司其职——边界只负责「能不能编码」，字段负责「合不合业务口径」。

### 2.1 文件分析 API Schema

文件分析流程包含文件上传、样例数据、任务确认和报告生成；任务保存、历史报告与 Context Pack 编辑见 §2.2 / §2.3，定时推送与数据库直连为规划能力。

**DataSourceRef**

```
DataSourceRef {
  id: str
  type: "csv" | "xlsx" | "mysql" | "postgres"
  name: str
  location: str
  selected_sheet?: str
  credentials_ref?: str
}
```

当前仅允许 `type="csv"` 和 `type="xlsx"`；`mysql/postgres` 为规划中的数据库直连预留。`.xls`、`.xlsm`、`.xlsb` 返回 `UNSUPPORTED_FILE_TYPE`。

**文件分析 endpoints**

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/sample-dataset` | 加载内置零售样例数据预览 |
| `POST` | `/api/v1/uploads` | 上传 CSV / XLSX 并返回 schema、sheet 列表、预览与字段识别结果 |
| `GET` | `/api/v1/uploads/{session_id}?sheet={sheet_name}` | 读取上传 session 的指定 sheet 预览 |
| `POST` | `/api/v1/tasks/parse` | 将自然语言目标解析为结构化任务；未配置 LLM 时返回默认周度模板并附 warning |
| `POST` | `/api/v1/reports/run` | 基于当前数据源与结构化任务生成可追溯报告 |
| `GET` | `/api/v1/model-status` | 返回模型配置状态 `{status, model?, provider?}`；`status` 包含 `configured/not_configured/disabled`，不返回 `base_url` / `api_key` |

**Dataset response metadata**

`GET /api/v1/sample-dataset`、`POST /api/v1/uploads` 与 `GET /api/v1/uploads/{session_id}` 的响应必须带：

```
context_pack_name: str                 # "Retail Operations"
context_pack_version: str              # "1.0.0"
```

**StructuredTask Context Pack fields**

`POST /api/v1/tasks/parse` 返回的 `task` 必须带：

```
context_pack_name: str                 # "Retail Operations"
context_pack_version: str              # "1.0.0"
```

**文件上传约束**

- CSV：UTF-8 编码优先，首行作为表头。
- XLSX：读取第一个非空可见 sheet；多 sheet 时前端展示 sheet selector，用户切换后重新生成预览和 `SchemaSummary`。
- XLSX 只解析普通二维表格，首行作为表头；公式单元格读取缓存值，缓存值缺失时提示用户用 Excel 打开并保存后重试。
- 当前版本不解析图表、透视表、宏、隐藏表、合并单元格语义和复杂表头。
- 上传文件统一落到 `./data/uploads/{session_id}/`，当前 session 索引保存在进程内存；自动清理策略作为后续加固项处理。

**文件解析 error codes**

| code | 触发情况 |
|---|---|
| `CSV_PARSE_FAILED` | CSV 无法解析 |
| `XLSX_PARSE_FAILED` | XLSX 无法读取或公式缓存值缺失 |
| `XLSX_NO_VISIBLE_SHEET` | workbook 无可用非空可见 sheet |
| `XLSX_UNSUPPORTED_FEATURE` | 检测到当前版本不支持的复杂 Excel 结构 |
| `UNSUPPORTED_FILE_TYPE` | 非 `.csv` / `.xlsx` 文件 |
| `CSV_KEY_FIELD_MISSING` | 净销售额或日期等关键字段缺失 |

**任务解析 warnings**（`/api/v1/tasks/parse` 在 `warnings[]` 返回，HTTP 200，均降级为默认周度模板，不阻断后续流程）：

| code | 触发情况 |
|---|---|
| `LLM_NOT_CONFIGURED` | 未配置模型 API |
| `LLM_CALL_FAILED` | 模型调用失败（鉴权/网络/超时等），不重试 |
| `LLM_PARSE_FAILED` | 输出非合法 JSON，修复重试一次后仍失败 |
| `LLM_INTENT_MISMATCH` | 目标与当前 Context Pack（零售运营）不匹配 |

**人工确认门**（业务产品层负责 UI 落地）：
- 文件分析：用户确认结构化任务后执行；SQL 由 Validator 自动拦截，报告中后置展示 SQL 依据
- 保存的任务：当前仅 `active` 一态，不提供状态变更 API；重跑由用户在任务详情显式触发（指纹校验通过才执行）
- 周期运行（规划中）：任务状态机 `draft → confirmed → active → paused`；数据库直连、定时任务首次启用、邮件首次发送须人工确认

### 2.2 配置、历史与数据源 API Schema

本节覆盖 **单模型配置** 与 **报告历史 + 数据源查看**。保存任务、同结构重跑、Context Pack 编辑与报告反馈见 §2.3；定时推送、数据库直连、任务模板为规划能力；多用户不做。

**API 分层**：路由按域拆分为 `backend/app/api/` 下的 APIRouter（`uploads` / `tasks` / `reports` / `datasets` / `llm_config` / `context_pack` / `feedback`）；`runtime.py` 承接上传 session 与共享取表逻辑；`main.py` 仅做 app 装配、`/health` 和末尾前端静态产物挂载。

**单模型配置**

配置优先级：`data/llm_config.json`（UI 写入）> `.env` / 环境变量。`get_settings()` 若检测到启用中的有效 `llm_config.json` 则据其构造 `Settings`，否则回落 `.env`。若 UI config 显式 `enabled=false`，视为用户关闭模型，不回落 `.env`。配置文件含 `provider / api_key / base_url / model / enabled / updated_at`，文件权限 600。

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/llm-config` | 回 `{provider, base_url, model, has_key, source:"ui"\|"env"\|"none", enabled}`，**不含 api_key** |
| `POST` | `/api/v1/llm-config` | 保存配置到 `llm_config.json`（写后 chmod 600），回最新 model-status；未提交 `api_key` 且已有 UI key 时保留旧 key |
| `POST` | `/api/v1/llm-config/test` | 用提交的配置做一次真实模型连通性测试，回 `{ok, error?}`（error 脱敏），**不落盘**；未提交 `api_key` 且已有 UI key 时可复用旧 key |
| `DELETE` | `/api/v1/llm-config` | 删除 `llm_config.json`，回落 `.env` / 体验模式 |

安全见 §4.1：api_key 永不出现在 GET 响应 / 日志 / 报告中。

**报告历史 + 数据源查看**

`POST /api/v1/reports/run` 收尾后持久化：新数据集存 `datasets`、报告存 `reports`（schema 见 §5.1），返回体增加 `report_id`。历史详情保持**只读**（不出现编辑 / 重新解析入口）。重跑仅经「保存的任务 + 新上传文件」路径发生（§2.3）；「保存为任务」是从报告创建新实体，不修改历史记录。

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/reports?limit=&offset=` | 历史报告列表（轻量：id / title / summary / status / ran_at / model / finding_count；排序见 §2.4 第 6 条） |
| `GET` | `/api/v1/reports/{report_id}` | 报告详情（完整 report payload + 结构化任务上下文 + 关联数据集概要；含 `task_id` / `task_title`（均可 null，由 `reports.task_id` join 派生）——支撑报告页「已归属任务」的事前判断与跳转） |
| `GET` | `/api/v1/datasets?limit=&offset=` | 数据源列表（轻量：id / file_name / 行列数 / 状态 / 引用报告数） |
| `GET` | `/api/v1/datasets/{dataset_id}` | 数据源详情（`SchemaSummary` + 预览），供"数据源查看" |

"对话"语义：无自由聊天记录；前端历史详情的"对话流"（目标 → 解析 → 任务 → 报告）由存下的 task + goal + report + `analysis_steps` 只读重建。

### 2.3 任务、业务口径与反馈 API Schema

本节覆盖 **保存任务 + 同结构重跑**、**Context Pack 编辑**、**报告反馈**。定时推送、数据库直连、任务模板为规划能力；多用户不做。

**任务（analysis tasks）**

「保存任务」语义固定为**从既有报告保存**（`POST /tasks` body 带 `report_id`）：服务端复制该报告的 StructuredTask 快照、**直接读取 founding dataset 存量 `field_profile_json` 的 canonical 字段集**计算 `schema_fingerprint`（时点口径见 §5.2：任务的 pack 身份记录 founding report 生成时的 `context_pack_name/version`，不用保存时活动包重算）、回填 founding report 的 `task_id`。已存在相同 `schema_fingerprint` 的任务时仍创建成功，但响应附 `warnings[]`（含既有任务 id 与标题），前端提示用户确认是否应在既有任务下重跑而非新建。不提供从任务确认页直接保存（保证报告链非空、指纹来源无歧义）。

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/v1/tasks` | 从既有报告保存任务。body `{report_id, title?}`；201 回任务详情。报告不存在 404 `REPORT_NOT_FOUND`；已归属任务 400 `REPORT_ALREADY_LINKED`（details 带既有 `task_id`） |
| `GET` | `/api/v1/tasks?limit=&offset=` | 任务列表（轻量：id / title / analysis_goal / created_at / status / context_pack_name / context_pack_version / report_count / last_run_at；后两者由 `reports.task_id` 派生） |
| `GET` | `/api/v1/tasks/{task_id}` | 任务详情：任务字段 + structured_task + canonical_fields 摘要（每项 `{name, display_name}`，display_name 由后端按当前活动包映射，见 §5.2）+ 报告链 `reports[]`（按 §2.4 第 6 条换算后的运行时刻倒序，每项 id / status / ran_at / summary / finding_count / has_previous_comparison） |
| `PATCH` | `/api/v1/tasks/{task_id}` | 任务改名：body `{title}`（1-255 字符，仅此一字段可改，无状态机交互）；返回任务详情。404 `TASK_NOT_FOUND`；400 `TASK_TITLE_INVALID` |
| `POST` | `/api/v1/tasks/{task_id}/rerun` | body `{data_source_ref: {id: <upload session_id>, type, selected_sheet?}}`。流程：resolve 上传 → 指纹比对（不合 400 `SCHEMA_MISMATCH`）→ 构建 history_context（§3.3）→ 共享 runner 执行 → 落库归链。响应与 `/reports/run` 同形：`{report_id, report}` |

实现约束：从 `/reports/run` 处理逻辑抽取共享内核 `execute_report_run(table, task, *, task_id=None, history_context=None)`（保留体验模式分流）；`/reports/run` 的路径 / 响应 / 错误码 / 状态码零变化。`tasks` router 中字面量路由（`/tasks/parse`）注册在 `/{task_id}` 动态路由之前。上传 session 失效（含后端重启丢进程内索引）复用既有 `UPLOAD_NOT_FOUND`。

**重跑前端预检（v0.13）**：前端对「任务字段集 vs 上传识别字段集」的比对只是 UX 提示，**服务端 rerun 的指纹比对是唯一权威**。上传响应的字段识别按上传时的活动包计算，口径可能在「上传完成 → 点击重跑」之间被编辑，因此前端在点击重跑时先用既有 `GET /api/v1/uploads/{session_id}?sheet=` 按**当时**活动包刷新识别结果：一致才进入生成进度态；不一致则停留在「核对中」并照常调用 rerun，由服务端返回 `SCHEMA_MISMATCH`（带 `*_display` 业务名）。不新增接口；刷新到发出 rerun 之间的毫秒级并发编辑仍以服务端响应收敛（生成态收到 `SCHEMA_MISMATCH` 即退出并展示差异）。

**Context Pack（单数资源，当前单包）**

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/context-pack` | 活动包：`{name, version, revision, is_modified, updated_at, payload}` |
| `PUT` | `/api/v1/context-pack` | 提交完整 payload → 服务端四层校验（§6.4）→ `revision+1` 落库 → 回 GET 同形；失败 400 `CONTEXT_PACK_VALIDATION_FAILED`（details.errors 列全量错误，不部分保存） |
| `POST` | `/api/v1/context-pack/reset` | 恢复出厂：payload 还原内置内容，`revision` 照常 +1，回 GET 同形 |

服务端强制：`meta.name` 不可变（变更即校验失败）；`meta.version` 由服务端按 §6.4 版本语义计算覆盖；`history_context` 字段忽略入参、原样保留占位。编辑器 UI 仅开放 metrics（calculation/aliases/unit/notes）、data_dictionary 列 aliases/description、`report_preferences.anomaly_thresholds` 三块，但 PUT 校验对全 payload 生效（防绕过 UI 的脏数据）。多包扩展时再增集合资源 `/context-packs/{id}`，向后兼容。

**请求 / 响应细节（v0.11）**：
- PUT body 为完整 pack JSON（即 GET 响应的 `payload` 内容）；同时接受 `{"payload": {...}}` 包装形式，便于前端把 GET 响应原样回传。两种形式语义相同。
- `is_modified`：当前 payload（比较时忽略服务端计算的 `meta.version`）与内置出厂内容不同即为 true；`revision >= 1` 但内容经 reset 还原时仍为 false。
- 校验产出的 `errors[]` / `warnings[]` 元素结构为 `{layer: 1|2|3|4, path: str, message: str}`（`path` 为 payload 内定位串，如 `metrics[0].calculation`）；PUT 成功响应在 GET 同形基础上附 `warnings[]`（无 warning 时为空数组），失败响应 400 `CONTEXT_PACK_VALIDATION_FAILED` 且 `details.errors` 列全量 error，不部分保存。
- GET 在活动包记录缺失时先按 §6.4 种子再返回；`updated_at` 为**带时区的 UTC ISO 串**（v0.13，如 `2026-09-19T01:30:00+00:00`，存储即 UTC；前端按本地时区展示「修改于」）。v0.16 起全部接口的时刻统一按 §2.4 输出。
- 错误与警告文案面向业务用户（v0.13）：**编辑器可触发**的问题用字段业务显示名与指标名描述，不暴露英文 canonical 名与结构术语（calculation 中用户自己写的字段 token 除外）；可定位到单个字段/指标时 `path` 带下标（如 `data_dictionary.tables[0].columns[8].aliases`），供前端跳转高亮。只有绕过 UI 的 API 调用才可能触发的结构错误（缺节、非文本名称、表名、未知字段等）允许保留技术原因（统一前缀「业务口径结构不完整」）。结构层逐项报出业务问题时，其余结构错误照常一并返回（`details.errors` 全量），畸形入参一律 400、不得 500。

**报告反馈（feedback）**

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/api/v1/reports/{report_id}/feedback` | body `{verdict: "useful"\|"not_useful", comment?: str(≤500)}`；**upsert 语义**（一报告一票，重复提交=改票，`updated_at` 刷新）；回 `{report_id, verdict, comment, updated_at}` |
| `GET` | `/api/v1/reports/{report_id}/feedback` | 回 `{feedback: {...} \| null}`，供报告页/历史详情回显已投状态 |
| `GET` | `/api/v1/feedback?limit=&offset=` | 反馈列表（id / report_id / report_title / verdict / comment / updated_at）+ 聚合 `{useful_count, not_useful_count}`——验证仪表数据口（当前不做仪表 UI） |

**请求 / 响应细节（v0.14）**：
- POST 创建与改票同形，**恒回 200**：`{report_id, verdict, comment, updated_at}`。每次成功提交都刷新 `updated_at`（内容与上次相同也刷新，语义为「最近一次确认」）；`created_at` 保留首投时间，仅落库、不出现在响应中。
- POST 为**整条覆盖**：每次提交以本次 `verdict` + `comment` 替换已存内容，未带 `comment`（或为 `null`）即把已存补充清空为空串——调用方改票时须回传要保留的补充（Web 端以当前输入框内容提交，且回显读取完成前不允许投票）。
- 入参校验全部返回 400 `FEEDBACK_INVALID` 且不落库：body 不是 JSON 对象（含 `null` 与缺省 body；请求体根本不是合法 JSON 属传输层错误，沿用框架 422，与全部 API 一致）；`verdict` 缺失或不是 `"useful"` / `"not_useful"` 两个字面量之一（大小写敏感）；`comment` 不是字符串（`null` 或缺省视为空串）；`comment` 去首尾空白（服务端 Python `str.strip()` 口径）后超过 500 个 **Unicode 码点**（中文与单码点 emoji 各计 1，组合 emoji 如 👨‍👩‍👧 按所含码点计）。前端以 JS `trim()` + `Array.from` 同口径预检，两种空白集的细微差异只会让服务端计数不大于前端，不会拒绝前端已放行的内容。落库与回显的 `comment` 是去首尾空白后的文本。未知字段一律忽略——包括 `voter`：服务端当前恒写 `"local"`，API 不接受也不返回 voter。
- （v0.15 修订）`comment` 含无法以 UTF-8 编码的孤立代理项时，改由 §2 请求体边界校验在进入本端点前拦下，返回 400 `REQUEST_BODY_INVALID`；「不落库、不回 500」的实质约定不变，`parse_feedback` 自身的守卫作为纵深防御保留。
- 先校验入参再查报告；`report_id` 不存在时 POST 与单报告 GET 均返回 404 `REPORT_NOT_FOUND`。`message` 按失败原因给出业务文案（超长为「反馈内容过长（最多 500 字）」）。
- `updated_at` 为**带时区的 UTC ISO 串**（同 context-pack v0.13，通用规则见 §2.4），前端按本地时区展示。
- 并发重复提交（如双击、双标签页）收敛为同一行：写入走 §5.1 唯一约束上的单语句原子 upsert，不先查后写，不因竞态产生第二行或 500。
- `GET /feedback` 响应：`{items, total, limit, offset, aggregate: {useful_count, not_useful_count}}`。`items` 按 `updated_at` 倒序（同刻按 `id` 倒序），元素 `{id, report_id, report_title, verdict, comment, updated_at}`，`report_title` 取报告标题（`reports.task_title`）；分页沿用 §2 列表约定（默认 20、上限 50）；`total` 与 `aggregate` 统计全部反馈、不随分页变化。「有用占比」= `useful_count / (useful_count + not_useful_count)`，由消费方计算（样本量小时仅作观察）。

**任务、口径、反馈与请求体校验 error codes**

| code | HTTP | 触发情况 |
|---|---|---|
| `TASK_NOT_FOUND` | 404 | 任务详情 / 改名 / rerun 指向不存在任务 |
| `TASK_TITLE_INVALID` | 400 | PATCH 任务改名或 POST 创建任务时 title 为空、纯空白或超长（去首尾空白后按 Unicode 码点计 1–255）；一律不写库。无法 UTF-8 编码的 title 更早一层由 `REQUEST_BODY_INVALID` 拦下 |
| `SCHEMA_MISMATCH` | 400 | rerun 新文件 canonical 字段集与任务指纹不一致；details `{missing_fields, extra_fields, missing_fields_display, extra_fields_display}`（双向差异；`*_display` 为业务显示名，后端用当前活动包 `display_name` 映射，缺失回退 canonical 名） |
| `REPORT_ALREADY_LINKED` | 400 | 对已归属任务的报告再次 POST /tasks；details 带既有 `task_id` |
| `CONTEXT_PACK_VALIDATION_FAILED` | 400 | PUT /context-pack 校验失败；details `{errors: [...]}` |
| `CONTEXT_PACK_NOT_FOUND` | 404 | 活动包缺失且内置文件不可读的容错边界 |
| `FEEDBACK_INVALID` | 400 | body 非对象 / verdict 非法 / comment 非字符串或超长（细节见上方反馈段 v0.14）。含孤立代理项的 comment 自 v0.15 起由 `REQUEST_BODY_INVALID` 在边界拦下 |
| `REQUEST_BODY_INVALID` | 400 | 任一 `/api/v1/*` 的 JSON 请求体含无法以 UTF-8 编码的字符串（见 §2 请求体边界校验）；不写库、不调用模型 |

复用既有码：`REPORT_NOT_FOUND`（保存任务、提交或回显反馈时 report_id 不存在）、`UPLOAD_NOT_FOUND`（rerun 上传 session 失效）。

### 2.4 时间戳契约（v0.16）

时刻（绝对时间点）与业务日期是两类值。本节约束时刻的生成、存储、传输与展示；业务日期（`time_range.*`、上传数据中的日期 / 时间值）是业务日历上的值，原样存储与输出，不做时区换算。

1. **生成**：后端产生的所有时刻一律取 UTC（应用代码经 `app/timestamps.py` 的 `utc_now()` / `utc_now_iso()`）。进程所在时区（Docker 镜像默认 UTC、本地运行为宿主时区）不得影响任何存储值与对外值。
2. **存储**：SQLite 不保存时区。应用库的 datetime 列统一使用 `UTCDateTime`（写入时换算为 UTC 后去掉时区，读出时一律标注 UTC；写入无时区的 datetime 直接报错，防止误用 `datetime.now()` 让本地时间冒充 UTC），DDL 仍为 `DATETIME`，与既有库兼容。库中无时区的值按 UTC 解释，唯一例外是存量报告的 `reports.ran_at`（第 5 条）。
3. **对外格式**：API 响应中的所有时刻都是带显式偏移 `+00:00` 的 ISO 8601 字符串。库列（`created_at` / `updated_at` / `ran_at` 及派生的 `last_run_at` / `latest_report_at`）可带微秒；报告 payload 内的时刻（`metadata.ran_at`、`findings[].evidence.ran_at`、`previous_comparison.previous_ran_at`）精确到秒。历史报告的 payload 在读出时同样满足本条（第 5 条）：无偏移值按生成进程偏移换算，带其他偏移（如 `Z`、`+08:00`）的值统一换算为 `+00:00`，无法解析的值原样保留；响应中不出现无偏移的时刻串。分析循环注入模型的 `history_context.previous_ran_at` 同此格式。
4. **展示**：前端按查看者浏览器的本地时区格式化时刻，统一经 `frontend/src/lib/history.ts`：列表与状态行用 `MM/DD HH:mm`，报告署名「生成于」、运行信息与证据「运行时间」用 `YYYY-MM-DD HH:mm:ss`，结论脚注用 `HH:mm:ss`，上期对比段落的「上期报告生成于」用 `MM/DD HH:mm`，不直接渲染原始串；收到不带偏移的串（契约外输入）时原样显示，不做换算。展示不附时区标注，导出 PDF 跨时区传阅时的时区标注与推送渠道一并在周期运行契约中决定（第 7 条）。同一份报告经任一部署路径打开，只要查看者时区相同，显示就相同。
5. **存量兼容（只在读取时换算，不迁移数据）**：v0.16 之前生成的报告，`report_json` 内的时刻与由 `metadata.ran_at` 解析写入的 `reports.ran_at` 列都是**生成进程的本地时间**（Docker 生成的恰为 UTC，本地运行生成的为宿主时区），且不带时区。
   - 判别：`report_json.metadata.ran_at` 为不带偏移的字符串即为存量报告；带偏移、缺失、非字符串或无法解析均按新报告处理（`ran_at` 列即 UTC——旧写入路径在后三种情况下落库的正是当时的 UTC 时刻）。
   - 偏移推断：生成进程偏移 =（本地时间 − `reports.created_at`）按 15 分钟取整；`ran_at` 列用列值推断，payload 用 `metadata.ran_at` 推断（存量数据中两者相同，各自推断使任一侧被单独改写时另一侧仍然正确）。`created_at` 自持久层引入起恒为 UTC，且与 `ran_at` 在同一次运行内先后写入（compose 打点后紧接着落库，实际相差不足 1 秒）。取整残差超过 5 分钟、或偏移超出 ±14 小时，视为无法推断，按 UTC 解释。
   - 换算：读出时把该报告的 `ran_at` 列与 payload 内无偏移的 `metadata.ran_at`、`findings[].evidence.ran_at` 减去该偏移后按 UTC 输出；`previous_comparison.previous_ran_at` 取 `previous_report_id` 所指报告换算后的运行时刻（上期可能出自另一时区的进程），所指报告不存在时按本报告的偏移换算。存储保持原样。
6. **先后顺序**：报告的先后以换算后的运行时刻为准——任务报告链 `reports[]`、上期选择（§3.3 history_context）、数据源的引用报告、任务 `last_run_at` 与数据源 `latest_report_at` 均按此排序与取值。历史报告列表的 SQL 分页按 `created_at DESC, id DESC`：`created_at` 恒为 UTC，与运行时刻相差不足 1 秒，对真实数据与按运行时刻排序等价（仅同一秒内并发落库的报告先后可能互换，不影响业务），且不受存量 `ran_at` 时区歧义影响。
7. **周期运行衔接（周期运行契约必解项）**：日 / 周 / 月调度按**业务时区的墙上时间**触发（如「每周一 09:00」），既不是 UTC，也不是进程时区。周期运行契约须定义业务时区配置（IANA 名称如 `Asia/Shanghai`，以及作用域与默认值），并落到三处：① 调度触发——APScheduler 默认取进程时区（容器内为 UTC），必须显式传入业务时区；② 服务端渲染的时间（邮件、IM 卡片没有浏览器）按业务时区格式化并标注时区；③ 调度与推送新增的时刻列（如下次运行时间、推送时间）一律使用 `UTCDateTime`，调度计算在业务时区完成，落库换算为 UTC。存储与 API 继续遵守本节。同时须一并决定：④ Web 与导出 PDF 是否附时区标注（与推送渠道口径一致）；⑤ 模型 SQL 中 `'now'` / `'localtime'` 取的是查询引擎进程时区（容器内为 UTC），是否由 SQL Validator 拦截或按业务时区注入；⑥ 注入模型的 `previous_ran_at` 为 UTC，模型叙事若引用运行日期可能与页面本地日期差一天，由 prompt 约束（可随结论一致性相关的 prompt 调整一并处理）。周期身份判别（time_range 对齐）同为周期运行契约必解项（§3.3）。

---

## 3. 任务执行层 — 三阶段执行模型

### 3.0 总览

```
Analysis Workflow
  │
  ├── Phase A: Pre-analysis（确定性）
  │     Schema Profiler ──► 加载 Context Pack ──► 初始化分析会话
  │
  ├── Phase B: Analysis Loop（有界 agentic）
  │     ┌─── while not finished and within bounds: ───┐
  │     │  模型选择工具 → 执行（过执行控制层）→ 观察结果  │
  │     │  → 决定下一步（下钻 / 转维度 / 记录发现 / 停止）│
  │     └─────────────────────────────────────────────┘
  │
  └── Phase C: Post-analysis（确定性）
        Report Composer ──► Web payload ──► 历史持久化
```

### 3.1 Phase A — Pre-analysis（确定性）

**Schema Profiler**
- 职责：扫描数据源结构，生成供 LLM 理解的 schema 摘要
- 输入：`DataSourceRef { type: csv|xlsx|mysql|postgres, location, selected_sheet?, credentials_ref? }`
- 输出：`SchemaSummary { tables: [{name, columns: [{name, type, nullable, sample_values, distinct_count}], row_count_estimate}] }`
- 副作用：只读访问数据源；不调用 LLM

**加载 Context Pack**
- 从 SQLite `context_packs` 表读取活动包（`load_active_context_pack()`）：每次运行时读取、不做进程级缓存（包体积小、读开销可忽略，换取零缓存失效 bug）；表空 / 不可读时容错回落内置 JSON
- 内置 JSON artifact（`backend/app/context_packs/retail_operations_v1.json`）保持只读，承担三个角色：首次启动种子、恢复默认的还原源、校验测试 fixture（存储与版本语义见 §6.4）
- 将 metrics/dimensions/templates 格式化为 LLM 可理解的系统上下文（schema 见 Section 6）

**初始化分析会话**
- 构造系统 prompt = Schema 摘要 + Context Pack + 分析模板（如有匹配的 template）
- 任务重跑且任务链存在上期报告时，循环 user payload 附 `history_context`（构建规则见 §3.3，注入位置见 §6.3 槽位 7）；首期 / 未保存任务的单次报告不附
- 设置 ExecutionPolicy（bounds、timeouts）
- 当次运行内记录分析步骤；持久化后用于历史详情重建

### 3.2 Phase B — Analysis Loop（有界 agentic）

模型在 while 循环里自主选择工具、观察结果、决定下一步。循环持续直到模型调用 `finish` 或触达边界约束。

#### 工具集（5 个，固定，不可扩展）

**Tool 1: `query_data`**
- 职责：执行模型提交的受控 SQL，返回查询结果
- 输入（模型提供）：`{ sql: str, summary?: str }`
- 内部流程：模型提交 SQL → **SQL Validator**（执行控制层穿透点）→ **Executor** → 返回结果
- 输出（返回给模型）：`{ sql: str, columns: str[], rows: list[list], row_count: int, exec_ms: int, data_ref: str }`
- 约束：
  - 每次都过 SQL Validator（拒绝写操作、强制 LIMIT、校验字段存在性）
  - 敏感字段（`is_sensitive=true`）的原始值不返回给模型，替换为 `[MASKED]`
  - 超时 30s，硬上限 120s
- 当前实现：返回给模型的 `rows` 限前 5 行预览，完整结果通过 `data_ref` 在后续工具间引用（截断标注与全称判断约束见 §8 待定契约项）

**Tool 2: `profile_column`**
- 职责：获取字段的快速统计摘要
- 输入：`{ table: str, column: str }`
- 输出：`{ type, distinct_count, null_pct, min, max, top_values: [{value, count}] }`
- 约束：敏感字段拒绝 profile

**Tool 3: `create_chart`**
- 职责：从查询结果生成可视化
- 输入：`{ data_ref: str, chart_type: "line"|"bar"|"pie"|"table", title: str, x_axis?: str, y_axis?: str }`
- 输出：`{ chart_id: str, png_base64: str, echarts_spec: dict }`
- 说明：当前 Web 预览使用 ECharts spec；`png_base64` 为空或预留给邮件推送嵌入（规划中）

**Tool 4: `record_finding`**
- 职责：记录一条分析发现
- 输入：`{ type: "trend"|"anomaly"|"recommendation", text: str, evidence: str, confidence: "high"|"medium"|"low" }`
- 输出：`{ finding_id: str }`
- 说明：每条 finding 关联当前循环轮次的 SQL + 数据，构成可追溯链
- **evidence 引用解析（v0.12）**：`evidence` 允许是**装饰性引用串**（模型常写成 `"query-1(整体), query-2(门店)"` 或 `"query-5（渠道维度…）"`）。运行时解析顺序：① 整串精确命中 `runtime.queries` → 用之；② 否则按 `query-\d+` 正则提取**首个**引用，命中则用之；③ 均未命中则按 short note 处理（`sql` 为空，`evidence_ref` 保留模型原文）。命中时 `evidence_ref` **归一化为该 canonical 引用**（如 `query-5`），让报告的 SQL 追溯与 Report Composer 的自动配图（按 `evidence_ref` 查 `query_results`）在装饰写法下同样成立。归一化会丢弃模型附注，附注独立字段化（`evidence.note`）与「无依据结论降级标注」仍是**周期运行契约候选**（§7）

**Tool 5: `finish`**
- 职责：结束分析循环
- 输入：`{ summary: str }`
- 输出：无（终止循环信号）
- 说明：模型主动判断"信息足够了"

#### 边界约束（硬性，实现侧不得自行放宽）

| 约束 | 默认值 | 硬上限 | 说明 |
|------|--------|--------|------|
| 分析步骤数 | 12 | 15 | 上限作用于循环轮次（for-range 实现，每轮至多一次工具调用）；计数口径见 §3.3 metadata（`loop_rounds` / `steps_recorded`） |
| Token 消耗 | 50K | 100K | 含输入+输出，BYOM = 用户的钱 |
| 执行时间 | 5 min | 10 min | 含所有 SQL 执行和 LLM 调用 |
| 单次 SQL 超时 | 30s | 120s | Executor 层强制 |

#### 降级策略

当任一约束触顶且模型尚未调用 `finish`：
1. 停止循环，不再调用 LLM
2. 以已有的 `findings` 组装报告
3. 报告头部标注：`⚠️ 分析因资源限制未完成，以下为部分结论`
4. 记录触顶原因到执行日志

**绝不**：静默失败、无限重试、吞掉错误。

#### Analysis Loop step codes

Analysis Loop 在 `analysis_steps[].code`（step.status=`failed`）或 `warnings[].code` 中暴露以下控制层信号；前端折叠展示，不阻断报告生成：

| code | 触发情况 | 出现位置 |
|---|---|---|
| `SQL_VALIDATOR_REJECTED` | 模型提交的 SQL 未通过 Validator | step |
| `TOOL_INVOCATION_FAILED` | 工具内部参数错误或运行异常（如未知字段、未知 query_ref） | step |
| `LLM_PARSE_FAILED` | 模型返回不是合法的 `{tool, args}` JSON | step |
| `LLM_CALL_FAILED` | 模型 API 调用失败（鉴权/网络/超时） | warning，触发后立即停止循环输出部分报告 |
| `LOOP_BUDGET_EXCEEDED` | 迭代/token/duration 任一触顶 | warning，部分报告 |

#### 模块契约变更说明

| 原 v0.1 模块 | v0.2 状态 | 说明 |
|-------------|-----------|------|
| Schema Profiler | ✅ 保留 | Pre-analysis 阶段，契约不变 |
| Query Planner | 🔄 退役 | 模型在循环中自主规划，不再需要独立模块 |
| SQL Generator | 🔄 内嵌 | 内嵌于 `query_data` 工具，不再独立暴露 |
| SQL Validator | ✅ 保留 | 每轮 SQL 必过，是执行控制层穿透点，契约不变 |
| Executor | ✅ 保留 | `query_data` 内部调用，契约不变 |
| Chart Generator | ✅ 保留 | `create_chart` 调用 + Post-analysis 定稿，契约不变 |
| Insight Writer | 🔄 退役 | 模型通过 `record_finding` 自主记录洞察 |
| Report Composer | ✅ 保留 | Post-analysis 阶段组装最终报告，契约不变 |

> 被"退役"不是删除代码——是其职责被 agentic 循环吸收。保留模块仍以纯函数 + Pydantic 模型实现。

### 3.3 Phase C — Post-analysis（确定性）

**Validation Rules 执行**
- Context Pack 保留 `validation_rules[]`，当前不新增独立阻断式规则引擎（仅在 pack 保存时校验 severity 枚举合法，见 §6.4）。
- 后续若启用规则引擎，应对 Analysis Loop 产出的 findings 和查询结果做确定性校验，不由模型判断。
- severity=error 的违规应标红并在报告中警告；是否阻断报告需要在对应设计文档中单列确认。

**图表定稿**
- 收集循环中所有 `create_chart` 的产出
- 统一样式、排版
- 当前 Web 使用 ECharts spec；`png_base64` 暂为空或预留，邮件推送（规划中）再启用 PNG 产物

**Report Composer**
- 输入：`{ task_meta, context_pack.report_preferences, findings[], charts[], validated_sql_trail[], history_context? }`
- 输出：结构化 `ReportPayload` dict（Web payload），包含 `status/title/summary/kpis/findings/warnings/metadata/analysis_steps` 与可选顶层 `previous_comparison`
- metadata 计数契约（v0.8 起）：
  - `loop_rounds: int`——已发起 LLM 调用的循环轮数（含调用失败的轮次）；体验模式（未配置模型）为 `0`
  - `steps_recorded: int`——`len(analysis_steps)`（含 failed step）。两者差异真实存在：预算触顶 / `LLM_CALL_FAILED` 的轮次产生 warning 不产生 step
  - `iterations_used: int`——**deprecated 别名**，值恒等于 `steps_recorded`（其历史语义本就是步骤数，不变义；周期运行阶段收口时评估移除）。序列化层对 payload 中没有整数 `loop_rounds` 的旧报告输出 `null`，不补算
- 顶层 `previous_comparison` 契约（仅任务重跑且存在上期报告时出现；由共享 runner 在 compose 时**确定性组装**，不依赖模型输出；体验模式与真实 LLM 两条报告路径共用）：

```
previous_comparison {
  previous_report_id: str             # 追溯锚点（唯一权威位置，metadata 不重复存）
  previous_ran_at: str                # 上期运行时刻，带时区 UTC（§2.4）
  previous_status: "completed" | "partial"   # partial 时前端段落头标注「上期分析未完整」
  previous_time_range: {...} | null   # 上期 metadata.time_range
  same_period: bool                   # 上期与本期 time_range 相同或重叠 → true，前端标题改为「与上次运行对比（相同时间窗）」，避免同期重跑被误读为周期环比
  baseline: [{ name, unit, previous_value | null, current_value, delta_value | null, delta_unit: "%" | "pp",
               severity: "normal" | "significant" | "critical" | null }]
                                      # 本期 KPI 与上期 baseline_values 按指标名对齐（以本期 kpis 顺序为准），代码计算差值；
                                      # 率值指标（KPI unit 为 "%"，如退款率）取百分点差（delta_unit="pp"，current − previous），
                                      #   其余取变化率（"%"，(current − previous) / previous × 100）；delta_value 保留 2 位小数
                                      # severity（v0.10）由服务端按活动包 report_preferences.anomaly_thresholds 计算：
                                      #   仅 delta_unit="%" 且 delta_value 非 null 的条目参与，|delta_value| ≥ critical_pct → "critical"，
                                      #   ≥ significant_pct → "significant"，否则 "normal"；"pp" 条目与不可比条目恒为 null（当前不着色）；
                                      #   前端只按 severity 映射颜色，不自行查阈值（阈值经业务口径编辑后自动生效）
                                      # 上期缺某指标（previous_value=null）或上期值为 0 时 delta_value 为 null，不编造
  summary_note: str                   # 上期报告执行摘要原文（可展开证据）
}
```

- **双「上期」口径分工（v0.9 裁决）**：KPI 总览的环比是**文件内相邻周期对比**（由本次上传文件的双窗口计算，byline/卡片标注「本文件内环比」）；`previous_comparison` 独占**跨报告对比**（对上期报告存档 KPI）。两者数值因数据重导出可能不同，属预期行为——前端各自标注口径，不做数值调和
- 不扩展 finding type 枚举（`trend|anomaly|recommendation` 维持封闭集合）；「证据可展开 / 跳转上期」由前端调既有 `GET /api/v1/reports/{previous_report_id}`，不新增 API
- 每条结论关联：SQL 原文、数据源、运行时间、分析步骤序号
- **体验模式固定报告（v0.17 登记）**：未配置或已关闭模型（`/model-status` 为 `not_configured` / `disabled`）时，共享 runner 以确定性固定流程生成报告（不调用模型，`loop_rounds = 0`）；生成成功时 `status` 为 `completed`，`warnings[]` 含 `FALLBACK_REPORT`（数据校验失败时照常返回 `failed` 与对应错误码，不附此码）；前端按通用 warning 展示其 `message`。更早版本以 `P0_THIN_LOOP` 发出同一信号，已落库的旧报告保留原码，消费方按 `message` 展示、不按 code 分支
- **订单状态取值无法识别（v0.18 登记）**：物化时 `order_status` 按 §6.4 归一化后仍有无法识别的取值（含空值）时，报告 `warnings[]` 含 `ORDER_STATUS_UNRECOGNIZED`，`message` 写明行数与示例取值；这些行保留原值，不参与任何核心指标（销售额、订单数、客单价，以及退款率的分子与分母）。体验模式与真实模型两条报告路径共用；数据中没有订单状态列时不产生此 warning

**history_context 运行时构建**

- 来源：本任务报告链中运行时刻（§2.4 第 5 条换算后的 `ran_at`）最新的一份报告（并列时按 `created_at`、`id` 取后者；failed 报告不落库，链上只有 completed/partial）
- 结构：`{ previous_report_id, previous_ran_at, previous_status（上期 report.status：completed | partial，v0.10 补，供 previous_comparison 透传）, previous_time_range, last_run_summary（上期 report.summary）, baseline_values（从上期 report_json.kpis 提取的 {指标名: current 数值}，非数值项跳过） }`
- 注入：作为循环 user payload 的 `history_context` 键（与 `context_pack` 平级，仅 rerun 且有上期时出现）；SYSTEM_PROMPT 增加一条静态规则——payload 含 history_context 时，分析须对照上期基线，结论引用上期数值需注明来自上期报告
- **不写回 Context Pack**：pack JSON 内的 `history_context` 字段为兼容占位（§6.1），运行时来源是任务报告链，不是 pack
- token 控制：baseline_values 只取 KPI 数值，不携带上期 findings 全文（与 §4.3 token 预算联动）
- 边界与假设（v0.9）：上期 `kpis` 为空（partial 降级可能返回空数组）时 `baseline` 为空数组，段落仍出现并显示「上期无可对比指标」；上期与本期 time_range 相同/重叠时置 `same_period=true`（§3.3 previous_comparison）。**「链序 = 期序」是当前版本的显式假设**——同一任务的周期身份判别（time_range 对齐、同期重跑去重）列为**周期运行契约必解项**，调度实现不得直接继承该假设

**通知投递（预留）**
- 定时任务、Email（SMTP）/ Webhook、HTML 邮件和图表 PNG 嵌入均为预留能力
- 当前报告只做 Web 展示与历史持久化

---

## 4. 执行控制层 — 硬约束（实现侧不得自行放宽）

### 4.1 数据安全约束

| 控制点 | 策略 | 配置位置 |
|--------|------|---------|
| 数据库账号权限 | 只读（仅 SELECT） | 数据源配置时强制校验 |
| SQL 语句类型 | 拒绝 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/CREATE | SQL Validator 硬编码 |
| 大表查询 | 自动 LIMIT，默认 `max_rows=10000` | `ExecutionPolicy.max_rows` |
| 全表扫描 | 无 WHERE + 无 LIMIT → 拒绝 | SQL Validator |
| 字段存在性 | 引用不存在字段 → 拒绝 | SQL Validator + SchemaSummary |
| 敏感字段 | `is_sensitive=true` 的字段值不进 LLM | `query_data` 工具 + Context Pack |
| 凭证安全 | API Key / SMTP 密码不入日志、不入报告 | 全局日志过滤 + 报告渲染过滤 |
| UI 模型配置 | `data/llm_config.json` 文件权限 600；`enabled=false` 显式关闭模型且不回落 `.env`；api_key 不入 GET 响应 / 日志 / 报告，错误信息经 `sanitize_error` 脱敏 | `llm_config` API + 全局日志过滤 |
| Context Pack 编辑 | 保存时服务端全量校验（§6.4 四层，error 即整体拒绝）；序列化 ≤ 64KB（存储层病态防护）+ prompt 注入体积警戒（`context_pack_for_llm` 估算超 6K token 时保存成功但返回 warning，提示分析预算可能提前触顶）；`meta.name` / 表名 `sales_orders` / canonical 列集 / `display_name` 冻结，服务端强制 | `context-pack` API + §6.4 校验 |

#### SQL Validator 策略

查询层使用临时 SQLite，仅暴露 canonical `sales_orders` 查询表。上传数据进入查询层前先按 Context Pack alias 和本地 fallback alias 映射为 canonical 字段，例如 `订单日期` → `order_date`、`销售额` → `net_sales_amount`。

SQL Validator 使用 AST 解析执行固定规则：只允许单条 `SELECT`、只允许 `sales_orders`、拒绝写操作/DDL/PRAGMA/ATTACH、多语句、未知表、未知字段和顶层 `SELECT *`；允许 `COUNT(*)`、聚合、`CASE`、`GROUP BY`、`ORDER BY` 输出别名。

LIMIT 策略固定为：无 `WHERE` 且无 `LIMIT` 直接拒绝；有 `WHERE` 但无 `LIMIT` 自动补 `LIMIT 10000`；已有 `LIMIT` 超过 `10000` 时收敛为 `LIMIT 10000`。Executor 侧再通过 SQLite read-only authorizer 做第二层只读防线。

### 4.2 LLM 交互约束

| 控制点 | 策略 | 配置位置 |
|--------|------|---------|
| 发给 LLM 的数据 | 仅 schema + 聚合摘要 + 查询结果，不发原始大批量明细 | `query_data` 自动截断 |
| SQL 透明度 | 报告必须显示完整 SQL，不可关闭 | Report Composer |
| LLM 单次超时 | 60s，硬上限 180s | `ExecutionPolicy.timeouts.llm` |

### 4.3 Analysis Loop 约束（v0.2 新增）

| 控制点 | 策略 | 配置位置 |
|--------|------|---------|
| 分析步骤上限 | 默认 12 步，硬上限 15 步 | `ExecutionPolicy.loop.max_iterations` |
| Token 预算 | 默认 50K，硬上限 100K | `ExecutionPolicy.loop.max_tokens` |
| 时间上限 | 默认 5 min，硬上限 10 min | `ExecutionPolicy.loop.max_duration` |
| **每轮 SQL 校验** | 循环内每一轮 SQL 都过 Validator，不是只验一次 | SQL Validator |
| 降级策略 | 触顶 → 输出已有发现 + 标注未完成 | Analysis Workflow 硬编码 |

### 4.4 业务流程约束

| 控制点 | 策略 | 配置位置 |
|--------|------|---------|
| 定时任务首次启用 | 用户手动确认（不可 auto-on） | 任务状态机 `draft→confirmed→active` |
| 邮件首次发送 | 测试邮件 + 用户确认后才进入定时 | 任务状态机 |

**违反任意一条 = 阻断式 bug，不允许实现侧自行权衡放宽。如需调整，必须先出方案并经维护者人工评审确认，再同步更新本契约。**

---

## 5. 数据流总览

```
[用户] ──配置/确认任务──► [业务产品层]
                          │
               手动运行   ▼
                   ┌─── Analysis Workflow ───┐
                   │                  │
                   │  Phase A: Pre    │
                   │  Schema Profiler │
                   │  + Context Pack  │
                   │       │          │
                   │       ▼          │
                   │  Phase B: Loop   │
                   │  ┌────────────┐  │
                   │  │ query_data │◄─┤── SQL Validator（每轮）
                   │  │ profile    │  │
                   │  │ chart      │  │
                   │  │ finding    │  │
                   │  │ finish ────┼──┤── 或触达边界
                   │  └────────────┘  │
                   │       │          │
                   │       ▼          │
                   │  Phase C: Post   │
                   │  Validate rules  │
                   │  Chart finalize  │
                   │  Report Compose  │
                   └───────┬──────────┘
                           ▼
                    Web 预览 JSON
                           │
                    React + ECharts
                           │
                    写入 SQLite 历史

规划中：调度器触发后复用同一 Analysis Workflow，并把报告投递到 SMTP/Webhook。
```

### 5.1 持久层数据模型

持久层位于 `backend/app/db/`（SQLAlchemy 2.0 ORM）；DB 由 `APP_DB_URL` 指定（默认 `sqlite:///./data/app.db`，落持久卷 `data/`）。SQLite 相对路径由 engine boundary 统一锚定到**仓库根目录**，不随启动命令的当前工作目录变化；因此默认 URL 始终指向仓库根下的 `data/app.db`。绝对 SQLite 路径保持原语义，Docker 的 `sqlite:////app/data/app.db` 仍指向 `/app/data/app.db`。报告 payload 整体以 JSON 列存储（`ReportPayload` 已是稳定结构化 dict，不拆多表）。v0.8 起新增 `analysis_tasks` / `context_packs` / `report_feedbacks` 三表与 `reports.task_id` 一列。

**无 Alembic 演进策略（v0.8 起）**：启动时 `Base.metadata.create_all()` 只创建**缺失的表**，不会给既有表加列。既有表加列必须经启动期 `ensure_columns()` 助手（PRAGMA table_info → `ALTER TABLE ADD COLUMN`），且**仅允许可空或带默认值的列**；禁止改名、删列、改类型。每次涉及加列的变更必须包含「旧库文件启动后自动升级且数据完好」的测试与验收（迄今唯一加列为 `reports.task_id`）。

**应用库当前仅支持 SQLite（v0.9 声明）**：`APP_DB_URL` 为非 sqlite 方案时启动 fail-fast 报错拒绝（`ensure_columns` 的 PRAGMA 机制为 SQLite 专有，不做方言适配）；PostgreSQL / MySQL 仅是规划中数据源直连的目标数据库，不是应用库选项。

**时刻列（v0.16）**：下列模型中的 `datetime` 字段列类型均为 `UTCDateTime`（§2.4 第 2 条），库中存不带时区的 UTC；DDL 仍为 `DATETIME`，既有库无需变更。`Report.ran_at` 的存量行是生成进程的本地时间，按 §2.4 第 5 条在读取时换算。

```
Dataset {
  id: uuid (pk)
  created_at: datetime
  data_source_ref_json: json          # DataSourceRef
  schema_summary_json: json           # SchemaSummary
  preview_json: json                  # head / tail 预览
  field_profile_json: json            # 字段识别结果
  file_path: str                      # data/uploads/...（样例数据为内置）
  file_name: str
  row_count: int
  column_count: int
}

Report {
  id: uuid (pk)
  created_at: datetime
  dataset_id: uuid (fk → Dataset)
  task_id: str | null (fk → AnalysisTask, index)   # v0.8 加列（ensure_columns）：任务归链；旧报告与未保存任务的报告为 NULL
  task_title: str
  analysis_goal: str
  structured_task_json: json           # StructuredTask，用于历史详情只读重建
  metrics_json / dimensions_json: json
  comparison: str
  context_pack_name: str
  context_pack_version: str            # 生成时活动包有效版本（出厂 "1.0.0" 或 "1.0.0-local.N"，见 §6.4）
  report_json: json                   # 完整 ReportPayload（§3.3 Report Composer 产出；含 loop_rounds/steps_recorded 与可选 previous_comparison）
  status: str                         # completed | partial | failed
  summary: str
  model_used: str
  iterations_used: int                # 语义钉死 = 记录步骤数（steps_recorded）；不加 loop_rounds 列，序列化层从 report_json 读取
  token_used: int
  ran_at: datetime                    # 运行时刻（compose 时打点，由 metadata.ran_at 解析写入）；v0.16 起为 UTC，存量行见 §2.4 第 5 条
}

AnalysisTask（表名 analysis_tasks，v0.8 新增）{
  id: uuid (pk)
  created_at: datetime
  title: str(255)                      # 默认取 structured_task.task_title，保存时可改
  analysis_goal: text
  structured_task_json: json           # 保存时的 StructuredTask 完整快照
  schema_fingerprint: str(80) (index)  # "v1:" + sha256 hex（§5.2）
  schema_fingerprint_json: json        # { version: 1, canonical_fields: [...], computed_with_pack: {name, version} }
  context_pack_name: str(120)          # founding report 生成时的活动包身份（时点口径见 §5.2，不取保存时活动包）
  context_pack_version: str(40)
  source_dataset_id: str(36) (fk → Dataset)   # founding 数据集（指纹来源）
  status: str(32) = "active"           # 当前只写 "active"，列先建，避免启用状态机时再加列；不提供状态变更 API
}
# 不存 run_count / last_run_at 冗余列：由 reports.task_id 计数 / 换算后运行时刻的最大值（§2.4 第 6 条）派生

ContextPackRecord（表名 context_packs，v0.8 新增）{
  id: uuid (pk)
  name: str(120) (unique)              # 业务身份键（当前不可改名）
  base_version: str(40)                # 种子或跟随时的出厂版本，如 "1.0.2"（revision 0 时随出厂更新，§6.4）
  revision: int = 0                    # 单调递增，永不重置（恢复默认也 +1）；版本语义见 §6.4
  payload_json: json                   # 完整 ContextPack（§6.1 schema）
  created_at / updated_at: datetime
}

ReportFeedback（表名 report_feedbacks，v0.8 新增）{
  id: uuid (pk)
  report_id: str(36) (fk → Report)
  voter: str(64) = "local"             # 当前恒为 "local"（单实例单投票人的有意简化）；推送给多位读者时复核，API 届时才暴露
  verdict: str(16)                     # "useful" | "not_useful"
  comment: text = ""                   # ≤ 500 字符
  created_at / updated_at: datetime
  unique(report_id, voter)             # 一（报告 × 投票人）一票（upsert）；复合键 v0.9 预留，避免日后引入多投票人时撞上「无 Alembic 策略无法改约束」的死角
                                       # v0.14：约束名 uq_report_feedbacks_report_id_voter；写入为该约束上的单语句
                                       # INSERT … ON CONFLICT DO UPDATE（SQLite ≥ 3.24），并发重复提交收敛为一行
}
# report_feedbacks 为纯新增表：旧库启动时由 create_all 补建，不涉及 ensure_columns 加列
```

历史/数据源读取端点见 §2.2；任务 / context-pack / feedback 端点见 §2.3。

### 5.2 schema_fingerprint 契约

「同结构」的判定口径是 **canonical 映射后字段集合**，不是原始列名、不比类型。依据：查询层只把经活动 Context Pack alias 映射成功的列写入 canonical 查询表，未映射列对分析完全不可见——分析意义上的同结构 = canonical 字段集相同。原始列名比对会把「列序调整 / 无关列改名」误判为异构；类型比对会被 pandas 推断噪声污染。

```
算法（v1）：
  canonical_fields = sorted(去重后的 canonical 字段集合)     # 来自 field_profile 映射结果
  schema_fingerprint = "v1:" + sha256(",".join(canonical_fields)).hexdigest()

判定（rerun 时）：任务.canonical_fields == 新文件.canonical_fields（集合双向严格相等）
  不等 → 400 SCHEMA_MISMATCH, details = {
    missing_fields: [任务有而新文件无],
    extra_fields:   [新文件有而任务无],
  }
```

- `"v1:"` 前缀留演化空间（多表时升 v2）。比对用 `schema_fingerprint_json.canonical_fields` 做集合 diff（可诊断），hash 仅做快速等值与索引。
- `extra_fields` 同样阻断：新文件多映射出 `unit_cost` 会解锁毛利指标，报告链失去可比性。当前从严，文件数据源周期接入时再议容差。
- **时点口径（v0.9 钉死）**：保存任务时 canonical_fields **直接读取 founding dataset 存量 `field_profile_json`**（即 founding report 分析实际使用的字段集），`computed_with_pack` 记录 founding report 的 `context_pack_name/version`（Report 表已存）——保证任务定义与报告链第一份报告严格自洽，摄取→保存窗口内的 pack 编辑不产生歧义。rerun 比对时新文件的 canonical 集合用**当时活动包**即时计算。用户编辑别名后旧任务可能对新文件 mismatch——这是诚实暴露而非 bug，details 指出差异字段（含业务显示名），产品文案同时覆盖「导出模板变化」与「别名编辑」两个成因方向。
- **展示名映射由后端负责（v0.9）**：SCHEMA_MISMATCH details 与任务详情序列化附 `display_name`（当前活动包 data_dictionary 列的 `display_name` 字段，缺失回退 canonical 名）；前端只渲染不查表。
- **另存新任务的代价与容差候选（v0.9 登记）**：另存新任务 = 开启新报告链，首期无 `previous_comparison`（对比中断）——该代价在产品文案中显式声明。文件数据源周期接入时容差讨论的首选候选：「按任务既有字段集投影重跑（用户确认后忽略多出字段）」——确定性且保持报告链可比性。

---

## 6. Context Pack Schema

Context Pack = 行业/场景的结构化业务知识包。存储于 SQLite `context_packs` 表并支持 Web 编辑（存储 / 版本 / 校验见 §6.4，API 见 §2.3）；内置 JSON artifact 降级为**出厂镜像**（首次启动种子、恢复默认还原源、校验测试 fixture）。`history_context` 的运行时来源是任务报告链（§3.3），pack 内同名字段为兼容占位。每次分析时注入 agentic 循环的系统 prompt。默认提供 `Retail Operations` 作为首个示例 pack，但 schema 本身保持行业无关，未来可承载多个 vertical pack。

### 6.1 完整 Schema

```
ContextPack {
  meta: {
    name: str                           # "Retail Operations"
    version: str                        # "1.0.0" (semver)
    description: str                    # 简要说明适用场景，如"零售经营分析示例 pack"
  }

  business_context: {
    company_description: str            # 公司/业务背景
    domain_notes: str                   # 领域特定说明（如季节性规律）
  }

  data_dictionary: {
    tables: [{
      name: str                         # "sales_orders"
      description: str                  # "销售订单表，每行一笔订单"
      columns: [{
        name: str                       # "net_sales_amount"
        display_name: str               # "净销售额"——业务显示名（任务详情 chips / SCHEMA_MISMATCH 提示用，§5.2）；当前冻结不可编辑
        description: str                # "订单净销售额（元）"
        data_type: str                  # "decimal"
        is_sensitive: bool              # true → 值不进 LLM
        aliases: [str]                  # ["销售额", "GMV", "实收销售额"]
      }]
      common_joins: [str]               # ["LEFT JOIN products ON sales_orders.product_id = products.id"]
    }]
  }

  metrics: [{                           # ★ 语义层核心：指标口径库
    name: str                           # "销售额"
    calculation: str                    # "SUM(net_sales_amount) WHERE order_status = 'completed'"
    unit: str                           # "元"
    aliases: [str]                      # ["GMV", "营业额"]
    time_grain: str                     # "daily" | "weekly" | "monthly"
    notes: str                          # "环比下降超10%需关注"
  }]

  dimensions: [{                        # ★ 语义层核心：分析维度
    name: str                           # "门店"
    column_ref: str                     # "stores.store_name"
    description: str                    # "零售门店名称"
    drill_path: [str]                   # ["区域", "城市", "门店"]
  }]

  analysis_templates: [{                # 引导 agentic 循环方向
    name: str                           # "零售周度经营回顾"
    trigger: str                        # "weekly"
    description: str                    # "每周一生成上周零售经营概览"
    required_metrics: [str]             # ["销售额", "订单量", "客单价"]
    default_dimensions: [str]           # ["门店", "商品类目"]
    analysis_steps: [str]               # 引导分析思路的自然语言步骤
  }]

  validation_rules: [{                  # Post-analysis 确定性校验
    name: str                           # "销售额非负"
    check: str                          # "销售额 >= 0"
    severity: "error" | "warning"
    message: str                        # "销售额出现负值，请检查退款或冲销数据是否重复扣减"
  }]

  report_preferences: {
    language: str                       # "zh-CN"
    tone: "professional" | "concise" | "detailed"
    chart_style: str                    # "clean" | "business"（预设样式）
    anomaly_thresholds: {
      significant_pct: float            # 10.0（变动超10%标黄）
      critical_pct: float               # 30.0（变动超30%标红）
    }
  }

  history_context: {                    # 兼容占位字段：运行时来源是任务报告链（§3.3），不读写本字段；PUT 时忽略入参原样保留
    last_run_summary: str               # （占位）上次分析的关键结论
    baseline_values: {str: float}       # （占位）基线指标值
    ongoing_notes: [str]                # （占位）持续关注事项；维护能力当前不做
  }
}
```

### 6.2 设计要点

| 设计决策 | 理由 |
|---------|------|
| `metrics` + `dimensions` 是核心 | 对标 Dot DotML、ThoughtSpot 治理语义层——口径一致性是分析质量的基础 |
| `analysis_templates` 引导但不强制 | 注入 prompt 后模型可偏离（如数据指向预期外方向）——保留探索性 |
| `validation_rules` 后续确定性执行 | 当前只读保留规则定义（仅校验 severity 枚举）；后续启用时由代码遍历执行，不由模型判断 |
| `history_context` 运行时来自任务报告链 | 重跑时从上期报告动态构建并注入（§3.3），不写回 pack；pack 内字段为兼容占位 |
| `is_sensitive` 联动执行控制层 | 标记为敏感的字段值不进 LLM，`query_data` 返回时自动 mask |
| `Retail Operations` 只是首个示例 pack | 用于内置演示，不把零售固化到 schema 和底层接口 |
| 单 pack，DB 存储 + 出厂 JSON 镜像 | 一个部署先跑通一个场景；编辑后以 DB 为准、出厂镜像负责种子与还原（§6.4）；多 pack 留给后续扩展（≥2 个垂直时再做加载机制） |

### 6.3 Context Pack 注入方式

分析会话初始化时，Context Pack 被格式化为系统 prompt 的一部分：

```
System Prompt 结构:
1. 角色定义（你是数据分析 Agent，任务是...）
2. 业务背景（来自 business_context）
3. 数据字典（来自 data_dictionary，排除 is_sensitive 字段的值说明）
4. 指标口径（来自 metrics，格式化为规则列表）
5. 分析维度（来自 dimensions，含下钻路径）
6. 分析引导（来自匹配的 analysis_template，如有）
7. 历史上下文（任务重跑时注入从任务链上期报告构建的 history_context（§3.3），首期 / 未保存任务的单次报告无此节；不读写 pack 内占位字段）
8. 工具使用说明（5 个工具的调用方式）
9. 报告风格要求（来自 report_preferences）
```

### 6.4 Context Pack 存储 / 版本 / 编辑校验

**存储与种子**：活动包存 `context_packs` 表（§5.1）。应用启动时表空则以内置 JSON 种子写入（`revision=0`）；运行期读取失败容错回落内置文件（同时记录 `CONTEXT_PACK_NOT_FOUND` 边界）。内置 JSON 永远只读不动。

**未编辑的活动包跟随出厂（v0.18）**：应用启动时，若活动包 `revision == 0`（从未经 PUT 或 reset 保存）且其内容（忽略 `meta.version`）或 `base_version` 与当前内置出厂包不同，就改写为当前出厂内容，`base_version` 更新为出厂 `meta.version`，`revision` 仍为 0；`revision ≥ 1` 的活动包一律不动（用户修改过或恢复过默认）。这样升级带来的出厂口径更新会自动到达未编辑的部署，界面不会把「出厂内容已更新」误显示为「已修改」。改写以 `revision == 0` 为条件执行，与同时发生的保存互不覆盖。为保证下文的版本串唯一，**内置出厂包的内容每次变化都必须提升 `meta.version`**；测试按版本登记出厂内容摘要（只追加），内容变化而版本号未提升即失败。

**版本语义**：每次保存（PUT 或 reset）`revision + 1`，永不重置、永不回退。有效版本串（写入 `payload.meta.version`、报告与上传响应的 `context_pack_version`）：

```
revision == 0  →  base_version            # 出厂态，如 "1.0.0"
revision >= 1  →  "{base_version}-local.{revision}"   # 如 "1.0.0-local.3"
```

单调计数保证一个部署内版本串唯一：任何一份历史报告的口径版本都能唯一指认当时的口径内容（可追溯链从 SQL 层延伸到语义层），也是 eval「口径修改被捕获」断言的基础。semver 自动 bump 的方案存在「恢复默认后重编辑产生同号不同内容」缺陷，故不采用。**恢复默认（reset）**：payload 还原为内置内容，`revision` 照常 +1。

**编辑范围**：UI 仅开放三块——metrics（calculation / aliases / unit / notes）、data_dictionary 列的 aliases / description、`report_preferences.anomaly_thresholds`。结构性要素（表名、canonical 列名集合、`display_name`、指标增删、`meta.name`）当前冻结：SQL Validator 按固定单表 + 已知字段做白名单校验（§4），开放结构编辑等于让用户修改安全边界的依据；结构扩展属后续行业包扩展工作。

**别名权威（v0.11）**：字段识别的别名来源**唯一**是活动包 `data_dictionary` 列的 `aliases`（外加 canonical 列名自身）。`field_mapping` 内置的 `CANONICAL_ALIASES` 回退表降级为「活动包不含该 canonical 列时」的兜底——内置包已覆盖全部 canonical 列且其 aliases 是回退表的超集，因此该降级对出厂态零行为变化，但它是「删除别名 → 该列不再被识别」这条因果链成立的前提（§7 capture 断言依赖）。基于列名 / 数据类型的推断（`infer_by_name_and_type`，仅 `order_date` / `net_sales_amount`）不属别名机制，保留不变。

**订单状态取值归一化（v0.18）**：物化时 `order_status` 的取值先去首尾空白、转小写，并把空格与连字符视为下划线，再按内置同义词表（`dataset_store.ORDER_STATUS_ALIASES`）映射到分析口径的三个取值——`completed`（如 已完成、交易成功、已付款、已发货、已签收、paid、shipped、delivered）、`partial_refund`（如 部分退款、部分退货、partially_refunded）、`refunded`（如 已退款、全额退款、退货、returned）。无法识别的取值（如 已取消、待付款、交易关闭）原样保留，并在报告中给出 `ORDER_STATUS_UNRECOGNIZED`（§3.3）；一个取值都无法识别时（如数字编码）整列保留原值与原类型；数据没有订单状态列时，全部行按 `completed` 计。同义词表是数据接入的确定性规则，不放进活动包、不在界面编辑。核心 KPI 只统计这三种状态的行：销售额、订单数与客单价计 `completed` / `partial_refund`，退款率 = (`refunded` + `partial_refund`) / 三种状态合计；出厂口径的 `calculation` 与此写法一致。

**单次运行同源（v0.13）**：一次请求 / 运行（样例与上传预览、`/tasks/parse`、`/reports/run`、`/tasks/{id}/rerun`、eval 用例）只解析**一次**活动包快照，并把同一快照显式传给该运行内的全部口径消费方——字段识别、**数据物化**（`materialize_table_to_sqlite` 决定哪些列进入 `sales_orders` 分析表，即 SQL 实际可见的字段）、prompt 注入、异常阈值、报告与数据集记录的 `context_pack_version`。物化环节不得再次读取活动包：否则并发保存口径时，报告记录的版本与实际参与 SQL 的列集可能分属两版口径，可追溯链在语义层断开。rerun 的指纹比对与物化共享同一快照，服务端重跑由此对口径编辑原子（前端预检语义见 §2.3）。只有未显式传入快照的调用方才自行读取一次活动包（兼容入口）。

**保存校验（四层，全部服务端执行；任一 error 级失败整体拒绝，HTTP 400 + details.errors 全量）**：

| 层 | 规则 |
|---|---|
| 1 结构层 | 复用既有 `validate_context_pack`：必需节存在；必需 metrics（销售额/订单数/客单价/退款率）不可删；必需 canonical 字段的 aliases 非空（v0.13：逐字段报告，文案用业务显示名、`path` 定位到该列 aliases——这是编辑器 UI 唯一可触发的结构层错误；其余结构错误只可能来自绕过 UI 的 API 调用，统一以「业务口径结构不完整」包装原因） |
| 2 字段层 | metric name 非空且唯一；calculation 非空；aliases 为非空字符串列表；**别名冲突检测**（同一 normalize 后的 alias 映射到两个不同 canonical 列 → error，堵住现状静默后写覆盖的口径事故面）；表名必须仍是 `sales_orders`、canonical 列名集合与各列 `display_name` 与内置版完全一致（只许改 aliases/description）；`anomaly_thresholds` 为有限正数且 `0 < significant_pct < critical_pct`；`validation_rules[].severity ∈ {error, warning}` |
| 3 引用层（best-effort） | 从 calculation 提取英文标识符 token，剔除 SQL 关键字/聚合函数白名单后必须 ∈ canonical 列名 → 否则 error（高置信引用错误）；中文 token 对照 metric 名集合，未命中仅 warning 放行（指标间引用如「销售额 / 订单数」）；不做完整 SQL parse，避免误杀阻断保存 |
| 4 影响层 | 序列化后 payload ≤ 64KB（存储层病态防护，error）；`context_pack_for_llm` 估算 token > 6K → **warning**（保存成功，提示「口径内容较大，分析可能因 token 预算提前降级」——64KB 硬限本身拦不住预算撑爆，警戒线才是预算保护，§4.3 联动）；**显示名表头 dry-run（v0.11 口径修正）**——用候选包对「内置包各列 `display_name` 作表头」的合成 schema 跑一次字段识别，`REQUIRED_FIELDS`（`net_sales_amount` / `order_date`）必须仍可识别 → 否则 error（防止把演示路径改砖）。不使用内置样例 CSV：其表头即 canonical 英文列名，canonical 名恒为自身别名，删中文别名也必然识别成功，无鉴别力 |

---

## 7. 报告质量 eval 契约（v0.9 重写）

eval 是报告质量的回归测试与发布门：`make eval` 通过率须为 100%。分两层，控制真实 LLM 调用成本：

| 层 | 位置 | 跑的时机 | 内容 |
|---|---|---|---|
| 确定性断言层 | `backend/tests/test_eval_assertions.py` | 随 `make check` 每次跑（零成本，高频回归网） | KPI 数值对 QA 基准、finding SQL 可重放、计数不变量、capture 口径生效断言、`previous_comparison` delta 数学、pack 校验规则 |
| LLM 层 | `backend/eval/` + `make eval` | 门控点必跑（建立基线、接入新用例与发布前收口，由开发计划指定），其余可选 | golden questions 全链路真实模型运行 + 硬断言/观察项 |

**断言实现纪律**：断言侧**禁止 import 产品计算函数**（reporting.py 等）——KPI 等数值必须用独立实现（pandas 复算）或读 QA 基准字面值比对，防止 f(x)==f(x) 自证循环。

**QA 基准契约（v2）**：`backend/.sample-data-qa.json` 由样例生成器同步产出，v2 起必须包含：4 个核心 KPI（销售额/订单数/客单价/退款率）的本期与上期窗口基准值 + 既有 6 项预埋异常指标。**QA 侧计算口径必须与产品报告口径一致**（订单数的 order_status 过滤范围等）——两侧分歧视为 bug，先裁决业务口径再对齐双方；订单数两侧均只计 completed / partial_refund 状态，退款率两侧的分母均为三种可识别状态合计（确定性 KPI 口径；口径包 `calculation` 只进模型上下文，见能力边界）。

**第二期 fixture 规格（供 rerun 用例与浏览器验收使用）**：
- 形态：**追加式**——period2 文件 = period1 全量行（同 SEED 确定性复现）+ 顺延新一周（独立子 rng），模拟「同一导出模板、导出范围顺延」的真实行为；重叠部分与第一期文件逐行一致，避免双「上期」口径在 fixture 内数值分叉
- 异常延续：SH001/徐汇在新一周相对上一周继续下滑（幅度区间生成器内固定）、童装退款率维持高位、抖音渠道特征延续——支撑「连续两期下滑」类历史叙事
- 同步产出 **period2 QA 基准文件**（以新一周为本期窗口的 KPI 双窗口值 + 异常指标），供 rerun 断言锚定
- 自检断言：period2 canonical 列集与 period1 一致；`max_date` 恰好后移一个周期；period1 部分行与第一期文件逐行一致

**目录结构**（`backend/pyproject.toml` 的 `testpaths=["tests"]` 使 `backend/eval/` 天然不进 `make check` / CI）：

```
backend/eval/
  __init__.py
  golden_questions.json       # 用例定义（JSON，不引新依赖）
  assertions.py               # 断言实现
  runner.py                   # uv run python -m eval.runner [--update-baseline] [--repeat N] [--only qN]
  fixtures/                   # 第二期追加式 period2 + 中文表头 zh（capture 用）fixture 及各自 QA 基准
  baseline/baseline.json      # 基线（提交入库）：每题断言结果 + 关键数值 + model + pack version + 日期
```

**golden question 格式**：

```
{ "id": "q1_weekly_review",
  "goal": "帮我生成周度销售经营回顾，重点看异常门店和商品",
  "data": "sample" | "fixtures/<file>",
  "flow": "run" | "rerun" | "capture", # rerun 先建任务再重跑；capture 先编辑口径再跑（带 pack_edit）
  "hard_assertions": [...],
  "observations": [...] }
```

**断言分级（v0.9 修订）**：
- **硬断言（gate，红即失败）**：
  - 报告 `status == completed`（LLM 瞬时失败有一次自动重试，见运行语义）
  - KPI 数值与 QA 基准 v2 字面值相符（KPI 为确定性产物，零容忍）
  - **finding SQL 分级断言**（阈值与语义 v0.12 未变，仅运行时解析按 §3.2 放宽）：evidence 带有效 data_ref 的 finding，其 SQL 必须对物化样例表可重放执行；evidence 为空 SQL 的 finding（模型按工具契约给了 short note）占比 ≤ 1/3——工具契约本就允许 short note，逐条硬性要求可重放会对合法输出结构性误报；evidence 收紧（note 独立字段化 + 无依据降级标注）列为周期运行契约候选
  - **预埋异常命中 ≥ 2/3**：按实体关键词（SH001/徐汇、童装、抖音）对**全部 findings 文本**匹配，**不按 finding type 过滤**——type 由模型自由标注、产品确定性基准自身即把抖音条目标为 trend，type 过滤会把 2/3 的容错空间吃成零
  - 计数不变量（`loop_rounds ≤ 15`、`steps_recorded == len(analysis_steps)`、`token_used > 0`）
  - rerun 报告 `previous_comparison` 存在、`previous_report_id` 可解析（等于隔离库内 founding 报告 id 且可查到）、delta 数学正确（锚定 period2 QA 基准：`previous_value` = 期 2 QA `previous` 字面值、`current_value` = 期 2 QA `current` 字面值、`delta_value` 按 §3.3 公式独立复算）、`same_period == false`
  - **capture 用例（别名驱动，v0.9 修订；数据口径 v0.11 澄清）**：PUT 移除「渠道」列（channel）的全部中文别名（v0.13 澄清：channel 是核心字段，别名列表不可为空（§6.4 L1），实际做法是替换为不匹配任何显示名的别名，如「投放渠道」）→ **中文表头（各列 `display_name`）样例**的字段识别不再含 channel、新报告 `context_pack_version` 为 `-local.N` → finally reset 恢复出厂。断言必须用中文表头数据（LLM 层用 `fixtures/retail_sales_orders_zh.csv`，确定性层用 display_name 合成 schema）——英文 canonical 表头样例对别名删除不敏感（§6.4 别名权威）。断言对象是**字段识别与版本追溯两条确定性因果链**；`calculation` 修改只进入模型上下文影响叙事（见能力边界），不作 capture 断言对象
  - （v0.13）**capture 用例门禁清单**：`status_completed`、`kpi_values_match`（中文表头 fixture 与 period1 同数据，锚定 period1 QA 字面值）、`finding_sql_replay`（在编辑后快照下物化重放，与分析时同源，见 §6.4 单次运行同源）、`count_invariants`，加三条 capture 专属断言——`capture_field_unrecognized`：该报告**落库数据集**的字段识别不含被编辑字段，且 `REQUIRED_FIELDS` 仍被识别（防空洞通过）；`capture_version_traced`：报告 payload 与落库 Report 的 `context_pack_version` 均等于编辑保存返回的版本、形如 `-local.N`，且不同于编辑前版本；`capture_control`（内置红绿对照）：「编辑前快照」与「恢复默认后快照」两端都必须按出厂口径识别到被编辑字段与 `REQUIRED_FIELDS`（字段断言因此判红，且是出于正确原因）、`is_modified == false`（从出厂态开始、回到出厂态），恢复后版本不同于编辑版本与编辑前版本（revision 单调前进）——证明断言有鉴别力、reset 已还原。**预埋异常命中在 capture 用例中降为观察项**（v0.13）：删除渠道别名后「抖音」实体在结构上不可达，2/3 阈值的容错空间被吃成零（与上文否决 type 过滤的理由同构）；阈值不变，其余用例照常 gate
- **观察项（记录进结果与基线，不 gate）**：预埋异常 3/3 全中率；finding 数与 type 分布；token / 时长漂移；pack 注入体积与 token_used 联动；分析正文/finding 中的上期引用信号（关键词或上期数值）——「报告有记忆」的模型侧证据；capture 编辑后模型叙事中的口径变化信号

**能力边界（诚实声明）**：当前 eval 捕获的是**口径（别名/阈值）修改的确定性影响**与**关键产出的粗粒度退化**（异常识别、SQL 可重放、KPI 正确）；prompt 级叙事质量退化只有观察项级的记录比对能力，不在 gate 范围。**「KPI 计算引擎读取 pack calculation」当前不实现**（calculation 只进模型上下文，确定性 KPI 按内置口径计算，编辑器 UI 明示）——如需实现列为周期运行阶段的候选决策，涉及执行用户可编辑 SQL 片段，须过 §4 安全评审。

**运行语义（v0.9 新增）**：
- 单题 LLM 调用瞬时失败（网络/限流类）自动重试 1 次；重试后仍失败才判红——区分瞬时故障与真实退化
- `--repeat N`：N > 1 时硬断言须全部运行全绿，观察项记录均值与极差；`make eval` 默认 N=1；`--update-baseline` 在 N=1 下执行，基线记录该次运行
- **DB 与上传隔离**：runner 强制使用独立临时应用库与上传目录（进程内覆写 `APP_DB_URL` 指向临时文件，运行后清理）；`make eval` 运行前后 `data/app.db` 必须无变化——rerun/capture 用例产生的任务、报告、pack revision 全部落在临时库，不污染开发/验收数据
- runner 检测未配置 LLM 时以可读文案 exit 2，**不静默跳过**；`--only qN` 单题运行可用（控制调试成本）
- **rerun 用例运行语义（v0.10）**：golden question 增可选 `founding` 字段（默认 `{"data": "sample"}`）。founding（上期）报告走**确定性路径**（体验模式 `generate_traceable_report`，不消耗模型调用），经 `save_report_run` + `save_task` 落隔离库；再由任务链构建 history_context，重跑走真实 LLM（`execute_report_run(..., task_id, history_context)`）。选确定性 founding 的理由：对比数学锚点是 QA 字面值、上期摘要内容稳定、单题成本只含一次模型运行；模型侧「上期引用」只作观察项
- **capture 用例运行语义（v0.13）**：golden question 取 `flow: "capture"` 并带 `pack_edit`（当前支持 `column_aliases: {canonical 列名: [新别名列表]}`，即替换该列全部别名）。全程在隔离库内：记录编辑前快照（该数据的识别字段集、有效版本、`is_modified`）→ 用与 `PUT /context-pack` **相同的四层校验与保存函数**写入编辑（校验不过即 setup 失败，不静默）→ 经共享 runner `execute_report_run`（真实 LLM，传入编辑后快照，与 SQL 重放同源）生成并落库报告 → 断言 → `finally` 调用与 `POST /context-pack/reset` 相同的恢复函数 → 记录恢复后快照供 `capture_control`。数据为 `fixtures/retail_sales_orders_zh.csv`：样例生成器以 period1 同 SEED 数据改写为各列 `display_name` 表头产出，附 `.qa.json`（KPI 与 period1 QA 同值）；其中「商品 SKU 编号」「二级商品类目」两个显示名不在出厂别名内、出厂口径下即不识别——真实导出模板的常态，不影响 capture 断言对象 `channel`。观察项 `capture_narrative_signal` 记录编辑后叙事中是否仍出现渠道维度词与渠道取值（抖音 / 天猫 / 小程序 / 线下）。套件级 `context_pack` 身份在任何用例运行**之前**读取（出厂版本），不受 capture 用例 revision 递增影响。run / rerun / capture 三类用例各自只解析一次口径快照并传到任务快照、分析、落库与 SQL 重放（§6.4 单次运行同源）

**基线纪律（v0.9 细化）**：
- `Makefile` 提供 `eval`（运行）与 `eval-baseline`（显式更新基线）两个入口；`make eval` 不进 `make check`、不进 CI（真实 key + 真实成本）；确定性等价断言随 check 跑
- **合法基线变更的两种类型**：① 新增用例扩充基线（接入新 golden questions）——正常演进，`make eval-baseline` + 在变更说明（PR 描述、提交说明或发布记录）中写明原因即可；② 既有用例断言结果变化——只有两种处理：修代码回绿，或决策「新行为正确」后显式刷基线留痕。禁止「跑红了就刷新基线」
- **漂移判别**：eval 无代码变更而意外变红时，先 `--repeat 3` 复跑——仅部分次失败 → 判定模型波动/服务商漂移，记入观察项并评估断言稳健性；稳定失败 → 按真实退化处理。基线的 `model` 字段是判别依据之一
- 断言阈值（2/3、1/3、6K token 警戒等）是契约值，调整须先改本节
- **模型变更留痕（v0.10）**：`make eval-baseline` 时若 `model` 与既有基线不同，变更说明须同时列出旧基线、变更前、变更后三组观察项——观察项差异先按模型变更解释、再看代码变更；硬断言变红仍按漂移判别流程处理

## 8. 变更管理

- 任何模块输入/输出契约变更必须**先**改本文件，**再**改实现
- 新增工具必须在本文件 Section 3.2 登记契约
- 执行控制层硬约束（第 4 节）调整必须经维护者确认
- Context Pack Schema 变更必须同步更新 Section 6（存储/版本/校验变更同步 §6.4）
- eval 断言阈值与基线纪律变更必须同步更新 Section 7
- 文件版本号：v0.2（架构形态决策后）→ v0.x（开发期迭代）→ v1.0（首个正式版本发布时同步）

### 待定契约项

以下事项已在正文登记、尚未定稿，汇总于此便于查找。「周期运行契约」指定时调度、数据源周期接入与推送上线前的契约评审；「周期运行阶段」指该能力的整个开发周期。

| 级别 | 事项 | 位置 |
|---|---|---|
| 周期运行契约必解项 | 业务时区配置，以及 Web / PDF 时区标注、模型 SQL 中的 `'now'` / `'localtime'`、模型叙事日期三项待决 | §2.4 第 7 条 |
| 周期运行契约必解项 | 同一任务的周期身份判别（time_range 对齐、同期重跑去重）；调度实现不得直接继承「链序 = 期序」假设 | §3.3 |
| 周期运行契约必解项 | 结论一致性：`query_data` 只把前 5 行预览交给模型，工具结果须显式标注截断，prompt 约束模型不对未见行做「唯一 / 最大 / 不在前 N」类全称判断；以 eval 前后对照与真实数据复验，在周期推送上线前完成 | §3.2 |
| 周期运行契约候选 | evidence 附注独立字段化（`evidence.note`）与无依据结论降级标注 | §3.2、§7 |
| 周期运行阶段候选 | 文件数据源周期接入时的结构容差（首选：按任务既有字段集投影重跑） | §5.2 |
| 周期运行阶段候选 | 报告 `warnings[]`（如 `ORDER_STATUS_UNRECOGNIZED`）在历史报告页、PDF 与推送中展示；当前只在生成时的分析对话中显示 | §3.3 |
| 周期运行阶段候选 | 「恢复默认」的版本基线：reset 保留原 `base_version`，恢复到新出厂内容后版本串仍是旧前缀（如 `1.0.0-local.3`）；需定义 reset 是否改基线，并让界面显示当前出厂版本 | §6.4 |
| 周期运行阶段候选 | KPI 计算引擎读取口径包 `calculation`（涉及执行用户可编辑 SQL 片段，须过 §4 安全评审） | §7 |
| 周期运行阶段候选 | `iterations_used` 别名移除（该阶段收口时评估）；反馈 voter 暴露（推送给多位读者时复核） | §3.3、§5.1 |
| 后续扩展 | 多包集合资源 `/context-packs/{id}`、schema_fingerprint v2（多表）、口径结构扩展（行业包） | §2.3、§5.2、§6.4 |

### 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-05-07 | 初稿：8 模块单趟流水线 |
| v0.2 | 2026-05-17 | 重写：workflow 外壳 + 有界 agentic 分析内核 + Context Pack Schema |
| v0.3 | 2026-05-24 | 补充 CSV / XLSX 上传、sheet 选择、错误码和 `.env` 行为 |
| v0.4 | 2026-05-31 | 补充单模型配置（§2.2 / §4.1）、持久层与报告历史（§2.2 / §5.1）、API 分层 |
| v0.5 | 2026-05-31 | 校准当前实现与规划能力的边界：API 分层待实现、Context Pack JSON 来源、12 步分析上限、历史持久化与通知投递拆分 |
| v0.6 | 2026-05-31 | （补记）API 分层完成回写：标记为已实现（§2.2） |
| v0.7 | 2026-05-31 | （补记）单模型配置完成回写：配置存储与 `enabled` 语义、api_key 脱敏约束（§2.2 / §4.1）；此前头部已标 v0.7 但本表漏记 v0.6 / v0.7 两行，v0.8 补齐 |
| v0.8 | 2026-06-11 | 任务复用与业务口径契约：API Schema 与错误码（§2.3）、双计数与 `previous_comparison`、history_context 运行时构建（§3.3）、Context Pack 编辑安全约束（§4.1）、三新表 + `task_id` + 无 Alembic 演进策略（§5.1）、schema_fingerprint（§5.2）、Context Pack 存储/版本/校验（§6.4）、eval 契约（§7，原变更管理顺延 §8） |
| v0.9 | 2026-07-19 | 契约补丁：§7 eval 契约重写（QA 基准 v2 / fixture 追加式规格 / SQL 分级断言 / 命中匹配去 type / capture 改别名驱动 / 运行语义与 DB 隔离 / 基线变更类型与漂移判别 / 能力边界声明）；§5.2 指纹时点钉死（founding report 口径）+ 展示名后端映射 + 容差候选登记；§3.3 previous_comparison 增 previous_status / same_period / delta_unit + 双「上期」口径裁决 + 「链序=期序」假设声明；§5.1 应用库 SQLite-only 声明 + ReportFeedback (report_id, voter) 复合唯一；§2.3 任务改名 PATCH + 保存同指纹 warning + SCHEMA_MISMATCH 显示名 + 报告详情 task 归属字段（§2.2）；§6.1 columns.display_name；§4.1/§6.4 64KB 定位修正 + prompt 体积警戒 |
| v0.10 | 2026-09-15 | 实现回写：§3.3 history_context 结构补 `previous_status`（含 `ran_at` 并列的选择规则）、`previous_comparison.baseline[]` 补服务端计算的 `severity`（阈值来源与公式、pp 恒 null）；§7 rerun 用例运行语义（确定性 founding + 真实 LLM 重跑、`founding` 字段）、`previous_report_id` 可解析与 delta 复算口径、模型变更留痕 |
| v0.11 | 2026-09-15 | 契约补丁：§2.3 context-pack 请求/响应细节（PUT body 两种形式、`is_modified` 判定、`errors`/`warnings` 元素结构、GET 缺记录先种子）；§6.4 别名权威（活动包 aliases 为字段识别唯一来源，`CANONICAL_ALIASES` 降级兜底）+ L4 dry-run 改用 display_name 表头合成 schema；§7 capture 用例数据口径澄清（中文表头 fixture / 合成 schema） |
| v0.12 | 2026-09-15 | §3.2 `record_finding` 增 evidence 引用解析规则（装饰串提取首个 `query-N`、`evidence_ref` 归一化为 canonical 引用、均未命中仍走 short note），修复装饰写法下结论丢失 SQL 追溯与自动配图；§7 声明 `finding_sql_replay` 阈值与语义不变 |
| v0.13 | 2026-09-19 | 契约补丁：§6.4 单次运行口径同源（活动包快照传入数据物化，rerun 指纹比对与物化共享快照）+ 结构层必需别名逐字段业务化报告；§2.3 重跑前端预检语义（点击时按当前口径刷新识别，服务端比对为唯一权威，不新增接口）、context-pack `updated_at` 带时区、错误文案业务化与下标 path；§7 capture 用例门禁清单（三条专属断言 + 内置红绿对照，异常命中在该用例降为观察项）与运行语义（`flow: "capture"` / `pack_edit` / 中文表头 fixture / finally 恢复 / 套件身份前置读取） |
| v0.14 | 2026-09-19 | 契约补丁：§2.3 报告反馈请求 / 响应细节（POST 创建与改票同形恒 200、每次提交刷新 `updated_at`、POST 整条覆盖、comment 去首尾空白后按 Unicode 码点计 ≤500、body 非对象 / verdict 非法 / comment 非字符串、含孤立代理项或超长一律 400 `FEEDBACK_INVALID` 不落库、未知字段含 voter 忽略、先校验后查报告且 404 复用 `REPORT_NOT_FOUND`、`updated_at` 带时区 UTC、列表 `{items, total, limit, offset, aggregate}` 全量聚合不随分页）；§5.1 `report_feedbacks` 唯一约束名、单语句原子 upsert、旧库由 create_all 补建 |
| v0.15 | 2026-09-20 | 入参边界加固：§2 新增**请求体边界校验**——所有 `/api/v1/*` JSON 请求体进入业务处理前统一扫描，含无法 UTF-8 编码的字符串即 400 `REQUEST_BODY_INVALID`，字典键与任意深度嵌套同查、multipart 跳过、非法 JSON 仍走 422（`POST /reports/run` 的 `task` 是开放式字典合并，字段无法穷举，逐字段校验不成立）；§2 列表分页 `limit`/`offset` 统一夹逼后回显，`offset` 上界钉在 `2^63-1`（越界入参不再在 SQLite 驱动层抛 `OverflowError`）；§2.3 新增 `REQUEST_BODY_INVALID` 错误码，`TASK_TITLE_INVALID` 覆盖 POST 创建路径，`FEEDBACK_INVALID` 的孤立代理项分支上移到边界（v0.14 实质约定不变） |
| v0.16 | 2026-09-22 | 时间戳契约：§2.4 新增——生成一律 UTC 且与进程时区无关；库列 `UTCDateTime`（DDL 不变）；对外时刻统一带 `+00:00`，含历史报告 payload 内的 `metadata.ran_at` / `evidence.ran_at` / `previous_ran_at`；前端按查看者本地时区展示；存量报告的时刻是生成进程本地时间（`reports.ran_at` 列同样如此，不是 UTC），按 `ran_at − created_at` 取整推断偏移、在读取时换算、不迁移数据；报告先后按换算后的运行时刻，历史列表 SQL 分页改按 `created_at`；业务时区登记为周期运行契约必解项。§2 REST 约定、§2.2 列表排序、§2.3 context-pack 时间说明与任务报告链排序、§3.3 `previous_ran_at` 与上期选择、§5.1 时刻列类型与 `last_run_at` 派生相应改写。对抗评审后补充：`UTCDateTime` 拒收无时区值、带其他偏移的 payload 值统一为 `+00:00`、列与 payload 各自推断偏移、前端对无偏移串原样显示、周期运行契约三项待决（时区标注 / SQL `localtime` / 叙事日期） |
| v0.17 | 2026-09-22 | §3.3 登记体验模式固定报告的 warning 码 `FALLBACK_REPORT`（此前实现发出 `P0_THIN_LOOP`，未入契约）；§8 新增「待定契约项」索引。全文改为公开契约措辞：去掉内部阶段标注、人名与内部文档引用，阶段限定改写为「当前」，后续阶段改写为「规划中」或「周期运行契约 / 阶段」，执行控制调整门槛写明「实现侧不得自行放宽、经维护者人工评审确认」。事实修正：§2.2 路由清单补 `datasets` / `context_pack` / `feedback`；§7 QA 基准的订单数口径由修复计划改写为已对齐的现状；§1 总览图注明规划能力。版本历史改为升序 |
| v0.18 | 2026-09-23 | §6.4 新增订单状态取值归一化（常见中英文写法映射到 `completed` / `partial_refund` / `refunded`，无法识别的保留原值）与「未编辑的活动包跟随出厂」规则（`revision == 0` 时启动期同步出厂内容与版本；出厂内容变化必须提升 `meta.version`）；出厂版本提升到 `1.0.2`，订单数与退款率的 `calculation` 与 KPI 口径对齐；§3.3 登记 `ORDER_STATUS_UNRECOGNIZED`，无法识别的行不参与任何核心指标（退款率分母改为三种可识别状态合计）；§7 QA 基准口径同步；§8 待定契约项加入结论一致性（预览截断标注与全称判断约束）、报告 warnings 的展示范围与「恢复默认」的版本基线；§3.2、§5.1 相应注记 |
