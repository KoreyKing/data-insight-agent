import { renderToStaticMarkup } from 'react-dom/server'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { DatasetPayload, ReportPayload, StructuredTask } from '../api/client'
import { INITIAL, type AppState } from '../lib/state'
import ArtifactPane from './ArtifactPane'

// 报告页真实渲染位置的回归网（architecture.md §2.4 第 4 条）：署名、运行信息、证据运行时间、
// 结论脚注、全部 SQL 页与上期对比段落都必须经本地时区格式化，不得透出原始 ISO 串。
// 进程时区固定为 Asia/Shanghai：在 UTC 机器上本地时间与 UTC 相同，无法区分「换算了」与「截了原始串」。
const RAN = '2026-09-21T11:46:52+00:00'
const EVIDENCE = '2026-09-21T11:46:30+00:00'
const PREVIOUS = '2026-09-15T09:52:33+00:00'
const RAW_INSTANT = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/

const ref = { id: 'd1', type: 'csv', name: 'sample.csv', location: 'sample.csv' }
const dataset = {
  data_source_ref: ref,
  row_count: 10,
  column_count: 2,
  schema_summary: { columns: [] },
  preview: { head: [], tail: [] },
  workbook_sheets: [],
  selected_sheet: null,
  field_profile: { is_valid: true, missing_key_fields: [], warnings: [], mappings: {} },
} as unknown as DatasetPayload
const task = {
  task_title: '周度经营复盘',
  data_source_ref: ref,
  context_pack_name: 'Retail Operations',
  context_pack_version: '1.0.0',
  analysis_goal: '周度复盘',
  metrics: [],
  dimensions: [],
  time_range: { mode: 'auto' },
  comparison: '环比',
  report_template: 'weekly_retail_review',
  execution_limits: { max_iterations: 12, max_tokens: 50000, max_duration_seconds: 300 },
} as StructuredTask
const report: ReportPayload = {
  status: 'completed',
  title: '周度经营复盘',
  summary: '摘要',
  kpis: [],
  warnings: [],
  findings: [
    {
      id: 'f1',
      type: 'trend',
      confidence: 'high',
      text: '结论一',
      evidence: { sql: 'SELECT 1', data_source: 'sales_orders', ran_at: EVIDENCE, iteration: 2 },
    },
    {
      id: 'f2',
      type: 'recommendation',
      confidence: 'medium',
      text: '建议',
      evidence: { sql: '', data_source: 'sales_orders', ran_at: EVIDENCE },
    },
  ],
  metadata: { data_source: ref, row_count: 10, ran_at: RAN, model: 'm', iterations_used: 2, token_used: 100 },
  previous_comparison: {
    previous_report_id: 'previous',
    previous_ran_at: PREVIOUS,
    previous_status: 'completed',
    previous_time_range: null,
    same_period: false,
    baseline: [],
    summary_note: '',
  },
} as unknown as ReportPayload

function render(tab: AppState['artifactTab']): string {
  const noop = () => {}
  const asyncNoop = async () => {}
  const state: AppState = {
    ...INITIAL,
    mode: 'current',
    step: 'report',
    dataset,
    task,
    report,
    currentReportId: 'r1',
    artifactTab: tab,
  }
  return renderToStaticMarkup(
    <ArtifactPane
      state={state}
      dispatch={noop}
      onSelectSheet={noop}
      onPickSample={noop}
      onPickUpload={noop}
      onOpenHistory={noop}
      onOpenTask={noop}
      onSaveTask={asyncNoop}
      onRenameTask={asyncNoop}
      onPickTaskUpload={noop}
      onSelectTaskSheet={asyncNoop}
      onConfirmTaskRerun={asyncNoop}
      onStopTaskRerun={noop}
    />,
  )
}

describe('报告页时刻渲染', () => {
  beforeAll(() => {
    vi.stubEnv('TZ', 'Asia/Shanghai')
  })
  afterAll(() => {
    vi.unstubAllEnvs()
  })

  it('报告正文：署名、运行信息、脚注与上期对比都按本地时区显示', () => {
    const html = render('report')
    expect(html).not.toMatch(RAW_INSTANT)
    expect(html).not.toContain('+00:00')
    expect(html).toContain('生成于 <b>2026-09-21 19:46:52</b>')
    expect(html).toContain('2026-09-21 19:46:30')
    expect(html).toContain('19:46:30')
    expect(html).not.toContain('11:46:30')
    expect(html).toContain('09/15 17:52')
  })

  it('全部 SQL 页：证据运行时间按本地时区显示', () => {
    const html = render('trace')
    expect(html).not.toMatch(RAW_INSTANT)
    expect(html).not.toContain('+00:00')
    expect(html).toContain('2026-09-21 19:46:30')
    expect(html).not.toContain('11:46:30')
  })
})
