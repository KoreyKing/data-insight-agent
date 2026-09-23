import { useEffect, useState, type FormEvent } from 'react'
import { asApiError, type ApiError } from '../api/client'
import type { AppState } from '../lib/state'
import { formatHistoryDate, historySummary, statusLabel } from '../lib/history'
import { friendlyContextPack } from '../lib/view'
import { Ico } from './icons'

type TaskPaneProps = {
  state: AppState
  onOpenHistory: (reportId: string) => void
  onRenameTask: (taskId: string, title: string) => Promise<void>
  onPickTaskUpload: () => void
  onSelectTaskSheet: (sheet: string) => Promise<void>
  onConfirmTaskRerun: () => Promise<void>
  onStopTaskRerun: () => void
}

function mismatchFields(error: ApiError | null, key: string): string[] {
  const value = error?.details?.[key]
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

export default function TaskPane({
  state,
  onOpenHistory,
  onRenameTask,
  onPickTaskUpload,
  onSelectTaskSheet,
  onConfirmTaskRerun,
  onStopTaskRerun,
}: TaskPaneProps) {
  const detail = state.taskDetail
  const [editingTitle, setEditingTitle] = useState(false)
  const [title, setTitle] = useState('')
  const [titleError, setTitleError] = useState('')

  useEffect(() => {
    setTitle(detail?.title ?? '')
    setEditingTitle(false)
    setTitleError('')
  }, [detail?.id, detail?.title])

  if (state.taskDetailLoading) {
    return (
      <div className="art-empty">
        <div className="art-empty-card">
          <div className="ic"><Ico.Loop size={24} /></div>
          <h3>正在读取任务详情</h3>
          <p>正在加载任务定义、数据结构与报告链。</p>
        </div>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="art-empty">
        <div className="art-empty-card">
          <div className="ic"><Ico.Template size={24} /></div>
          <h3>选择一个分析任务</h3>
          <p>任务定义、所需字段和历次报告会显示在这里。</p>
        </div>
      </div>
    )
  }
  const taskId = detail.id

  async function submitTitle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalized = title.trim()
    if (!normalized || normalized.length > 255) {
      setTitleError('任务名不能为空，且不超过 255 字。')
      return
    }
    setTitleError('')
    try {
      await onRenameTask(taskId, normalized)
      setEditingTitle(false)
    } catch (value) {
      setTitleError(asApiError(value).message)
    }
  }

  const rerunDataset = state.taskRerunDataset
  const mismatch = state.taskRerunError?.code === 'SCHEMA_MISMATCH'
  const missing = mismatchFields(state.taskRerunError, 'missing_fields_display')
  const extra = mismatchFields(state.taskRerunError, 'extra_fields_display')
  const rerunning = state.busy === 'task-rerun'
  const checking = state.busy === 'task-rerun-check'
  const uploadBusy = state.busy === 'task-upload'

  return (
    <div className="task-detail">
      <div className="task-detail-hero">
        <div className="rep-tagrow"><span className="d" /> 可复用分析任务</div>
        {editingTitle ? (
          <form className="task-title-form" onSubmit={submitTitle}>
            <input
              value={title}
              maxLength={255}
              onChange={(event) => setTitle(event.target.value)}
              aria-label="任务名称"
              autoFocus
            />
            <button className="btn primary sm" type="submit" disabled={state.busy === 'task-rename'}>
              保存
            </button>
            <button
              className="btn subtle sm"
              type="button"
              onClick={() => {
                setTitle(detail.title)
                setEditingTitle(false)
                setTitleError('')
              }}
            >
              取消
            </button>
          </form>
        ) : (
          <div className="task-title-row">
            <h2>{detail.title}</h2>
            <button className="btn subtle xs" onClick={() => setEditingTitle(true)}>
              改名
            </button>
          </div>
        )}
        {titleError && <div className="task-inline-error">{titleError}</div>}
        <p>{detail.analysis_goal}</p>
        <div className="task-meta-row">
          <span><Ico.Clock size={11} /> 创建于 {formatHistoryDate(detail.created_at)}</span>
          <span>{friendlyContextPack(detail.context_pack_name)} · {detail.context_pack_version}</span>
          <span>{detail.report_count} 份报告</span>
        </div>
      </div>

      <section className="task-section">
        <div className="task-section-hd">
          <div><span>01</span><h3>任务定义</h3></div>
          <small>保存时快照 · 只读</small>
        </div>
        <div className="task-definition-grid">
          <div><span>指标</span><div className="chips">{detail.structured_task.metrics.map((metric) => <b className="chip" key={metric}>{metric}</b>)}</div></div>
          <div><span>维度</span><div className="chips">{detail.structured_task.dimensions.map((dimension) => <b className="chip dim" key={dimension}>{dimension}</b>)}</div></div>
          <div><span>对比方式</span><strong>{detail.structured_task.comparison || '无对比'}</strong></div>
          <div><span>报告模板</span><strong>{detail.structured_task.report_template}</strong></div>
        </div>
      </section>

      <section className="task-section">
        <div className="task-section-hd">
          <div><span>02</span><h3>数据结构</h3></div>
          <small>重跑文件需包含完全一致的业务字段</small>
        </div>
        <div className="task-field-chips">
          {detail.canonical_fields.map((field) => (
            <span className="task-field" key={field.name} title={field.name}>{field.display_name}</span>
          ))}
        </div>
      </section>

      <section className="task-section task-rerun-section">
        <div className="task-section-hd">
          <div><span>03</span><h3>上传新数据重跑</h3></div>
          <small>CSV / Excel · 沿用本任务定义</small>
        </div>

        {rerunning ? (
          <div className="task-rerun-progress">
            <div className="task-rerun-progress-hd">
              <div><Ico.Loop size={13} /> 正在校验结构并生成新报告</div>
              <button className="btn danger xs" onClick={onStopTaskRerun}><Ico.X size={9} /> 停止</button>
            </div>
            {state.progress.map((step, index) => (
              <div className={`gen-step ${step.state}`} key={`${step.label}-${index}`}>
                <span className="ico">{step.state === 'done' ? <Ico.Check size={11} /> : <Ico.Loop size={11} />}</span>
                <div><div className="ttl">{step.label}</div><div className="det">{step.detail}</div></div>
                <div className="t">{step.state === 'pending' ? '' : '…'}</div>
              </div>
            ))}
            {state.genWaiting && <div className="task-rerun-wait">仍在分析中，正在等待模型返回结果…</div>}
            <div className="task-rerun-elapsed">已用 {state.elapsed || '0.0'}s</div>
          </div>
        ) : (
          <>
            <div className={`task-upload-zone ${rerunDataset ? 'ready' : ''}`}>
              <div className="task-upload-icon"><Ico.Upload size={18} /></div>
              <div className="task-upload-copy">
                <strong>{rerunDataset?.data_source_ref.name ?? '选择本期导出的同结构文件'}</strong>
                <span>
                  {rerunDataset
                    ? `${rerunDataset.row_count.toLocaleString('zh-CN')} 行 · ${rerunDataset.column_count} 个字段`
                    : '系统会先识别业务字段，结构一致后才会生成报告。'}
                </span>
              </div>
              <button className="btn ghost sm" onClick={onPickTaskUpload} disabled={uploadBusy || checking}>
                {uploadBusy ? '正在上传…' : rerunDataset ? '重新选择' : '选择文件'}
              </button>
            </div>

            {rerunDataset && rerunDataset.workbook_sheets.length > 1 && (
              <div className="task-sheet-picker">
                <span>选择工作表</span>
                <div>
                  {rerunDataset.workbook_sheets.filter((sheet) => sheet.visible && !sheet.empty).map((sheet) => (
                    <button
                      className={`chip ${sheet.selected ? '' : 'add'}`}
                      key={sheet.name}
                      onClick={() => onSelectTaskSheet(sheet.name)}
                      disabled={uploadBusy || checking}
                    >
                      {sheet.name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {rerunDataset && (
              <div className="task-rerun-actions">
                <button
                  className="btn primary task-rerun-cta"
                  onClick={onConfirmTaskRerun}
                  disabled={uploadBusy || checking || Boolean(state.taskRerunError)}
                >
                  <Ico.Loop size={12} /> {checking ? '正在核对数据结构…' : '确认数据并开始重跑'}
                </button>
                {checking && (
                  <button className="btn danger task-rerun-cta" onClick={onStopTaskRerun}>
                    <Ico.X size={10} /> 停止
                  </button>
                )}
              </div>
            )}
          </>
        )}

        {state.taskRerunError && !rerunning && (
          <div className={`task-action-alert ${mismatch ? 'mismatch' : 'error'}`}>
            <div className="task-action-alert-title"><Ico.Warn size={13} /> {state.taskRerunError.message}</div>
            {mismatch && (
              <>
                <div className="task-mismatch-grid">
                  <div><span>缺少字段</span><strong>{missing.length ? missing.join('、') : '无'}</strong></div>
                  <div><span>多出字段</span><strong>{extra.length ? extra.join('、') : '无'}</strong></div>
                </div>
                <ol>
                  <li>检查是否使用了与上期相同的导出模板。</li>
                  <li>如果最近修改过字段别名，请到“业务口径设置”核对。</li>
                  <li>业务字段确实变化时，可用新文件直接生成并另存为新任务；新任务首期没有上期对比。</li>
                </ol>
              </>
            )}
          </div>
        )}
      </section>

      <section className="task-section">
        <div className="task-section-hd">
          <div><span>04</span><h3>报告链</h3></div>
          <small>按运行时间倒序</small>
        </div>
        <div className="task-report-chain">
          {detail.reports.map((report, index) => (
            <button key={report.id} onClick={() => onOpenHistory(report.id)}>
              <span className="task-chain-index">{String(detail.reports.length - index).padStart(2, '0')}</span>
              <span className="task-chain-main">
                <strong>{formatHistoryDate(report.ran_at)}</strong>
                <small>{historySummary(report.summary, 110)}</small>
              </span>
              <span className="task-chain-meta">
                <b>{statusLabel(report.status)}</b>
                <small>{report.finding_count} 洞察</small>
                {report.has_previous_comparison && <em>含上期对比</em>}
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  )
}
