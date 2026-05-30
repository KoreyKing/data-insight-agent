# Data Insight Agent 架构契约

> 状态：v0.3（2026-05-24，补充 P0 CSV / Excel 上传契约）
> 前版：v0.1 基于单趟流水线，已被本版替代
> 用途：开发期所有跨层 / 跨模块改动前必须先读本文件
> 维护：任何契约变更必须更新本文件，CLAUDE.md「Vibe Coding 协作纪律」#3 依赖于此

---

## 1. 架构总览：Workflow 外壳 + 有界 Agentic 分析内核

```
┌──────────────────────────────────────────────────────────────┐
│  确定性 Workflow 外壳（代码持有编排权）                         │
│                                                              │
│  调度触发 ──► 加载上下文 ──► ┌─────────────────┐ ──► 报告组装 ──► 推送 │
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
  用户数据库/CSV        用户 AI API (BYOM)     用户 SMTP 邮箱
```

**核心设计原则**：

| 原则 | 含义 |
|------|------|
| 外壳确定性 | 调度、连接、报告组装、推送——代码写死顺序，可预测、可追溯 |
| 内核 agentic | 分析步骤中模型自主决定取数/下钻/停止——数据分析本质是探索性的 |
| 有界 | 迭代上限 + Token 预算 + 时间上限 + 降级策略——无人值守场景下不能放飞 |
| 工具集固定 | 5 个工具，不可扩展——有界任务空间不需要开放 skill 体系 |
| 执行控制层包裹 | 每一轮 SQL 都过安全校验，不是只验一次 |

**与 v0.1 的关键差异**：

v0.1 的 8 模块单趟流水线（TaskRunner 按序调用）被替代。分析步骤不是一条直线——"销售额掉了"需要逐层下钻找根因，下一步取决于上一步返回什么。这种数据依赖的分支需要 agentic 循环，所有数据分析竞品（Julius AI、Dot、ThoughtSpot）验证了这一点。

---

## 2. 业务产品层

承接对象：前端 React + Vite 应用。

**模块清单**：
- 数据源管理
- 分析任务配置（对话式 + 结构化确认）
- 报告预览
- 定时推送管理
- 历史报告
- 模型 / SMTP 设置
- **Context Pack 配置**（指标口径、维度、分析模板的增删改查）

**REST API 约定**：
- 路径前缀 `/api/v1/`
- 资源命名复数：`/datasources`、`/tasks`、`/reports`、`/settings`、`/context-pack`
- 列表分页：`?page=1&size=20`
- 错误响应统一：`{code: str, message: str, details?: object}`

### 2.1 P0 API Schema

P0 只启用文件上传、样例数据、任务确认和当次报告生成，不启用任务保存、历史报告、定时推送、数据库直连和 Context Pack 编辑。

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

P0 仅允许 `type="csv"` 和 `type="xlsx"`；`mysql/postgres` 保留给 P2。`.xls`、`.xlsm`、`.xlsb` 返回 `UNSUPPORTED_FILE_TYPE`。

**P0 endpoints**

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/api/v1/sample-dataset` | 加载内置零售样例数据预览 |
| `POST` | `/api/v1/uploads` | 上传 CSV / XLSX 并返回 schema、sheet 列表、预览与字段识别结果 |
| `GET` | `/api/v1/uploads/{session_id}?sheet={sheet_name}` | 读取上传 session 的指定 sheet 预览 |
| `POST` | `/api/v1/tasks/parse` | 将自然语言目标解析为 P0 结构化任务；未配置 LLM 时返回默认周度模板并附 warning |
| `POST` | `/api/v1/reports/run` | 基于当前数据源与结构化任务生成当次可追溯报告 |

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
- P0 不解析图表、透视表、宏、隐藏表、合并单元格语义和复杂表头。
- 上传文件统一落到 `./data/uploads/{session_id}/`，P0 保留 24 小时后由清理任务删除。

**P0 error codes**

| code | 触发情况 |
|---|---|
| `CSV_PARSE_FAILED` | CSV 无法解析 |
| `XLSX_PARSE_FAILED` | XLSX 无法读取或公式缓存值缺失 |
| `XLSX_NO_VISIBLE_SHEET` | workbook 无可用非空可见 sheet |
| `XLSX_UNSUPPORTED_FEATURE` | 检测到 P0 不支持的复杂 Excel 结构 |
| `UNSUPPORTED_FILE_TYPE` | 非 `.csv` / `.xlsx` 文件 |
| `CSV_KEY_FIELD_MISSING` | 净销售额或日期等关键字段缺失 |

**P0 任务解析 warnings**（`/api/v1/tasks/parse` 在 `warnings[]` 返回，HTTP 200，均降级为默认周度模板，不阻断后续流程）：

| code | 触发情况 |
|---|---|
| `LLM_NOT_CONFIGURED` | 未配置模型 API |
| `LLM_CALL_FAILED` | 模型调用失败（鉴权/网络/超时等），不重试 |
| `LLM_PARSE_FAILED` | 输出非合法 JSON，修复重试一次后仍失败 |
| `LLM_INTENT_MISMATCH` | 目标与当前 Context Pack（零售运营）不匹配 |

**人工确认门**（业务产品层负责 UI 落地）：
- P0：用户确认结构化任务后执行；SQL 由 Validator 自动拦截，报告中后置展示 SQL 依据
- P1/P2：任务状态机 `draft → confirmed → active → paused`
- P2：数据库直连、定时任务首次启用、邮件首次发送须人工确认

---

## 3. 任务执行层 — 三阶段执行模型

### 3.0 总览

```
TaskRunner
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
        执行 validation_rules ──► 图表定稿 ──► Report Composer ──► 推送
```

### 3.1 Phase A — Pre-analysis（确定性）

**Schema Profiler**
- 职责：扫描数据源结构，生成供 LLM 理解的 schema 摘要
- 输入：`DataSourceRef { type: csv|xlsx|mysql|postgres, location, selected_sheet?, credentials_ref? }`
- 输出：`SchemaSummary { tables: [{name, columns: [{name, type, nullable, sample_values, distinct_count}], row_count_estimate}] }`
- 副作用：只读访问数据源；不调用 LLM

**加载 Context Pack**
- 从 SQLite 读取当前部署的 Context Pack（schema 见 Section 6）
- 将 metrics/dimensions/templates 格式化为 LLM 可理解的系统上下文

**初始化分析会话**
- 构造系统 prompt = Schema 摘要 + Context Pack + 分析模板（如有匹配的 template）
- 设置 ExecutionPolicy（bounds、timeouts）
- 创建会话记录（用于可追溯性）

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
- P0 实现：返回给模型的 `rows` 限前 5 行预览，完整结果通过 `data_ref` 在后续工具间引用

**Tool 2: `profile_column`**
- 职责：获取字段的快速统计摘要
- 输入：`{ table: str, column: str }`
- 输出：`{ type, distinct_count, null_pct, min, max, top_values: [{value, count}] }`
- 约束：敏感字段拒绝 profile

**Tool 3: `create_chart`**
- 职责：从查询结果生成可视化
- 输入：`{ data_ref: str, chart_type: "line"|"bar"|"pie"|"table", title: str, x_axis?: str, y_axis?: str }`
- 输出：`{ chart_id: str, png_base64: str, echarts_spec: dict }`
- 说明：双轨输出——Matplotlib PNG（邮件嵌入用）+ ECharts spec（Web 预览用）

**Tool 4: `record_finding`**
- 职责：记录一条分析发现
- 输入：`{ type: "trend"|"anomaly"|"recommendation", text: str, evidence: str, confidence: "high"|"medium"|"low" }`
- 输出：`{ finding_id: str }`
- 说明：每条 finding 关联当前循环轮次的 SQL + 数据，构成可追溯链

**Tool 5: `finish`**
- 职责：结束分析循环
- 输入：`{ summary: str }`
- 输出：无（终止循环信号）
- 说明：模型主动判断"信息足够了"

#### 边界约束（硬性，CC 不得自行放宽）

| 约束 | 默认值 | 硬上限 | 说明 |
|------|--------|--------|------|
| 迭代轮次 | 8 | 15 | 每次工具调用算 1 轮 |
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

P0 Analysis Loop 在 `analysis_steps[].code`（step.status=`failed`）或 `warnings[].code` 中暴露以下控制层信号；前端折叠展示，不阻断报告生成：

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
- 从 Context Pack 读取 `validation_rules[]`
- 对 Analysis Loop 产出的 findings 和查询结果执行校验
- severity=error 的违规标红并在报告中警告
- 确定性执行，不由模型判断

**图表定稿**
- 收集循环中所有 `create_chart` 的产出
- 统一样式、排版
- 确保双轨输出完整（PNG + ECharts spec）

**Report Composer**
- 输入：`{ task_meta, context_pack.report_preferences, findings[], charts[], validated_sql_trail[] }`
- 输出：`Report { html, web_payload, metadata: {datasource, queries[], ran_at, model, iterations_used, token_used} }`
- 每条结论关联：SQL 原文、数据源、运行时间、循环轮次

**推送**
- 根据任务配置：Email（SMTP）/ Webhook
- HTML 邮件中图表以 base64 嵌入
- Web 预览以 JSON payload 存储

---

## 4. 执行控制层 — 硬约束（CC 不得自行放宽）

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

#### P0.4 SQL Validator 策略

P0.4 查询层使用临时 SQLite，仅暴露 canonical `sales_orders` 查询表。上传数据进入查询层前先按 Context Pack alias 和本地 fallback alias 映射为 canonical 字段，例如 `订单日期` → `order_date`、`销售额` → `net_sales_amount`。

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
| 迭代上限 | 默认 8 轮，硬上限 15 轮 | `ExecutionPolicy.loop.max_iterations` |
| Token 预算 | 默认 50K，硬上限 100K | `ExecutionPolicy.loop.max_tokens` |
| 时间上限 | 默认 5 min，硬上限 10 min | `ExecutionPolicy.loop.max_duration` |
| **每轮 SQL 校验** | 循环内每一轮 SQL 都过 Validator，不是只验一次 | SQL Validator |
| 降级策略 | 触顶 → 输出已有发现 + 标注未完成 | TaskRunner 硬编码 |

### 4.4 业务流程约束

| 控制点 | 策略 | 配置位置 |
|--------|------|---------|
| 定时任务首次启用 | 用户手动确认（不可 auto-on） | 任务状态机 `draft→confirmed→active` |
| 邮件首次发送 | 测试邮件 + 用户确认后才进入定时 | 任务状态机 |

**违反任意一条 = 阻断式 bug，不允许 CC 自行权衡放宽。如需调整，必须通过 Plan Mode 走人工评审。**

---

## 5. 数据流总览

```
[用户] ──配置任务──► [业务产品层] ──持久化──► SQLite
                          │
              调度器触发   ▼
                   ┌─── TaskRunner ───┐
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
                           │
               ┌───────────┴───────────┐
               ▼                       ▼
          HTML 邮件                Web 预览 JSON
               │                       │
              SMTP              React + ECharts
```

---

## 6. Context Pack Schema

Context Pack = 行业/场景的结构化业务知识包。P0 使用内置只读 JSON artifact；P1 起单租户一个 pack，写入 SQLite `context_pack` 表并允许 Web 界面编辑。每次分析时注入 agentic 循环的系统 prompt。V1 默认提供 `Retail Operations` 作为首个示例 pack，但 schema 本身保持行业无关，未来可承载多个 vertical pack。

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

  history_context: {                    # 系统自动维护
    last_run_summary: str               # 上次分析的关键结论
    baseline_values: {str: float}       # 基线指标值，如 {"GMV": 125000.0}
    ongoing_notes: [str]                # 持续关注事项
  }
}
```

### 6.2 设计要点

| 设计决策 | 理由 |
|---------|------|
| `metrics` + `dimensions` 是核心 | 对标 Dot DotML、ThoughtSpot 治理语义层——口径一致性是分析质量的基础 |
| `analysis_templates` 引导但不强制 | 注入 prompt 后模型可偏离（如数据指向预期外方向）——保留探索性 |
| `validation_rules` 确定性执行 | 不由模型判断，Post-analysis 阶段代码遍历执行——确保硬性校验不被跳过 |
| `history_context` 系统自动维护 | 每次分析完成后写入 last_run_summary + 更新 baseline——支持趋势跟踪和环比 |
| `is_sensitive` 联动执行控制层 | 标记为敏感的字段值不进 LLM，`query_data` 返回时自动 mask |
| `Retail Operations` 只是首个示例 pack | 用于 V1 演示与需求验证，不把零售固化到 schema 和底层接口 |
| V1 单 pack，JSON 存储 | 一个部署先跑通一个场景，多 pack 留给后续扩展（≥2 个垂直时再做加载机制） |

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
7. 历史上下文（来自 history_context）
8. 工具使用说明（5 个工具的调用方式）
9. 报告风格要求（来自 report_preferences）
```

---

## 7. 变更管理

- 任何模块输入/输出契约变更必须**先**改本文件，**再**改实现
- 新增工具必须在本文件 Section 3.2 登记契约
- 执行控制层硬约束（第 4 节）调整必须经 Korey 确认
- Context Pack Schema 变更必须同步更新 Section 6
- 文件版本号：v0.2（架构形态决策后）→ v0.x（V1 开发期迭代）→ v1.0（V1 发布同步）

### 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-05-07 | 初稿：8 模块单趟流水线 |
| v0.2 | 2026-05-17 | 重写：workflow 外壳 + 有界 agentic 分析内核 + Context Pack Schema |
| v0.3 | 2026-05-24 | 补充 P0 CSV / XLSX 上传、sheet 选择、错误码和 `.env` 行为 |
