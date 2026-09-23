import { useEffect, useState, type Dispatch } from 'react'
import type { Action, AppState } from '../lib/state'
import { taskView } from '../lib/state'
import type {
  DatasetPayload,
  Finding,
  HistoryDatasetDetail,
  KPI,
  PreviousComparison,
  ReportPayload,
  StructuredTask,
} from '../api/client'
import { formatClock, formatDateTime, formatHistoryDate, historySummary } from '../lib/history'
import {
  comparisonDeltaClass,
  deriveRole,
  formatComparisonDelta,
  formatComparisonValue,
  friendlyContextPack,
  highlightSQL,
  kpiDeltaText,
  kpiIsPositive,
  kpiIsUp,
  reportRunInfo,
  roleColor,
  sampleText,
  tableFromSpec,
  typeIcon,
} from '../lib/view'
import { Ico } from './icons'
import FindingChart from './charts/FindingChart'
import Sparkline from './charts/Sparkline'
import ReportFeedback from './ReportFeedback'
import SaveTaskDialog from './SaveTaskDialog'
import TaskPane from './TaskPane'

function ProfileStat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <div
        style={{
          fontSize: 10.5,
          color: 'var(--ink-3)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: 22,
          fontWeight: 500,
          color: 'var(--ink-1)',
          margin: '4px 0 2px',
          fontFeatureSettings: '"tnum"',
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>{sub}</div>
    </div>
  )
}

function DatasetProfile({
  state,
  onSelectSheet,
  datasetOverride,
  readonly,
  detail,
}: {
  state: AppState
  onSelectSheet: (sheet: string) => void
  datasetOverride?: DatasetPayload | null
  readonly?: boolean
  detail?: HistoryDatasetDetail | null
}) {
  const [showRaw, setShowRaw] = useState(false)
  const dataset = datasetOverride ?? state.dataset
  if (!dataset) return null

  const columns = dataset.schema_summary.columns
  const profile = dataset.field_profile
  const mappedCount = Object.values(profile.mappings || {}).filter(
    (m) => (m.confidence || '').toLowerCase() !== 'low',
  ).length
  const dateColumn = columns.find((c) => {
    const role = deriveRole(c, profile)
    return role === '时间'
  })
  const sheets = dataset.workbook_sheets || []
  const previewRows = [
    ...dataset.preview.head,
    ...dataset.preview.tail.filter(
      (tailRow) =>
        !dataset.preview.head.some((headRow) => JSON.stringify(headRow) === JSON.stringify(tailRow)),
    ),
  ]

  return (
    <div className="ds-wrap">
      <div className="ds-hero">
        <div>
          <div className="rep-tagrow">
            <span className="d" /> 数据集 · 字段映射
          </div>
          <h2>{dataset.data_source_ref.name}</h2>
          <div className="meta">
            <span>
              {dataset.data_source_ref.type.toUpperCase()} · <b>{dataset.row_count.toLocaleString('zh-CN')}</b> 行
            </span>
            <span>
              <b>{dataset.column_count}</b> 列
            </span>
            {dateColumn && (
              <span>
                时间列 <b className="mono">{dateColumn.name}</b>
              </span>
            )}
          </div>
        </div>
        <div className="ds-status">
          {profile.is_valid ? (
            <span>
              <Ico.Check size={11} />
              &nbsp; 字段可分析
            </span>
          ) : (
            <span style={{ color: 'var(--amber-500)' }}>
              <Ico.Warn size={11} />
              &nbsp; 部分字段待确认
            </span>
          )}
        </div>
      </div>

      {!readonly && sheets.length > 1 && (
        <div className="sheet-row">
          {sheets.map((s) => (
            <button
              key={s.name}
              className={`sheet-tab ${s.selected ? 'active' : ''}`}
              onClick={() => onSelectSheet(s.name)}
              disabled={s.empty || Boolean(state.busy)}
              title={s.empty ? '空工作表' : ''}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}

      <div
        className="ds-card"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 18, marginBottom: 16 }}
      >
        <ProfileStat
          label="行数"
          value={dataset.row_count.toLocaleString('zh-CN')}
          sub={`${dataset.column_count} 列`}
        />
        <ProfileStat
          label="可分析字段"
          value={`${mappedCount} / ${columns.length}`}
          sub="已套用分析场景"
        />
        <ProfileStat
          label="字段映射"
          value={profile.is_valid ? '通过' : '待确认'}
          sub={profile.missing_key_fields.length ? `缺 ${profile.missing_key_fields.length} 关键字段` : '关键字段齐备'}
        />
        <ProfileStat
          label="时间列"
          value={dateColumn ? dateColumn.name : '未检测'}
          sub={dateColumn ? '支持 日 / 周 / 月 聚合' : '部分分析受限'}
        />
      </div>

      <div className="ds-card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="ds-fields-hd">
          <div className="hstack" style={{ gap: 8 }}>
            <h4 style={{ margin: 0 }}>分析场景 · 字段映射</h4>
            <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>
              已套用<b style={{ color: 'var(--forest-700)' }}>「{friendlyContextPack(dataset.context_pack_name ?? 'Retail Operations')}」</b>口径
              {dataset.context_pack_version ? ` ${dataset.context_pack_version}` : ''} · {mappedCount}/
              {columns.length} 命中
            </span>
          </div>
          <div className="hstack" style={{ gap: 4 }}>
            <button className="btn subtle xs" onClick={() => setShowRaw(true)}>
              <Ico.Table size={11} /> 查看原始数据
            </button>
          </div>
        </div>

        <div className="ds-fields-head">
          <div />
          <div>字段</div>
          <div>角色</div>
          <div>取值预览</div>
          <div style={{ textAlign: 'right' }}>缺失</div>
          <div style={{ textAlign: 'right' }}>基数</div>
          <div />
        </div>

        <div className="ds-fields-body">
          {columns.map((col) => {
            const role = deriveRole(col, profile)
            const rc = roleColor(role)
            const mapping = profile.mappings?.[col.name]
            const canonical = mapping?.canonical_field || col.name
            const conf = (mapping?.confidence || '').toUpperCase()
            const confCls = conf === 'MEDIUM' || conf === 'MED' ? 'med' : conf === 'LOW' ? 'low' : ''
            return (
              <div className="ds-fields-row" key={col.name}>
                <div className="ds-type" data-t={col.data_type}>
                  {typeIcon(col.data_type)}
                </div>
                <div>
                  <div className="ds-fname">{col.name}</div>
                  <div className="ds-canon">→ {canonical}</div>
                </div>
                <div>
                  <span
                    className="ds-role"
                    style={{ background: rc.bg, color: rc.fg, borderColor: rc.bd }}
                  >
                    {role}
                  </span>
                </div>
                <div className="ds-sample">{sampleText(col.sample_values)}</div>
                <div className="ds-miss" style={{ textAlign: 'right', color: 'var(--ink-4)' }}>
                  {col.nullable ? '可空' : '—'}
                </div>
                <div className="ds-uniq" style={{ textAlign: 'right' }}>
                  {col.distinct_count ? col.distinct_count.toLocaleString('zh-CN') : '—'}
                </div>
                <div>{conf ? <span className={`conf ${confCls}`}>{conf}</span> : null}</div>
              </div>
            )
          })}
        </div>
      </div>

      {readonly && previewRows.length > 0 && (
        <div className="preview ds-inline-preview">
          <div className="preview-hd">
            <div className="hstack">
              <Ico.Table size={13} /> <b>数据预览</b>
              <span style={{ color: 'var(--ink-3)' }}>
                前 {Math.min(previewRows.length, 6)} 行 / 共 {dataset.row_count.toLocaleString('zh-CN')} 行
              </span>
            </div>
          </div>
          <div className="preview-body">
            <table className="t">
              <thead>
                <tr>
                  {columns.map((col) => (
                    <th key={col.name}>
                      {col.name}
                      <span className="type">{col.data_type}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewRows.slice(0, 6).map((row, i) => (
                  <tr key={i}>
                    {columns.map((col) => {
                      const t = col.data_type.toLowerCase()
                      const cls = t === 'number' ? 'num' : 'txt'
                      const value = row[col.name]
                      return (
                        <td key={col.name} className={cls}>
                          {value === null || value === undefined ? '' : String(value)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showRaw && (
        <div className="modal-backdrop" onClick={() => setShowRaw(false)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="preview-hd" style={{ borderBottom: '1px solid var(--line-soft)' }}>
              <div className="hstack">
                <Ico.Table size={13} /> <b>原始数据预览 · {dataset.data_source_ref.name}</b>
                <span style={{ color: 'var(--ink-3)' }}>
                  前 {previewRows.length} 行 / 共 {dataset.row_count.toLocaleString('zh-CN')} 行
                </span>
              </div>
              <button className="btn subtle xs" onClick={() => setShowRaw(false)}>
                <Ico.X size={10} /> 关闭
              </button>
            </div>
            <div className="preview-body modal-body">
              <table className="t">
                <thead>
                  <tr>
                    {columns.map((col) => (
                      <th key={col.name}>
                        {col.name}
                        <span className="type">{col.data_type}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, i) => (
                    <tr key={i}>
                      {columns.map((col) => {
                        const t = col.data_type.toLowerCase()
                        const cls = t === 'number' ? 'num' : 'txt'
                        const value = row[col.name]
                        return (
                          <td key={col.name} className={cls}>
                            {value === null || value === undefined ? '' : String(value)}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {detail && detail.reports.length > 0 && (
        <div className="ds-card ds-report-refs">
          <div className="ds-fields-hd">
            <div className="hstack" style={{ gap: 8 }}>
              <h4 style={{ margin: 0 }}>关联报告</h4>
              <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>
                {detail.reports.length} 份历史报告引用
              </span>
            </div>
          </div>
          <div className="ds-ref-list">
            {detail.reports.slice(0, 6).map((report) => (
              <div className="ds-ref-row" key={report.id}>
                <div>
                  <div className="ds-ref-title">{report.title}</div>
                  <div className="ds-ref-summary">{historySummary(report.summary, 72)}</div>
                </div>
                <div className="ds-ref-meta">
                  <span>{formatHistoryDate(report.ran_at)}</span>
                  <span>{report.finding_count} 洞察</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function GenerationView({ state }: { state: AppState }) {
  const slow = Number(state.elapsed) >= 30
  return (
    <div className="gen-state">
      <div className="rep-tagrow">
        <span className="d" /> 正在分析
      </div>
      <h2>{state.task?.task_title ?? '生成报告'}</h2>
      <div className="sub">正在自动取数、下钻异常并生成图表，每一步都会记录 SQL 依据。</div>

      {state.progress.map((p, i) => (
        <div key={i} className={`gen-step ${p.state}`}>
          <span className="ico">
            {p.state === 'done' ? (
              <Ico.Check size={12} />
            ) : p.state === 'active' ? (
              <Ico.Loop size={12} />
            ) : (
              <span className="mono" style={{ fontSize: 10 }}>
                {i + 1}
              </span>
            )}
          </span>
          <div>
            <div className="ttl">{p.label}</div>
            {p.detail && <div className="det">{p.detail}</div>}
          </div>
          <div className="t">{p.state === 'pending' ? '' : '…'}</div>
        </div>
      ))}

      {state.genWaiting && (
        <div className="gen-step active" style={{ marginTop: 2 }}>
          <span className="ico">
            <Ico.Loop size={12} />
          </span>
          <div>
            <div className="ttl">仍在分析中，正在等待模型返回结果…</div>
            {slow && <div className="det">复杂分析可能需要 1–2 分钟，请稍候。</div>}
          </div>
          <div className="t">…</div>
        </div>
      )}

      <div
        style={{
          marginTop: 18,
          padding: '12px 14px',
          background: 'var(--bg-panel)',
          border: '1px solid var(--line-soft)',
          borderRadius: 'var(--r-md)',
          fontSize: 12,
          color: 'var(--ink-3)',
        }}
      >
        <span>
          <Ico.Clock size={12} /> 已用{' '}
          <b className="mono" style={{ color: 'var(--ink-1)' }}>
            {state.elapsed || '0.0'}s
          </b>
        </span>
      </div>
    </div>
  )
}

function InsightEvidence({ finding }: { finding: Finding }) {
  const [tab, setTab] = useState<'sql' | 'data' | 'meta'>('sql')
  const ev = finding.evidence
  const dataTable = tableFromSpec(finding.chart?.echarts_spec)
  return (
    <div className="evi-drawer">
      <div className="evi-tabs">
        <button className={`evi-tab ${tab === 'sql' ? 'active' : ''}`} onClick={() => setTab('sql')}>
          <Ico.Code size={11} /> SQL
        </button>
        {dataTable && (
          <button className={`evi-tab ${tab === 'data' ? 'active' : ''}`} onClick={() => setTab('data')}>
            <Ico.Table size={11} /> 数据 ({dataTable.rows.length} 行)
          </button>
        )}
        <button className={`evi-tab ${tab === 'meta' ? 'active' : ''}`} onClick={() => setTab('meta')}>
          <Ico.Doc size={11} /> 元信息
        </button>
      </div>
      <div className="evi-pane">
        {tab === 'sql' && (
          <>
            <div className="evi-meta-grid">
              <div>
                <div className="k">数据源</div>
                <div className="v">{ev.data_source}</div>
              </div>
              <div>
                <div className="k">运行时间</div>
                <div className="v">{formatDateTime(ev.ran_at)}</div>
              </div>
              {typeof ev.iteration === 'number' && (
                <div>
                  <div className="k">分析步骤</div>
                  <div className="v">#{ev.iteration}</div>
                </div>
              )}
            </div>
            {ev.sql ? (
              <pre className="sql-block" dangerouslySetInnerHTML={{ __html: highlightSQL(ev.sql) }} />
            ) : (
              <div className="evi-note">
                本结论来自 <span className="mono">{ev.evidence_ref || 'manual-observation'}</span>，无对应 SQL。
              </div>
            )}
          </>
        )}
        {tab === 'data' && dataTable && (
          <div className="evi-table">
            <table className="t">
              <thead>
                <tr>
                  {dataTable.header.map((c, i) => (
                    <th key={i}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dataTable.rows.map((r, i) => (
                  <tr key={i}>
                    {r.map((c, j) => (
                      <td key={j} className={j === 0 ? 'txt' : 'num'}>
                        {c}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === 'meta' && (
          <div style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.7 }}>
            <div className="evi-meta-grid" style={{ gridTemplateColumns: 'repeat(2, 1fr)' }}>
              <div>
                <div className="k">数据源</div>
                <div className="v">{ev.data_source}</div>
              </div>
              {typeof ev.row_count === 'number' && (
                <div>
                  <div className="k">数据行数</div>
                  <div className="v">{ev.row_count.toLocaleString('zh-CN')}</div>
                </div>
              )}
              <div>
                <div className="k">运行时间</div>
                <div className="v">{formatDateTime(ev.ran_at)}</div>
              </div>
              {typeof ev.exec_ms === 'number' && (
                <div>
                  <div className="k">执行耗时</div>
                  <div className="v">{ev.exec_ms} ms</div>
                </div>
              )}
              {ev.validated_by && (
                <div>
                  <div className="k">校验</div>
                  <div className="v">{ev.validated_by}</div>
                </div>
              )}
              {typeof ev.iteration === 'number' && (
                <div>
                  <div className="k">分析步骤</div>
                  <div className="v">#{ev.iteration}</div>
                </div>
              )}
            </div>
            <p style={{ color: 'var(--ink-3)', marginTop: 10 }}>
              本结论由执行控制层校验，SQL 仅访问只读视图 <span className="mono">sales_orders</span>，未执行写操作。
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function InsightCard({
  finding,
  defaultOpen,
  dispatch,
}: {
  finding: Finding
  defaultOpen: boolean
  dispatch: Dispatch<Action>
}) {
  const [open, setOpen] = useState(defaultOpen)
  const typeUpper = (finding.type || '').toUpperCase()
  const tagCls = typeUpper === 'TREND' ? 'trend' : typeUpper === 'FACT' ? 'fact' : ''
  const ev = finding.evidence
  return (
    <article className="insight">
      <div className="insight-hd">
        <span className={`insight-tag ${tagCls}`}>
          <span className="dot" />
          {typeUpper}
        </span>
        <div />
        <span className="insight-conf">置信度 {(finding.confidence || '').toUpperCase()}</span>
      </div>
      <div className="insight-body">
        <p>{finding.text}</p>
      </div>
      {finding.chart && (
        <div className="insight-chart">
          <div className="chart-mount">
            <FindingChart
              spec={finding.chart.echarts_spec}
              title={finding.chart.title}
              onRenderError={(title) => dispatch({ type: 'CHART_ERROR', title })}
            />
          </div>
        </div>
      )}
      <div className="insight-foot">
        <div className="evi">
          <span>
            <Ico.Database size={11} /> {ev.data_source}
          </span>
          {ev.ran_at && (
            <span>
              <Ico.Clock size={11} /> {formatClock(ev.ran_at)}
            </span>
          )}
          {typeof ev.iteration === 'number' && (
            <span>
              <Ico.Loop size={11} /> 第 {ev.iteration} 步
            </span>
          )}
        </div>
        <button className="trace" onClick={() => setOpen(!open)}>
          <Ico.Code size={12} /> {open ? '收起' : '查看'}依据
          <span
            style={{
              transform: open ? 'rotate(90deg)' : 'rotate(0)',
              display: 'inline-block',
              transition: 'transform 150ms',
            }}
          >
            <Ico.Caret size={9} />
          </span>
        </button>
      </div>
      {open && <InsightEvidence finding={finding} />}
    </article>
  )
}

function KPIStrip({ kpis }: { kpis: KPI[] }) {
  return (
    <div className="kpi-grid">
      {kpis.map((k) => {
        const up = kpiIsUp(k)
        const positive = kpiIsPositive(k)
        const cls = positive ? 'up' : 'down'
        const color = positive ? 'var(--forest-600)' : 'var(--rust-500)'
        return (
          <div className="kpi" key={k.name}>
            <span className="lbl">{k.name}</span>
            <span className="val">
              {k.unit === '元' && '¥'}
              {k.current.toLocaleString('zh-CN')}
              {k.unit === '%' && <span className="unit">%</span>}
              {k.unit !== '%' && k.unit !== '元' && <span className="unit"> {k.unit}</span>}
            </span>
            <span className={`delta ${cls}`}>
              <span className="arrow">{up ? <Ico.ArrowUp size={9} /> : <Ico.ArrowDown size={9} />}</span>
              <span>{kpiDeltaText(k)}</span>
              <span className="vs">环比</span>
            </span>
            {k.spark && k.spark.length > 1 && (
              <div className="spark">
                <Sparkline data={k.spark} color={color} width={150} height={22} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function PreviousComparisonSection({
  comparison,
  onOpenPrevious,
}: {
  comparison: PreviousComparison
  onOpenPrevious: (reportId: string) => void
}) {
  const [noteOpen, setNoteOpen] = useState(false)
  const title = comparison.same_period ? '与上次运行对比（相同时间窗）' : '对比上期'
  return (
    <>
      <div className="rep-section-hd">
        <span className="nb">§ 01</span>
        <h3>{title}</h3>
        <span className="line" />
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-4)' }}>
          跨报告对比
        </span>
      </div>
      <section className="cmp" aria-label={title}>
        <div className="cmp-hd">
          <div className="cmp-meta">
            <span>
              <Ico.Clock size={11} /> 上期报告生成于 <b>{formatHistoryDate(comparison.previous_ran_at)}</b>
            </span>
            {comparison.previous_status === 'partial' && (
              <span className="cmp-flag">
                <Ico.Warn size={11} /> 上期分析未完整
              </span>
            )}
            {comparison.same_period && (
              <span className="cmp-flag muted">时间窗与上次运行相同或重叠，不是周期环比</span>
            )}
          </div>
          <button
            className="btn ghost sm"
            onClick={() => onOpenPrevious(comparison.previous_report_id)}
            title="打开上期报告的只读详情"
          >
            <Ico.Doc size={11} /> 查看上期报告
          </button>
        </div>

        {comparison.baseline.length === 0 ? (
          <p className="cmp-empty">上期无可对比指标。</p>
        ) : (
          <table className="cmp-table">
            <thead>
              <tr>
                <th>指标</th>
                <th className="num">上期值</th>
                <th className="num">本期值</th>
                <th className="num">变化</th>
              </tr>
            </thead>
            <tbody>
              {comparison.baseline.map((entry) => (
                <tr key={entry.name}>
                  <td>{entry.name}</td>
                  <td className="num">{formatComparisonValue(entry.previous_value, entry.unit)}</td>
                  <td className="num">{formatComparisonValue(entry.current_value, entry.unit)}</td>
                  <td className={`num cmp-delta ${comparisonDeltaClass(entry)}`}>
                    {formatComparisonDelta(entry)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="cmp-note">
          <button className="btn subtle xs" onClick={() => setNoteOpen((open) => !open)}>
            <Ico.Doc size={11} /> {noteOpen ? '收起' : '展开'}上期摘要
          </button>
          {noteOpen && <blockquote>{comparison.summary_note || '上期报告没有执行摘要。'}</blockquote>}
        </div>
        <p className="cmp-foot">
          对比值取自上期报告存档的核心指标，由系统按指标名对齐计算，不由模型生成；率值指标按百分点（pp）呈现且不参与阈值着色。
        </p>
      </section>
    </>
  )
}

function ReportDoc({
  report,
  reportId,
  dispatch,
  onOpenHistory,
}: {
  report: ReportPayload
  reportId: string | null
  dispatch: Dispatch<Action>
  onOpenHistory: (reportId: string) => void
}) {
  const info = reportRunInfo(report)
  const comparison = report.previous_comparison ?? null
  // 含对比段落时其占 § 01，后续段落顺延。
  const sectionNo = (index: number) => `§ ${String(comparison ? index + 1 : index).padStart(2, '0')}`
  const recommendations = report.findings.filter((f) => (f.type || '').toLowerCase() === 'recommendation')
  const sqlCount = report.findings.filter((f) => f.evidence?.sql).length
  const chartCount = report.findings.filter((f) => f.chart).length
  return (
    <div className="rep-wrap">
      <div className="rep-tagrow">
        <span className="d" /> 报告 · 周度
        {report.status === 'partial' && (
          <span style={{ marginLeft: 10, color: 'var(--amber-500)' }}>· 部分报告</span>
        )}
      </div>
      <h1 className="rep-title">{report.title}</h1>
      <div className="rep-byline">
        <span>
          生成于 <b>{info.ranAt}</b>
        </span>
        <span>
          数据源 <b className="mono">{info.dataSource}</b>
        </span>
        <span>{info.rowCount.toLocaleString('zh-CN')} 行</span>
        <span className="pill" title="生成本报告时使用的业务口径版本">
          <Ico.Sparkle size={10} /> {friendlyContextPack(report.context_pack_name)}
          {report.context_pack_version ? ` · 口径 ${report.context_pack_version}` : ''}
        </span>
        <span>
          {info.analysisCounts} · {info.tokenUsed.toLocaleString('zh-CN')} tokens
        </span>
      </div>

      {report.summary && <p className="rep-lede">{report.summary}</p>}

      {comparison && (
        <PreviousComparisonSection comparison={comparison} onOpenPrevious={onOpenHistory} />
      )}

      <div className="rep-section-hd">
        <span className="nb">{sectionNo(1)}</span>
        <h3>核心指标</h3>
        <span className="line" />
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-4)' }} title="本次上传文件内相邻周期的对比">
          本文件内环比
        </span>
      </div>
      {report.kpis.length > 0 ? (
        <KPIStrip kpis={report.kpis} />
      ) : (
        <p style={{ color: 'var(--ink-3)', fontSize: 13 }}>本期未生成核心指标。</p>
      )}

      <div className="rep-section-hd">
        <span className="nb">{sectionNo(2)}</span>
        <h3>关键洞察</h3>
        <span className="line" />
        <span className="mono" style={{ fontSize: 11, color: 'var(--ink-4)' }}>
          {report.findings.length} 项
        </span>
      </div>
      <div className="insights">
        {report.findings.map((f, i) => (
          <InsightCard key={f.id} finding={f} defaultOpen={i === 0} dispatch={dispatch} />
        ))}
      </div>

      {recommendations.length > 0 && (
        <>
          <div className="rep-section-hd">
            <span className="nb">{sectionNo(3)}</span>
            <h3>下一步建议</h3>
            <span className="line" />
          </div>
          <ol
            style={{
              margin: 0,
              paddingLeft: 18,
              color: 'var(--ink-1)',
              fontSize: 14,
              lineHeight: 1.7,
            }}
          >
            {recommendations.map((f) => (
              <li key={f.id}>{f.text}</li>
            ))}
          </ol>
        </>
      )}

      <div className="rep-foot">
        <div>
          <h5>运行信息</h5>
          <div className="meta-row">
            <span className="k">数据源</span>
            <span className="v">{info.dataSource}</span>
          </div>
          <div className="meta-row">
            <span className="k">运行时间</span>
            <span className="v">{info.ranAt}</span>
          </div>
          <div className="meta-row">
            <span className="k">模型</span>
            <span className="v">{info.model}</span>
          </div>
          <div className="meta-row">
            <span className="k">分析过程</span>
            <span className="v">{info.analysisCounts}</span>
          </div>
        </div>
        <div>
          <h5>追溯</h5>
          <div className="meta-row">
            <span className="k">SQL 数量</span>
            <span className="v">{sqlCount} 条（已校验）</span>
          </div>
          <div className="meta-row">
            <span className="k">图表</span>
            <span className="v">{chartCount} 张（ECharts spec）</span>
          </div>
          <div className="meta-row">
            <span className="k">校验</span>
            <span className="v" style={{ color: 'var(--forest-600)' }}>
              ✓ 全部通过
            </span>
          </div>
        </div>
      </div>

      {/* 只有已落库的报告才能投票；key 保证切换报告时反馈状态随之重建。 */}
      {reportId && <ReportFeedback key={reportId} reportId={reportId} />}
    </div>
  )
}

function TaskReadOnly({
  state,
  taskOverride,
  compareOverride,
  userGoalOverride,
}: {
  state: AppState
  taskOverride?: StructuredTask | null
  compareOverride?: string
  userGoalOverride?: string
}) {
  const sourceTask = taskOverride ?? state.task
  if (!sourceTask) return null
  const task = taskView(sourceTask, compareOverride ?? state.compare)
  const rowStyle = {
    display: 'grid',
    gridTemplateColumns: '90px 1fr',
    padding: '10px 0',
    borderBottom: '1px dashed var(--line-soft)',
  } as const
  return (
    <div>
      <div className="lbl-row" style={rowStyle}>
        <span className="muted" style={{ fontSize: 11.5 }}>
          分析场景
        </span>
        <span className="chip">{friendlyContextPack(task.context)}</span>
      </div>
      <div className="lbl-row" style={rowStyle}>
        <span className="muted" style={{ fontSize: 11.5 }}>
          指标
        </span>
        <div className="chips" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {task.metrics.map((m) => (
            <span className="chip" key={m}>
              {m}
            </span>
          ))}
        </div>
      </div>
      <div className="lbl-row" style={rowStyle}>
        <span className="muted" style={{ fontSize: 11.5 }}>
          维度
        </span>
        <div className="chips" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {task.dims.map((d) => (
            <span className="chip dim" key={d}>
              {d}
            </span>
          ))}
        </div>
      </div>
      <div className="lbl-row" style={rowStyle}>
        <span className="muted" style={{ fontSize: 11.5 }}>
          对比
        </span>
        <span className="chip">{task.compare}</span>
      </div>
      <div className="lbl-row" style={{ display: 'grid', gridTemplateColumns: '90px 1fr', padding: '10px 0' }}>
        <span className="muted" style={{ fontSize: 11.5 }}>
          原始需求
        </span>
        <div
          style={{
            padding: 10,
            background: 'var(--bg-panel)',
            border: '1px solid var(--line-soft)',
            borderRadius: 'var(--r-sm)',
            fontFamily: 'var(--font-serif)',
            fontSize: 14,
            color: 'var(--ink-1)',
            maxWidth: 560,
          }}
        >
          {userGoalOverride || state.userGoal || sourceTask.analysis_goal}
        </div>
      </div>
    </div>
  )
}

function TraceView({ report }: { report: ReportPayload }) {
  const withSql = report.findings.filter((f) => f.evidence?.sql)
  return (
    <div style={{ padding: '28px 32px', maxWidth: 920 }}>
      <div className="rep-tagrow">
        <span className="d" /> 追溯 · 全部 SQL
      </div>
      <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 22, fontWeight: 500, margin: '4px 0 6px' }}>
        报告依据中心
      </h2>
      <p style={{ color: 'var(--ink-3)', fontSize: 13, margin: '0 0 18px' }}>
        本报告共执行 {withSql.length} 条 SQL，全部走只读视图 <span className="mono">sales_orders</span>
        。点击复制可在外部 SQL Lab 复现。
      </p>
      {withSql.length === 0 && (
        <p style={{ color: 'var(--ink-3)', fontSize: 13 }}>本次报告未产生可追溯 SQL。</p>
      )}
      {withSql.map((f, i) => (
        <div
          key={f.id}
          style={{
            marginBottom: 18,
            background: 'var(--bg-panel)',
            border: '1px solid var(--line-soft)',
            borderRadius: 'var(--r-md)',
            padding: 14,
          }}
        >
          <div className="hstack" style={{ marginBottom: 10 }}>
            <span className="mono" style={{ color: 'var(--ink-3)', fontSize: 11 }}>
              § Q0{i + 1}
            </span>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{f.text.slice(0, 28)}</span>
            <span className="mono muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              {formatDateTime(f.evidence.ran_at)}
              {typeof f.evidence.iteration === 'number' ? ` · #${f.evidence.iteration}` : ''}
            </span>
          </div>
          <pre
            className="sql-block"
            style={{ margin: 0 }}
            dangerouslySetInnerHTML={{ __html: highlightSQL(f.evidence.sql) }}
          />
        </div>
      ))}
    </div>
  )
}

type ArtifactPaneProps = {
  state: AppState
  dispatch: Dispatch<Action>
  onSelectSheet: (sheet: string) => void
  onPickSample: () => void
  onPickUpload: () => void
  onOpenHistory: (reportId: string) => void
  onOpenTask: (taskId: string) => void
  onSaveTask: (reportId: string, title: string) => Promise<void>
  onRenameTask: (taskId: string, title: string) => Promise<void>
  onPickTaskUpload: () => void
  onSelectTaskSheet: (sheet: string) => Promise<void>
  onConfirmTaskRerun: () => Promise<void>
  onStopTaskRerun: () => void
}

export default function ArtifactPane({
  state,
  dispatch,
  onSelectSheet,
  onPickSample,
  onPickUpload,
  onOpenHistory,
  onOpenTask,
  onSaveTask,
  onRenameTask,
  onPickTaskUpload,
  onSelectTaskSheet,
  onConfirmTaskRerun,
  onStopTaskRerun,
}: ArtifactPaneProps) {
  const tab = state.artifactTab
  const report =
    state.mode === 'tasks' ? null : state.mode === 'history' ? state.historyReport : state.report
  const dataset =
    state.mode === 'tasks'
      ? null
      : state.mode === 'history'
      ? state.historyDataset
      : state.mode === 'dataset'
        ? state.datasetPreview
        : state.dataset
  const task = state.mode === 'tasks' ? null : state.mode === 'history' ? state.historyTask : state.task
  const userGoal = state.mode === 'history' ? state.historyUserGoal : state.userGoal
  const progress = state.mode === 'history' ? state.historyProgress : state.progress
  const readonly = state.mode === 'history' || state.mode === 'dataset'
  const effectiveStep =
    state.mode === 'tasks'
      ? 'empty'
      : state.mode === 'history'
      ? report
        ? 'report'
        : 'empty'
      : state.mode === 'dataset'
        ? dataset
          ? 'dataset'
          : 'empty'
        : state.step
  const [printPending, setPrintPending] = useState(false)
  const [saveTaskOpen, setSaveTaskOpen] = useState(false)
  const reportId = state.mode === 'history' ? state.historyDetail?.id ?? null : state.currentReportId
  const reportTaskId =
    state.mode === 'history' ? state.historyDetail?.task_id ?? null : state.currentReportTaskId
  const reportTaskTitle =
    state.mode === 'history' ? state.historyDetail?.task_title ?? null : state.currentReportTaskTitle

  // 导出 PDF（方案 A）：其它 tab 时报告内容未挂载，先切回报告 tab，等渲染后再触发浏览器打印。
  useEffect(() => {
    if (!printPending) return
    if (effectiveStep !== 'report' || tab !== 'report') return
    const id = window.requestAnimationFrame(() => {
      window.print()
      setPrintPending(false)
    })
    return () => window.cancelAnimationFrame(id)
  }, [printPending, tab, effectiveStep])

  function handleExportPdf() {
    if (tab !== 'report') dispatch({ type: 'TAB', tab: 'report' })
    setPrintPending(true)
  }

  let title = '工作台'
  let crumbs: string[] = ['工作台']
  let icon = <Ico.Database />
  const sourceName = dataset?.data_source_ref.name
  if (dataset) {
    title = '数据集预览'
    crumbs = ['工作台', sourceName!]
    icon = <Ico.Database />
  }
  if (effectiveStep === 'task_ready') {
    title = '结构化任务'
    crumbs = ['工作台', sourceName!, '任务确认']
    icon = <Ico.Sparkle />
  }
  if (effectiveStep === 'generating') {
    title = '正在生成报告'
    crumbs = ['工作台', '生成中']
    icon = <Ico.Loop />
  }
  if (effectiveStep === 'report' && report) {
    title = report.title
    crumbs = readonly ? ['历史报告', report.metadata.data_source.name ?? '报告'] : ['工作台', '报告']
    icon = <Ico.Doc />
  }
  if (state.mode === 'dataset') {
    title = dataset?.data_source_ref.name ?? '数据源'
    crumbs = ['数据源', dataset?.data_source_ref.name ?? '选择数据源']
    icon = <Ico.Database />
  }
  if (state.mode === 'tasks') {
    title = state.taskDetail?.title ?? '分析任务'
    crumbs = ['分析任务', state.taskDetail?.title ?? '选择任务']
    icon = <Ico.Template />
  }

  return (
    <section className="art">
      <div className="art-hd">
        <div className="ttl">
          <span className="ic">{icon}</span>
          <div>
            <h3>{title}</h3>
            <div className="crumbs">
              {crumbs.map((c) => (
                <span key={c}>{c}</span>
              ))}
            </div>
          </div>
        </div>
        <div className="tools">
          {readonly && <span className="readonly-pill">只读</span>}
          {effectiveStep === 'report' && report && (
            <>
              {reportTaskId ? (
                <button className="btn ghost sm" onClick={() => onOpenTask(reportTaskId)}>
                  <Ico.Template size={11} /> 已保存 · {reportTaskTitle ?? '查看任务'}
                </button>
              ) : reportId ? (
                <button className="btn primary sm" onClick={() => setSaveTaskOpen(true)}>
                  <Ico.Template size={11} /> 保存为任务
                </button>
              ) : null}
              <button className="btn ghost sm" onClick={handleExportPdf} title="导出当前报告为 PDF">
                <Ico.Download size={11} /> 导出 PDF
              </button>
            </>
          )}
        </div>
      </div>

      {effectiveStep === 'report' && report && (
        <div className="art-tabs">
          <button
            className={`art-tab ${tab === 'report' ? 'active' : ''}`}
            onClick={() => dispatch({ type: 'TAB', tab: 'report' })}
          >
            <span className="num">01</span> 报告
          </button>
          <button
            className={`art-tab ${tab === 'dataset' ? 'active' : ''}`}
            onClick={() => dispatch({ type: 'TAB', tab: 'dataset' })}
          >
            <span className="num">02</span> 数据集
          </button>
          <button
            className={`art-tab ${tab === 'task' ? 'active' : ''}`}
            onClick={() => dispatch({ type: 'TAB', tab: 'task' })}
          >
            <span className="num">03</span> 任务定义
          </button>
          <button
            className={`art-tab ${tab === 'trace' ? 'active' : ''}`}
            onClick={() => dispatch({ type: 'TAB', tab: 'trace' })}
          >
            <span className="num">04</span> 全部 SQL
          </button>
        </div>
      )}

      <div className="art-scroll">
        {state.mode === 'tasks' && (
          <TaskPane
            state={state}
            onOpenHistory={onOpenHistory}
            onRenameTask={onRenameTask}
            onPickTaskUpload={onPickTaskUpload}
            onSelectTaskSheet={onSelectTaskSheet}
            onConfirmTaskRerun={onConfirmTaskRerun}
            onStopTaskRerun={onStopTaskRerun}
          />
        )}

        {state.mode !== 'tasks' && !dataset && (
          <div className="art-empty">
            <div className="art-empty-card">
              <div className="ic">
                {state.mode === 'history' ? <Ico.Doc size={26} /> : <Ico.Database size={26} />}
              </div>
              <h3>
                {state.historyDetailLoading || state.datasetDetailLoading
                  ? '正在读取详情'
                  : readonly
                    ? '选择一条记录'
                    : '等待数据接入'}
              </h3>
              <p>
                {readonly
                  ? '从中间列表选择历史报告或数据源，详情会在这里只读展示。'
                  : '从左侧上传 CSV / Excel，或一键载入零售样例。选定后字段映射与样本预览会出现在这里。'}
              </p>
              {!readonly && (
                <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginTop: 14 }}>
                  <button className="btn primary sm" onClick={onPickSample} disabled={Boolean(state.busy)}>
                    <Ico.Sample size={11} /> 使用零售样例
                  </button>
                  <button className="btn ghost sm" onClick={onPickUpload} disabled={Boolean(state.busy)}>
                    <Ico.Upload size={11} /> 上传文件
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {dataset &&
          (effectiveStep === 'dataset' || effectiveStep === 'parsing' || effectiveStep === 'task_ready') && (
            <DatasetProfile
              state={state}
              onSelectSheet={onSelectSheet}
              datasetOverride={dataset}
              readonly={readonly}
              detail={state.mode === 'dataset' ? state.datasetDetail : null}
            />
          )}

        {effectiveStep === 'generating' && <GenerationView state={{ ...state, progress }} />}

        {effectiveStep === 'report' && report && tab === 'report' && (
          <ReportDoc
            report={report}
            reportId={reportId}
            dispatch={dispatch}
            onOpenHistory={onOpenHistory}
          />
        )}
        {effectiveStep === 'report' && report && tab === 'dataset' && (
          <DatasetProfile
            state={state}
            onSelectSheet={onSelectSheet}
            datasetOverride={dataset}
            readonly={readonly}
          />
        )}
        {effectiveStep === 'report' && report && tab === 'task' && (
          <div style={{ padding: '28px 32px', maxWidth: 720 }}>
            <div className="rep-tagrow">
              <span className="d" /> 任务定义
            </div>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 22, fontWeight: 500, margin: '4px 0 16px' }}>
              {task?.task_title}
            </h2>
            <TaskReadOnly state={state} taskOverride={task} userGoalOverride={userGoal} />
          </div>
        )}
        {effectiveStep === 'report' && report && tab === 'trace' && <TraceView report={report} />}
      </div>
      <SaveTaskDialog
        open={saveTaskOpen}
        initialTitle={task?.task_title ?? report?.title ?? '分析任务'}
        onClose={() => setSaveTaskOpen(false)}
        onSave={(title) => {
          if (!reportId) return Promise.resolve()
          return onSaveTask(reportId, title)
        }}
      />
    </section>
  )
}
