// 业务口径编辑器的纯函数：版本文案、未保存判断、校验路径 → 业务位置映射。
import type { ContextPackPayload, ContextPackState, PackColumn } from '../api/client'
import { formatHistoryDate } from './history'

export type PackSection = 'metrics' | 'fields' | 'thresholds'

export type IssueLocation = {
  section: PackSection | null
  label: string
  // 页面元素 id：点击错误时跳转并聚焦；null 表示无法定位到单个输入框。
  anchor: string | null
}

const METRIC_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  calculation: '口径表达式',
  aliases: '别名',
  unit: '单位',
  notes: '说明',
}

const COLUMN_FIELD_LABELS: Record<string, string> = {
  aliases: '别名',
  description: '说明',
  display_name: '显示名',
  name: '字段',
}

const THRESHOLD_LABELS: Record<string, string> = {
  significant_pct: '标黄阈值',
  critical_pct: '标红阈值',
}

export function clonePayload(payload: ContextPackPayload): ContextPackPayload {
  return JSON.parse(JSON.stringify(payload)) as ContextPackPayload
}

export function packColumns(payload: ContextPackPayload): PackColumn[] {
  return payload.data_dictionary.tables[0]?.columns ?? []
}

export function isDirty(draft: ContextPackPayload | null, saved: ContextPackState | null): boolean {
  if (!draft || !saved) return false
  return JSON.stringify(draft) !== JSON.stringify(saved.payload)
}

export function baseVersion(version: string): string {
  return version.split('-local.')[0]
}

// 出厂态「1.0.0（默认）」；编辑过「1.0.0-local.N · 修改于 …」；恢复默认后注明已恢复（版本号只增不退）。
export function versionLabel(state: ContextPackState): string {
  if (state.revision === 0) return `口径版本 ${state.version}（默认）`
  const when = state.updated_at ? ` · 修改于 ${formatHistoryDate(state.updated_at)}` : ''
  const restored = state.is_modified ? '' : '（已恢复默认）'
  return `口径版本 ${state.version}${restored}${when}`
}

export function nextVersion(state: ContextPackState): string {
  return `${baseVersion(state.version)}-local.${state.revision + 1}`
}

export function locateIssue(path: string, payload: ContextPackPayload | null): IssueLocation {
  const metric = /^metrics\[(\d+)\](?:\.(\w+))?/.exec(path)
  if (metric) {
    const index = Number(metric[1])
    const field = metric[2]
    const name = payload?.metrics[index]?.name ?? `第 ${index + 1} 个指标`
    const fieldLabel = field ? METRIC_FIELD_LABELS[field] : undefined
    return {
      section: 'metrics',
      label: ['指标口径', name, fieldLabel].filter(Boolean).join(' · '),
      anchor: field ? `pack-metric-${index}-${field}` : `pack-metric-${index}`,
    }
  }

  const column = /^data_dictionary\.tables\[0\]\.columns\[(\d+)\](?:\.(\w+))?/.exec(path)
  if (column) {
    const index = Number(column[1])
    const field = column[2]
    const columns = payload ? packColumns(payload) : []
    const name = columns[index]?.display_name ?? `第 ${index + 1} 个字段`
    const fieldLabel = field ? COLUMN_FIELD_LABELS[field] : undefined
    return {
      section: 'fields',
      label: ['字段别名', name, fieldLabel].filter(Boolean).join(' · '),
      anchor: field ? `pack-field-${index}-${field}` : `pack-field-${index}`,
    }
  }

  if (path.startsWith('report_preferences.anomaly_thresholds')) {
    const key = path.split('.')[2]
    const fieldLabel = key ? THRESHOLD_LABELS[key] : undefined
    return {
      section: 'thresholds',
      label: ['异常阈值', fieldLabel].filter(Boolean).join(' · '),
      anchor: key ? `pack-threshold-${key}` : 'pack-threshold-significant_pct',
    }
  }
  if (path.startsWith('data_dictionary')) return { section: 'fields', label: '字段别名', anchor: null }
  if (path.startsWith('metrics')) return { section: 'metrics', label: '指标口径', anchor: null }
  if (path.startsWith('meta')) return { section: null, label: '分析场景', anchor: null }
  if (path.startsWith('validation_rules')) return { section: null, label: '校验规则', anchor: null }
  // 整包级问题（体积等）没有具体位置：只展示消息本身。
  return { section: null, label: '', anchor: null }
}
