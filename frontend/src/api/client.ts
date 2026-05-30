// API client — extracted from the original App.tsx inline wiring.
// Single source for the 5 P0 endpoints + model-status, plus shared payload types.

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
  iterations_used: number
  token_used: number
  time_range?: TimeRange
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
}

export type ModelStatus = {
  status: 'configured' | 'not_configured' | 'failed' | 'unknown'
  model?: string
  provider?: string
}

export type ApiError = {
  code: string
  message: string
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
  UPLOAD_NOT_FOUND: '未找到上传 session，请重新上传文件。',
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
): Promise<{ report: ReportPayload }> {
  return requestJson('/api/v1/reports/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ analysis_goal: analysisGoal, data_source_ref: dataSourceRef, task }),
    signal,
  })
}

export function fetchModelStatus(): Promise<ModelStatus> {
  return requestJson<ModelStatus>('/api/v1/model-status')
}
