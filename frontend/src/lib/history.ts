import type {
  DatasetPayload,
  DataSourceRef,
  FieldProfile,
  HistoryDatasetDetail,
  HistoryReportDetail,
  ReportPayload,
  StructuredTask,
} from '../api/client'

const DEFAULT_LIMITS = { max_iterations: 8, max_tokens: 50000, max_duration_seconds: 300 }
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

export function formatHistoryDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
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
