import type {
  DatasetPayload,
  DataSourceRef,
  FieldProfile,
  HistoryDatasetDetail,
  HistoryReportDetail,
  ReportPayload,
  StructuredTask,
} from '../api/client'

const DEFAULT_LIMITS = { max_iterations: 12, max_tokens: 50000, max_duration_seconds: 300 }
const EMPTY_PROFILE: FieldProfile = {
  is_valid: false,
  missing_key_fields: [],
  warnings: [],
  mappings: {},
}

export function datasetDetailToPayload(detail: HistoryDatasetDetail): DatasetPayload {
  const ref = sanitizeDataSourceRef(detail.data_source_ref, detail.id, detail.file_name)
  return {
    data_source_ref: ref,
    row_count: detail.row_count,
    column_count: detail.column_count,
    schema_summary: detail.schema_summary ?? { columns: [] },
    preview: {
      head: detail.preview?.head ?? [],
      tail: detail.preview?.tail ?? [],
    },
    workbook_sheets: [],
    selected_sheet: ref.selected_sheet ?? null,
    field_profile: detail.field_profile ?? EMPTY_PROFILE,
  }
}

export function reportDetailToView(
  detail: HistoryReportDetail,
  datasetDetail?: HistoryDatasetDetail,
): {
  dataset: DatasetPayload
  task: StructuredTask
  report: ReportPayload
  userGoal: string
} {
  const dataset = datasetDetail ? datasetDetailToPayload(datasetDetail) : summaryDataset(detail)
  const task = normalizeTask(detail, dataset.data_source_ref)
  const report = normalizeReport(detail.report, dataset)
  return {
    dataset,
    task,
    report,
    userGoal: task.analysis_goal || detail.report.analysis_goal || detail.summary,
  }
}

// 时刻展示（architecture.md §2.4）：后端一律给带偏移的 UTC ISO 串，这里按查看者浏览器的本地时区格式化。
// options.timeZone 仅供测试固定时区；页面调用不传，取浏览器时区。空值显示「—」。
// 无法解析或不带偏移的串原样返回：无偏移串的时区无从判断，换算只会静默出错。
type FormatOptions = { timeZone?: string }

const OFFSET_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i

export function formatHistoryDate(
  value: string | null | undefined,
  { timeZone }: FormatOptions = {},
): string {
  if (!value) return '—'
  const date = parseInstant(value)
  if (!date) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone,
  }).format(date)
}

// 报告署名、运行信息与证据运行时间：YYYY-MM-DD HH:mm:ss
export function formatDateTime(value: string | null | undefined, options: FormatOptions = {}): string {
  const parts = localParts(value, options)
  if (typeof parts === 'string') return parts
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}

// 结论脚注：HH:mm:ss
export function formatClock(value: string | null | undefined, options: FormatOptions = {}): string {
  const parts = localParts(value, options)
  if (typeof parts === 'string') return parts
  return `${parts.hour}:${parts.minute}:${parts.second}`
}

function parseInstant(value: string): Date | null {
  if (!OFFSET_SUFFIX.test(value.trim())) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function localParts(
  value: string | null | undefined,
  { timeZone }: FormatOptions,
): Record<Intl.DateTimeFormatPartTypes, string> | string {
  if (!value) return '—'
  const date = parseInstant(value)
  if (!date) return value
  // en-GB 默认 24 小时制，hourCycle 再显式钉一次；个别引擎午夜给出 "24" 时归零。
  const parts = new Intl.DateTimeFormat('en-GB', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
    timeZone,
  }).formatToParts(date)
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value])) as Record<
    Intl.DateTimeFormatPartTypes,
    string
  >
  if (byType.hour === '24') byType.hour = '00'
  return byType
}

export function statusLabel(status: string | null | undefined): string {
  if (status === 'partial') return '部分报告'
  if (status === 'ready') return '可分析'
  if (status === 'completed') return '已完成'
  return status || '未知'
}

export function historySummary(text: string | null | undefined, max = 58): string {
  const value = (text || '').replace(/\s+/g, ' ').trim()
  if (!value) return '暂无摘要'
  return value.length > max ? `${value.slice(0, max)}…` : value
}

function sanitizeDataSourceRef(
  ref: DataSourceRef | undefined,
  fallbackId: string,
  fileName: string,
): DataSourceRef {
  const source = ref ?? {
    id: fallbackId,
    type: 'csv',
    name: fileName,
    location: fileName,
  }
  return {
    ...source,
    id: source.id || fallbackId,
    name: source.name || fileName,
    location: fileName,
  }
}

function summaryDataset(detail: HistoryReportDetail): DatasetPayload {
  const ref = sanitizeDataSourceRef(undefined, detail.dataset_id, detail.dataset.file_name)
  return {
    data_source_ref: ref,
    row_count: detail.dataset.row_count,
    column_count: detail.dataset.column_count,
    schema_summary: { columns: [] },
    preview: { head: [], tail: [] },
    workbook_sheets: [],
    selected_sheet: null,
    field_profile: EMPTY_PROFILE,
  }
}

function normalizeTask(detail: HistoryReportDetail, ref: DataSourceRef): StructuredTask {
  const task = detail.task ?? ({} as Partial<StructuredTask>)
  return {
    task_title: task.task_title || detail.title || detail.report.title || '历史报告',
    data_source_ref: ref,
    context_pack_name:
      task.context_pack_name || detail.report.context_pack_name || 'Retail Operations',
    context_pack_version:
      task.context_pack_version || detail.report.context_pack_version || '1.0.0',
    analysis_goal: task.analysis_goal || detail.report.analysis_goal || detail.summary || '',
    metrics: Array.isArray(task.metrics) ? task.metrics : [],
    dimensions: Array.isArray(task.dimensions) ? task.dimensions : [],
    time_range: task.time_range || { mode: 'auto' },
    comparison: task.comparison || '环比',
    report_template: task.report_template || 'weekly_retail_review',
    execution_limits: { ...DEFAULT_LIMITS, ...(task.execution_limits ?? {}) },
  }
}

function normalizeReport(report: ReportPayload, dataset: DatasetPayload): ReportPayload {
  return {
    ...report,
    metadata: {
      ...report.metadata,
      data_source: {
        ...report.metadata.data_source,
        ...dataset.data_source_ref,
      },
      row_count: report.metadata.row_count ?? dataset.row_count,
    },
  }
}
