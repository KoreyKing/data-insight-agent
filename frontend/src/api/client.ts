// API client — extracted from the original App.tsx inline wiring.
// Single source for backend API calls (report workflow, tasks, context pack, feedback, model config) and shared payload types.

export type DataSourceRef = {
  id: string
  type: 'csv' | 'xlsx' | 'mysql' | 'postgres'
  name: string
  location: string
  selected_sheet?: string | null
}

export type WorkbookSheet = {
  name: string
  visible: boolean
  empty: boolean
  selected: boolean
}

export type ColumnSummary = {
  name: string
  data_type: string
  nullable: boolean
  sample_values: unknown[]
  distinct_count: number
}

export type FieldMapping = {
  canonical_field: string
  confidence: string
  method: string
}

export type FieldProfile = {
  is_valid: boolean
  missing_key_fields: string[]
  warnings: string[]
  mappings: Record<string, FieldMapping>
}

export type DatasetPayload = {
  session_id?: string
  data_source_ref: DataSourceRef
  row_count: number
  column_count: number
  schema_summary: { columns: ColumnSummary[] }
  preview: { head: Record<string, unknown>[]; tail: Record<string, unknown>[] }
  workbook_sheets: WorkbookSheet[]
  selected_sheet?: string | null
  field_profile: FieldProfile
  context_pack_name?: string
  context_pack_version?: string
}

export type StructuredTask = {
  task_title: string
  data_source_ref: DataSourceRef
  context_pack_name: string
  context_pack_version: string
  analysis_goal: string
  metrics: string[]
  dimensions: string[]
  time_range: { mode: string }
  comparison: string
  report_template: string
  execution_limits: { max_iterations: number; max_tokens: number; max_duration_seconds: number }
}

export type ApiWarning = {
  code: string
  message: string
}

export type FindingEvidence = {
  sql: string
  data_source: string
  ran_at: string
  exec_ms?: number
  row_count?: number
  validated_by?: string
  iteration?: number
  evidence_ref?: string
}

export type Finding = {
  id: string
  type: string
  confidence: string
  text: string
  evidence: FindingEvidence
  chart?: { id: string; title: string; echarts_spec: Record<string, unknown> }
}

export type KPI = {
  name: string
  current: number
  previous: number
  delta: number
  delta_pct: number | null
  unit: string
  delta_unit: string
  spark?: number[]
}

export type AnalysisStep = {
  iteration: number
  tool: string
  status: string
  summary: string
  code?: string
  sql?: string
  row_count?: number
  data_ref?: string
  chart_id?: string
  finding_id?: string
}

export type TimeRange = {
  current_start?: string
  current_end?: string
  previous_start?: string
  previous_end?: string
}

export type ReportMetadata = {
  data_source: DataSourceRef
  row_count: number
  query_engine?: string
  ran_at: string
  model: string
  loop_rounds?: number | null
  steps_recorded?: number
  iterations_used: number
  token_used: number
  time_range?: TimeRange
}

export type ComparisonSeverity = 'normal' | 'significant' | 'critical'

export type PreviousComparisonEntry = {
  name: string
  unit: string
  previous_value: number | null
  current_value: number | null
  delta_value: number | null
  delta_unit: '%' | 'pp'
  severity: ComparisonSeverity | null
}

// 跨报告对比段落（architecture.md §3.3）：仅任务重跑且链上有上期报告时出现，数值由后端确定性计算。
export type PreviousComparison = {
  previous_report_id: string
  previous_ran_at: string | null
  previous_status: 'completed' | 'partial'
  previous_time_range: TimeRange | null
  same_period: boolean
  baseline: PreviousComparisonEntry[]
  summary_note: string
}

export type ReportPayload = {
  status?: string
  title: string
  analysis_goal?: string
  summary: string
  kpis: KPI[]
  findings: Finding[]
  warnings: ApiWarning[]
  analysis_steps?: AnalysisStep[]
  metadata: ReportMetadata
  context_pack_name?: string
  context_pack_version?: string
  previous_comparison?: PreviousComparison | null
}

export type PaginatedResponse<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type HistoryDatasetSummary = {
  id: string
  file_name: string
  row_count: number
  column_count: number
}

export type HistoryReportListItem = {
  id: string
  dataset_id: string
  title: string
  summary: string
  status: string
  ran_at: string | null
  created_at: string | null
  model: string
  loop_rounds: number | null
  iterations_used: number
  token_used: number
  finding_count: number
  anomaly_count: number
  dataset: HistoryDatasetSummary
}

export type HistoryReportDetail = HistoryReportListItem & {
  task_id: string | null
  task_title: string | null
  report: ReportPayload
  task: StructuredTask
  dataset: HistoryDatasetSummary
}

export type AnalysisTaskListItem = {
  id: string
  title: string
  analysis_goal: string
  created_at: string | null
  status: string
  context_pack_name: string
  context_pack_version: string
  report_count: number
  last_run_at: string | null
}

export type AnalysisTaskReport = {
  id: string
  status: string
  ran_at: string | null
  summary: string
  finding_count: number
  has_previous_comparison: boolean
}

export type AnalysisTaskDetail = AnalysisTaskListItem & {
  structured_task: StructuredTask
  schema_fingerprint: string
  schema_fingerprint_json: {
    version?: number
    canonical_fields?: string[]
    computed_with_pack?: { name?: string; version?: string }
  }
  canonical_fields: { name: string; display_name: string }[]
  source_dataset_id: string
  reports: AnalysisTaskReport[]
  warnings?: DuplicateTaskWarning[]
}

export type DuplicateTaskWarning = {
  task_id: string
  task_title: string
}

export type TaskListResponse = {
  tasks: AnalysisTaskListItem[]
  limit: number
  offset: number
}

export type DatasetReportRef = {
  id: string
  title: string
  summary: string
  status: string
  ran_at: string | null
  created_at: string | null
  model: string
  finding_count: number
  anomaly_count: number
}

export type HistoryDatasetListItem = {
  id: string
  file_name: string
  data_source_type: string
  row_count: number
  column_count: number
  created_at: string | null
  status: string
  report_count: number
  latest_report_at: string | null
}

export type HistoryDatasetDetail = HistoryDatasetListItem & {
  data_source_ref: DataSourceRef
  schema_summary: DatasetPayload['schema_summary']
  preview: DatasetPayload['preview']
  field_profile: FieldProfile
  reports: DatasetReportRef[]
}

export type ModelStatus = {
  status: 'configured' | 'not_configured' | 'disabled' | 'failed' | 'unknown'
  model?: string
  provider?: string
}

export type LlmConfig = {
  provider: string | null
  base_url: string | null
  model: string | null
  has_key: boolean
  source: 'ui' | 'env' | 'none'
  enabled: boolean
}

export type SaveLlmConfigPayload = {
  provider: string
  model: string
  enabled: boolean
  api_key?: string
  base_url?: string
}

export type TestLlmConnectionResponse = {
  ok: boolean
  error?: string
}

export type ApiError = {
  code: string
  message: string
  details?: Record<string, unknown>
}

// 业务口径（architecture.md §2.3 / §6.4）：编辑器只改指标口径 / 字段别名 / 异常阈值三块，
// 其余内容原样回传；服务端四层校验是唯一权威。
export type PackMetric = {
  name: string
  calculation: string
  unit: string
  aliases: string[]
  notes: string
  [key: string]: unknown
}

export type PackColumn = {
  name: string
  display_name: string
  description: string
  aliases: string[]
  [key: string]: unknown
}

export type ContextPackPayload = {
  meta: { name: string; version: string; [key: string]: unknown }
  metrics: PackMetric[]
  data_dictionary: {
    tables: { name: string; columns: PackColumn[]; [key: string]: unknown }[]
    [key: string]: unknown
  }
  report_preferences: {
    anomaly_thresholds: { significant_pct: number | null; critical_pct: number | null }
    [key: string]: unknown
  }
  [key: string]: unknown
}

export type ContextPackIssue = {
  layer: number
  path: string
  message: string
}

export type ContextPackState = {
  name: string
  version: string
  revision: number
  is_modified: boolean
  updated_at: string | null
  payload: ContextPackPayload
  warnings?: ContextPackIssue[]
}

// 报告反馈（architecture.md §2.3 v0.14）：一报告一票，重复提交即改票，只落本地库、无外发。
export type FeedbackVerdict = 'useful' | 'not_useful'

export type ReportFeedbackRecord = {
  report_id: string
  verdict: FeedbackVerdict
  comment: string
  updated_at: string
}

export const defaultGoal =
  '帮我生成周度经营复盘，重点看销售变化、异常门店、商品表现和可行动线索'

export const errorMessages: Record<string, string> = {
  CSV_PARSE_FAILED: '无法解析这份 CSV，请确认编码为 UTF-8、首行是表头且分隔符正确。',
  XLSX_PARSE_FAILED:
    '无法读取这份 Excel，请确认文件为普通 .xlsx；如包含公式，请用 Excel 打开并保存后重试。',
  XLSX_NO_VISIBLE_SHEET: '未找到可分析的非空可见工作表，请检查 sheet 是否为空或被隐藏。',
  XLSX_UNSUPPORTED_FEATURE:
    '当前版本只支持首行表头的普通二维表格，不解析复杂表头、合并单元格、透视表或图表。',
  UNSUPPORTED_FILE_TYPE: '当前仅支持 CSV 和 .xlsx 文件，请另存为 CSV 或 .xlsx 后上传。',
  UPLOAD_NOT_FOUND: '上传已过期，请重新选择文件。',
  TASK_NOT_FOUND: '没有找到这个任务。',
  TASK_TITLE_INVALID: '任务名不能为空，且不超过 255 字。',
  REPORT_ALREADY_LINKED: '这份报告已经属于一个分析任务。',
  SCHEMA_MISMATCH: '新文件的数据结构与这个任务不一致，无法对比重跑。',
  CONTEXT_PACK_VALIDATION_FAILED: '口径设置有问题，尚未保存。',
  CONTEXT_PACK_NOT_FOUND: '业务口径数据异常，已回退默认口径。',
  REQUEST_BODY_INVALID: '请求内容包含无法处理的字符，请检查输入后重试。',
  NETWORK_ERROR: '无法连接到分析服务，请确认后端服务已启动后重试。',
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, init)
  } catch (err) {
    // Propagate user-initiated aborts unchanged so callers can ignore them.
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    // fetch rejects on network failure / backend unreachable
    throw { code: 'NETWORK_ERROR', message: errorMessages.NETWORK_ERROR }
  }
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    // non-JSON response (e.g. proxy 502 HTML) — treat as unreachable backend
    throw { code: 'NETWORK_ERROR', message: errorMessages.NETWORK_ERROR }
  }
  if (!response.ok) {
    throw payload
  }
  return payload as T
}

export function asApiError(value: unknown): ApiError {
  if (value && typeof value === 'object' && 'code' in value && 'message' in value) {
    const error = value as ApiError
    return {
      code: error.code,
      message: errorMessages[error.code] ?? error.message,
      details:
        'details' in value && value.details && typeof value.details === 'object'
          ? (value.details as Record<string, unknown>)
          : undefined,
    }
  }
  return { code: 'UNKNOWN_ERROR', message: '处理过程中出现意外错误' }
}

export function loadSample(): Promise<DatasetPayload> {
  return requestJson<DatasetPayload>('/api/v1/sample-dataset')
}

export function uploadFile(file: File): Promise<DatasetPayload> {
  const formData = new FormData()
  formData.append('file', file)
  return requestJson<DatasetPayload>('/api/v1/uploads', { method: 'POST', body: formData })
}

export function selectSheet(sessionId: string, sheet: string): Promise<DatasetPayload> {
  return requestJson<DatasetPayload>(
    `/api/v1/uploads/${sessionId}?sheet=${encodeURIComponent(sheet)}`,
  )
}

// 按当前活动口径重新识别已上传文件（口径可能在上传后被编辑，§2.3 v0.13 重跑前端预检）。
export function refreshUpload(
  sessionId: string,
  sheet: string | null | undefined,
  signal?: AbortSignal,
): Promise<DatasetPayload> {
  const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : ''
  return requestJson<DatasetPayload>(`/api/v1/uploads/${encodeURIComponent(sessionId)}${query}`, {
    signal,
  })
}

export type DimensionOption = {
  name: string
  description?: string | null
}

export function parseTask(
  analysisGoal: string,
  dataSourceRef: DataSourceRef,
): Promise<{ task: StructuredTask; warnings: ApiWarning[]; dimension_options?: DimensionOption[] }> {
  return requestJson('/api/v1/tasks/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ analysis_goal: analysisGoal, data_source_ref: dataSourceRef }),
  })
}

export function runReport(
  analysisGoal: string,
  dataSourceRef: DataSourceRef,
  task: StructuredTask | null,
  signal?: AbortSignal,
): Promise<{ report_id: string; report: ReportPayload }> {
  return requestJson('/api/v1/reports/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ analysis_goal: analysisGoal, data_source_ref: dataSourceRef, task }),
    signal,
  })
}

export function fetchReports(
  limit = 20,
  offset = 0,
): Promise<PaginatedResponse<HistoryReportListItem>> {
  return requestJson(`/api/v1/reports?limit=${limit}&offset=${offset}`)
}

export function fetchReportDetail(reportId: string): Promise<HistoryReportDetail> {
  return requestJson(`/api/v1/reports/${encodeURIComponent(reportId)}`)
}

export function fetchReportFeedback(
  reportId: string,
): Promise<{ feedback: ReportFeedbackRecord | null }> {
  return requestJson(`/api/v1/reports/${encodeURIComponent(reportId)}/feedback`)
}

export function submitReportFeedback(
  reportId: string,
  verdict: FeedbackVerdict,
  comment: string,
): Promise<ReportFeedbackRecord> {
  return requestJson<ReportFeedbackRecord>(
    `/api/v1/reports/${encodeURIComponent(reportId)}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ verdict, comment }),
    },
  )
}

export function fetchDatasets(
  limit = 20,
  offset = 0,
): Promise<PaginatedResponse<HistoryDatasetListItem>> {
  return requestJson(`/api/v1/datasets?limit=${limit}&offset=${offset}`)
}

export function fetchDataset(datasetId: string): Promise<HistoryDatasetDetail> {
  return requestJson(`/api/v1/datasets/${encodeURIComponent(datasetId)}`)
}

export function saveTask(reportId: string, title: string): Promise<AnalysisTaskDetail> {
  return requestJson<AnalysisTaskDetail>('/api/v1/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ report_id: reportId, title }),
  })
}

export function fetchTasks(limit = 50, offset = 0): Promise<TaskListResponse> {
  return requestJson<TaskListResponse>(`/api/v1/tasks?limit=${limit}&offset=${offset}`)
}

export function fetchTaskDetail(taskId: string): Promise<AnalysisTaskDetail> {
  return requestJson<AnalysisTaskDetail>(`/api/v1/tasks/${encodeURIComponent(taskId)}`)
}

export function renameTask(taskId: string, title: string): Promise<AnalysisTaskDetail> {
  return requestJson<AnalysisTaskDetail>(`/api/v1/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
}

export function rerunTask(
  taskId: string,
  dataSourceRef: DataSourceRef,
  signal?: AbortSignal,
): Promise<{ report_id: string; report: ReportPayload }> {
  return requestJson(`/api/v1/tasks/${encodeURIComponent(taskId)}/rerun`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data_source_ref: dataSourceRef }),
    signal,
  })
}

export function getContextPack(): Promise<ContextPackState> {
  return requestJson<ContextPackState>('/api/v1/context-pack')
}

export function saveContextPack(payload: ContextPackPayload): Promise<ContextPackState> {
  return requestJson<ContextPackState>('/api/v1/context-pack', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload }),
  })
}

export function resetContextPack(): Promise<ContextPackState> {
  return requestJson<ContextPackState>('/api/v1/context-pack/reset', { method: 'POST' })
}

export function fetchModelStatus(): Promise<ModelStatus> {
  return requestJson<ModelStatus>('/api/v1/model-status')
}

export function getLlmConfig(): Promise<LlmConfig> {
  return requestJson<LlmConfig>('/api/v1/llm-config')
}

export function saveLlmConfig(payload: SaveLlmConfigPayload): Promise<ModelStatus> {
  return requestJson<ModelStatus>('/api/v1/llm-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function testLlmConnection(
  payload: SaveLlmConfigPayload,
): Promise<TestLlmConnectionResponse> {
  return requestJson<TestLlmConnectionResponse>('/api/v1/llm-config/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteLlmConfig(): Promise<ModelStatus> {
  return requestJson<ModelStatus>('/api/v1/llm-config', { method: 'DELETE' })
}
