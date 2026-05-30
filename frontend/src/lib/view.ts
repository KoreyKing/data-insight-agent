// Shared view-model helpers: formatting + field-role derivation + chart-spec table extraction.
import type { ColumnSummary, FieldProfile, KPI, ReportPayload } from '../api/client'

export type FieldRole = '时间' | '指标' | '维度' | '标记' | '标识'

// Map internal Context Pack names to user-facing business labels.
const CONTEXT_PACK_LABELS: Record<string, string> = {
  'Retail Operations': '零售经营分析',
}

export function friendlyContextPack(name: string | undefined | null): string {
  if (!name) return '通用分析场景'
  return CONTEXT_PACK_LABELS[name] ?? name
}

const METRIC_CANON_HINTS = [
  'net_sales',
  'sales',
  'amount',
  'revenue',
  'price',
  'discount',
  'refund_amount',
  'quantity',
  'qty',
  'gmv',
  'aov',
]

const ID_CANON_HINTS = ['order_id', 'customer_id', 'id']

// Derive a display role from data_type + canonical mapping.
// Rule: date→时间, boolean→标记, id→标识, metric canonical or numeric→指标, else→维度.
// A numeric column is treated as a metric even when its canonical name is not a known
// metric (e.g. unit_cost): numbers are measures unless they are identifiers.
export function deriveRole(column: ColumnSummary, profile: FieldProfile | undefined): FieldRole {
  const type = (column.data_type || '').toLowerCase()
  const isNumeric = type === 'number' || type === 'numeric' || type === 'float' || type === 'int'
  if (type === 'date' || type === 'datetime' || type === 'time') return '时间'
  if (type === 'boolean' || type === 'bool') return '标记'

  const canonical = (profile?.mappings?.[column.name]?.canonical_field || '').toLowerCase()
  if (canonical) {
    if (ID_CANON_HINTS.some((hint) => canonical === hint || canonical.endsWith('_id'))) return '标识'
    if (METRIC_CANON_HINTS.some((hint) => canonical.includes(hint))) return '指标'
  }
  if (isNumeric) return '指标'
  return '维度'
}

export function typeIcon(type: string): string {
  const t = (type || '').toLowerCase()
  if (t === 'number' || t === 'numeric' || t === 'float' || t === 'int') return '#'
  if (t === 'date' || t === 'datetime' || t === 'time') return '◷'
  if (t === 'boolean' || t === 'bool') return '⊙'
  if (t === 'string') return 'a'
  return 'A'
}

export function roleColor(role: FieldRole): { bg: string; fg: string; bd: string } {
  if (role === '时间') return { bg: 'var(--sky-50)', fg: 'var(--sky-500)', bd: 'var(--sky-100)' }
  if (role === '指标') return { bg: 'var(--amber-50)', fg: 'var(--amber-500)', bd: 'var(--amber-100)' }
  if (role === '维度') return { bg: 'var(--forest-50)', fg: 'var(--forest-700)', bd: 'var(--forest-100)' }
  if (role === '标记') return { bg: 'var(--rust-50)', fg: 'var(--rust-600)', bd: 'var(--rust-100)' }
  return { bg: 'var(--bg-canvas)', fg: 'var(--ink-3)', bd: 'var(--line-soft)' }
}

export function sampleText(values: unknown[]): string {
  if (!values || values.length === 0) return '—'
  return values
    .slice(0, 4)
    .map((v) => (v === null || v === undefined ? '∅' : String(v)))
    .join(', ')
}

export function formatKpiValue(kpi: KPI): string {
  if (kpi.unit === '元') return `¥${Math.round(kpi.current).toLocaleString('zh-CN')}`
  if (kpi.unit === '%') return `${kpi.current.toFixed(1)}%`
  return `${kpi.current.toLocaleString('zh-CN')} ${kpi.unit}`
}

export function kpiDeltaText(kpi: KPI): string {
  const up = (kpi.delta_pct ?? kpi.delta) > 0
  const sign = up ? '+' : ''
  if (kpi.delta_unit === 'pp') return `${sign}${kpi.delta.toFixed(1)} pp`
  if (kpi.delta_pct === null || kpi.delta_pct === undefined) return `${sign}${kpi.delta}`
  return `${sign}${kpi.delta_pct.toFixed(1)}%`
}

// "Lower is better" KPIs (refund/return rate). Everything else: higher is better.
export function kpiIsPositive(kpi: KPI): boolean {
  const up = (kpi.delta_pct ?? kpi.delta) > 0
  const lowerBetter = /退款|退货|refund|return/i.test(kpi.name)
  return lowerBetter ? !up : up
}

export function kpiIsUp(kpi: KPI): boolean {
  return (kpi.delta_pct ?? kpi.delta) > 0
}

// Extract a small table from an echarts spec so the evidence "数据" tab can show numbers
// without the backend shipping raw result rows. Returns header + rows, or null.
export function tableFromSpec(
  spec: Record<string, unknown> | undefined,
): { header: string[]; rows: string[][] } | null {
  if (!spec) return null
  const xAxis = spec.xAxis as { data?: unknown[] } | { data?: unknown[] }[] | undefined
  const axis = Array.isArray(xAxis) ? xAxis[0] : xAxis
  const categories = axis?.data as unknown[] | undefined
  const series = spec.series as { name?: string; data?: unknown[] }[] | undefined
  if (categories && series && series.length > 0) {
    const header = ['分类', ...series.map((s, i) => s.name || `series_${i + 1}`)]
    const rows = categories.map((cat, idx) => [
      String(cat),
      ...series.map((s) => formatCell(s.data?.[idx])),
    ])
    return { header, rows }
  }
  // pie-style: series[0].data = [{name, value}]
  const pieData = series?.[0]?.data as { name?: string; value?: number }[] | undefined
  if (pieData && pieData.length > 0 && typeof pieData[0] === 'object') {
    const header = ['分类', '值']
    const rows = pieData.map((d) => [String(d.name ?? ''), formatCell(d.value)])
    return { header, rows }
  }
  return null
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return value.toLocaleString('zh-CN')
  return String(value)
}

export function reportRunInfo(report: ReportPayload) {
  const meta = report.metadata
  return {
    dataSource: meta.data_source?.name ?? '—',
    ranAt: meta.ran_at ?? '—',
    model: meta.model ?? 'not_configured',
    iterations: `${meta.iterations_used ?? 0} / ${meta.iterations_used ? 8 : 8}`,
    rowCount: meta.row_count ?? 0,
    tokenUsed: meta.token_used ?? 0,
  }
}

// SQL syntax highlighting → HTML string (kw/fn/lit). Ported from design highlightSQL.
export function highlightSQL(sql: string): string {
  const kw =
    /\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AND|OR|NOT|AS|CASE|WHEN|THEN|ELSE|END|BETWEEN|IS|NULL|DISTINCT|LIMIT|ASC|DESC|IN|WITH)\b/g
  const fn = /\b(SUM|COUNT|AVG|MIN|MAX|NULLIF|STRFTIME|DATE|CAST)\b/g
  const lit = /'[^']*'|\b\d+(?:\.\d+)?\b/g
  const escapeMap: Record<string, string> = { '<': '&lt;', '>': '&gt;', '&': '&amp;' }
  return sql
    .replace(/[<>&]/g, (c) => escapeMap[c])
    .replace(kw, '<span class="kw">$1</span>')
    .replace(fn, '<span class="fn">$1</span>')
    .replace(lit, '<span class="lit">$&</span>')
}
