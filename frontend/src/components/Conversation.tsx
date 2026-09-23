import { useEffect, useRef, useState, type Dispatch, type ReactNode } from 'react'
import type { Action, AppState } from '../lib/state'
import { taskView } from '../lib/state'
import { defaultGoal, type DimensionOption, type ModelStatus } from '../api/client'
import { formatHistoryDate, historySummary, statusLabel } from '../lib/history'
import { formatAnalysisCounts, friendlyContextPack } from '../lib/view'
import { Ico } from './icons'

const SUGGESTED_QUESTIONS = [
  '本周和上周比，看销售变化和哪些店表现异常',
  '哪些商品退款最多，原因可能是什么',
  '抖音渠道最近 4 周的趋势怎么样',
  '上海 3 家门店本月的销售情况',
]

function MsgAvatar({ kind }: { kind: 'user' | 'agent' }) {
  return <span className="av">{kind === 'user' ? 'K' : 'D'}</span>
}

function AgentMsg({ children, plain }: { children: ReactNode; plain?: boolean }) {
  return (
    <div className="msg agent">
      <div className="msg-meta agent">
        <MsgAvatar kind="agent" />
        <span>Agent</span>
        <span style={{ color: 'var(--ink-4)' }}>· 实时</span>
      </div>
      <div className={`msg-body ${plain ? 'plain' : ''}`}>{children}</div>
    </div>
  )
}

function UserMsg({ children }: { children: ReactNode }) {
  return (
    <div className="msg user">
      <div className="msg-meta user">
        <MsgAvatar kind="user" />
        <span>你</span>
      </div>
      <div className="msg-body">{children}</div>
    </div>
  )
}

function HeroBlock({
  onPickSample,
  onPickUpload,
}: {
  onPickSample: () => void
  onPickUpload: () => void
}) {
  return (
    <div className="hero">
      <h2>把数据交给 Agent，让它取数、出图、解释每一个结论。</h2>
      <p>支持 CSV / Excel 表格。从一个文件或示例开始，提一句中文需求即可。</p>
      <div className="hero-tags">
        <span className="hero-tag">
          <Ico.Sparkle size={11} /> 行业知识包 · 零售经营
        </span>
        <span className="hero-tag">
          <Ico.Code size={11} /> 每个结论可追溯到 SQL
        </span>
        <span className="hero-tag">
          <Ico.Database size={11} /> 自部署 · 自配模型
        </span>
      </div>
      <div className="hero-grid">
        <button className="hero-card" onClick={onPickSample}>
          <span className="ic-wrap">
            <Ico.Sample />
          </span>
          <span className="ttl">先看一份示例</span>
          <span className="sub">一份零售门店近 3 个月的订单数据，点击即可试跑</span>
        </button>
        <button className="hero-card" onClick={onPickUpload}>
          <span className="ic-wrap sky">
            <Ico.Upload />
          </span>
          <span className="ttl">上传自己的表格</span>
          <span className="sub">CSV 或 .xlsx，多 sheet 可在右侧选择工作表</span>
        </button>
      </div>
    </div>
  )
}

function ThinkStep({ state, label, detail, time }: AppState['parsing'][number]) {
  return (
    <div className={`think-step ${state}`}>
      <span className="ic">
        {state === 'done' ? (
          <Ico.Check size={14} />
        ) : state === 'active' ? (
          <Ico.Loop size={14} />
        ) : (
          <Ico.Dot size={6} />
        )}
      </span>
      <span className="lbl">{label}</span>
      <span className="t">{time}</span>
      {detail && <div className="think-detail" style={{ gridColumn: '2 / -1' }}>{detail}</div>}
    </div>
  )
}

function GenProgress({ progress }: { progress: AppState['progress'] }) {
  return (
    <div className="thinking">
      {progress.map((p, i) => (
        <ThinkStep key={i} {...p} />
      ))}
    </div>
  )
}

function DimAdder({
  options,
  selected,
  dispatch,
}: {
  options: DimensionOption[]
  selected: string[]
  dispatch: Dispatch<Action>
}) {
  const [open, setOpen] = useState(false)
  const candidates = options.filter((o) => !selected.includes(o.name))
  if (candidates.length === 0) return null
  return (
    <span className="dim-adder">
      <button className="chip add" onClick={() => setOpen((o) => !o)}>
        <Ico.Plus size={9} /> 添加维度
      </button>
      {open && (
        <div className="dim-menu">
          <div className="dim-menu-hd">该分析场景支持的维度</div>
          {candidates.map((c) => (
            <button
              key={c.name}
              className="dim-menu-item"
              onClick={() => {
                dispatch({ type: 'ADD_DIM', value: c.name })
                setOpen(false)
              }}
            >
              <span className="dim-name">{c.name}</span>
              {c.description && <span className="dim-desc">{c.description}</span>}
            </button>
          ))}
        </div>
      )}
    </span>
  )
}

function TaskCard({
  state,
  dispatch,
  onRun,
}: {
  state: AppState
  dispatch: Dispatch<Action>
  onRun: () => void
}) {
  if (!state.task) return null
  const task = taskView(state.task, state.compare)
  return (
    <div className="task-summary-card">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: 10,
        }}
      >
        <div className="hstack" style={{ gap: 8 }}>
          <Ico.Sparkle size={14} />
          <strong style={{ fontSize: 14 }}>{task.title}</strong>
        </div>
        <span className="muted" style={{ fontSize: 11 }}>
          已解析 · 可编辑
        </span>
      </div>
      <div className="lbl-row">
        <span className="lbl">分析场景</span>
        <div>
          <span className="chip">{friendlyContextPack(task.context)}</span>
        </div>
      </div>
      <div className="lbl-row">
        <span className="lbl">指标</span>
        <div className="chips">
          {task.metrics.map((m, i) => (
            <span className="chip editable" key={m}>
              {m}
              <button className="x" onClick={() => dispatch({ type: 'CHIP_REMOVE', group: 'metrics', index: i })}>
                <Ico.X size={8} />
              </button>
            </span>
          ))}
        </div>
      </div>
      <div className="lbl-row">
        <span className="lbl">维度</span>
        <div className="chips">
          {task.dims.map((d, i) => (
            <span className="chip dim editable" key={d}>
              {d}
              <button className="x" onClick={() => dispatch({ type: 'CHIP_REMOVE', group: 'dims', index: i })}>
                <Ico.X size={8} />
              </button>
            </span>
          ))}
          <DimAdder options={state.dimensionOptions} selected={task.dims} dispatch={dispatch} />
        </div>
      </div>
      <div className="lbl-row">
        <span className="lbl">对比</span>
        <div className="chips">
          {['环比', '同比', '无对比'].map((opt) => (
            <button
              key={opt}
              className={`chip ${task.compare === opt ? '' : 'add'}`}
              style={task.compare === opt ? {} : { borderStyle: 'solid' }}
              onClick={() => dispatch({ type: 'SET_COMPARE', value: opt })}
            >
              {opt}
            </button>
          ))}
        </div>
      </div>
      <div className="task-actions">
        <button className="btn primary" onClick={onRun} disabled={state.busy === 'report'}>
          <Ico.Sparkle size={12} /> 生成可追溯报告
        </button>
        <button className="btn subtle" onClick={() => dispatch({ type: 'ABORT_TASK' })}>
          取消
        </button>
      </div>
    </div>
  )
}

function LibraryHeader({
  icon,
  title,
  count,
  note,
  eyebrow = 'READ ONLY',
}: {
  icon: ReactNode
  title: string
  count: number
  note: string
  eyebrow?: string
}) {
  return (
    <div className="library-hd">
      <div className="library-ic">{icon}</div>
      <div>
        <div className="library-eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        <p>{note}</p>
      </div>
      <span className="library-count">{count}</span>
    </div>
  )
}

function TaskLibrary({
  state,
  onOpenTask,
}: {
  state: AppState
  onOpenTask: (taskId: string) => void
}) {
  return (
    <section className="conv library-panel">
      <LibraryHeader
        icon={<Ico.Template size={16} />}
        title="分析任务"
        count={state.tasks.length}
        eyebrow="REUSABLE"
        note="保存满意的报告为任务，下期上传同结构文件即可沿用任务定义重跑。"
      />
      <div className="library-scroll">
        {state.tasksLoading && <div className="library-empty">正在读取分析任务…</div>}
        {state.tasksError && (
          <div className="library-empty error">
            <Ico.Warn size={14} /> {state.tasksError.message}
          </div>
        )}
        {!state.tasksLoading && !state.tasksError && state.tasks.length === 0 && (
          <div className="library-empty">
            <Ico.Template size={20} />
            <span>还没有保存的任务</span>
            <p>生成报告后可以把它保存为任务，下期数据一键重跑。</p>
          </div>
        )}
        {!state.tasksLoading &&
          state.tasks.map((task) => (
            <button
              key={task.id}
              className={`library-row ${state.selectedTaskId === task.id ? 'active' : ''}`}
              onClick={() => onOpenTask(task.id)}
            >
              <div className="library-row-main">
                <div className="library-row-title">{task.title}</div>
                <p>{historySummary(task.analysis_goal, 92)}</p>
              </div>
              <div className="library-row-meta">
                <span>
                  <Ico.Clock size={11} /> 最近运行 {formatHistoryDate(task.last_run_at)}
                </span>
                <span>{task.context_pack_name}</span>
                <span>{task.context_pack_version}</span>
              </div>
              <div className="library-row-stats">
                <span>{task.report_count} 份报告</span>
                <span>{task.status === 'active' ? '可重跑' : task.status}</span>
              </div>
            </button>
          ))}
      </div>
    </section>
  )
}

function HistoryLibrary({
  state,
  onOpenHistory,
}: {
  state: AppState
  onOpenHistory: (reportId: string) => void
}) {
  return (
    <section className="conv library-panel">
      <LibraryHeader
        icon={<Ico.Doc size={16} />}
        title="历史报告"
        count={state.historyTotal}
        note="点击任一报告，在右侧以只读方式查看报告正文、任务定义、SQL 依据与关联数据源。"
      />
      <div className="library-scroll">
        {state.historyLoading && <div className="library-empty">正在读取历史报告…</div>}
        {state.historyError && (
          <div className="library-empty error">
            <Ico.Warn size={14} /> {state.historyError.message}
          </div>
        )}
        {!state.historyLoading && !state.historyError && state.historyReports.length === 0 && (
          <div className="library-empty">
            <Ico.Doc size={20} />
            <span>暂无历史报告</span>
            <p>生成第一份报告后，这里会出现可回看的只读记录。</p>
          </div>
        )}
        {!state.historyLoading &&
          state.historyReports.map((report) => (
            <button
              key={report.id}
              className={`library-row ${state.selectedHistoryId === report.id ? 'active' : ''}`}
              onClick={() => onOpenHistory(report.id)}
            >
              <div className="library-row-main">
                <div className="library-row-title">{report.title}</div>
                <p>{historySummary(report.summary, 92)}</p>
              </div>
              <div className="library-row-meta">
                <span>
                  <Ico.Clock size={11} /> {formatHistoryDate(report.ran_at)}
                </span>
                <span>
                  <Ico.Database size={11} /> {report.dataset.file_name}
                </span>
                <span>{statusLabel(report.status)}</span>
              </div>
              <div className="library-row-stats">
                <span>{report.finding_count} 洞察</span>
                <span>{report.anomaly_count} 异常</span>
                <span>{formatAnalysisCounts(report.loop_rounds, report.iterations_used)}</span>
              </div>
            </button>
          ))}
      </div>
    </section>
  )
}

function DatasetLibrary({
  state,
  onOpenDataset,
}: {
  state: AppState
  onOpenDataset: (datasetId: string) => void
}) {
  return (
    <section className="conv library-panel">
      <LibraryHeader
        icon={<Ico.Database size={16} />}
        title="数据源"
        count={state.datasetsTotal}
        note="查看已写入历史的数据源结构、字段映射、样本预览，以及关联报告引用。"
      />
      <div className="library-scroll">
        {state.datasetsLoading && <div className="library-empty">正在读取数据源…</div>}
        {state.datasetsError && (
          <div className="library-empty error">
            <Ico.Warn size={14} /> {state.datasetsError.message}
          </div>
        )}
        {!state.datasetsLoading && !state.datasetsError && state.datasets.length === 0 && (
          <div className="library-empty">
            <Ico.Database size={20} />
            <span>暂无数据源</span>
            <p>每次成功生成报告后，系统会保存一份对应的数据源快照。</p>
          </div>
        )}
        {!state.datasetsLoading &&
          state.datasets.map((dataset) => (
            <button
              key={dataset.id}
              className={`library-row dataset ${state.selectedDatasetId === dataset.id ? 'active' : ''}`}
              onClick={() => onOpenDataset(dataset.id)}
            >
              <div className="library-row-main">
                <div className="library-row-title">{dataset.file_name}</div>
                <p>
                  {dataset.row_count.toLocaleString('zh-CN')} 行 · {dataset.column_count} 列 ·{' '}
                  {dataset.data_source_type.toUpperCase() || 'TABLE'}
                </p>
              </div>
              <div className="library-row-meta">
                <span>
                  <Ico.Clock size={11} /> {formatHistoryDate(dataset.created_at)}
                </span>
                <span>{statusLabel(dataset.status)}</span>
                <span>{dataset.report_count} 份报告</span>
              </div>
              <div className="library-row-stats">
                <span>最近报告 {formatHistoryDate(dataset.latest_report_at)}</span>
              </div>
            </button>
          ))}
      </div>
    </section>
  )
}

type ConversationProps = {
  state: AppState
  dispatch: Dispatch<Action>
  model: ModelStatus | null
  onPickSample: () => void
  onPickUpload: () => void
  onSubmitGoal: (goal: string) => void
  onRun: () => void
  onStop: () => void
  onOpenHistory: (reportId: string) => void
  onOpenDataset: (datasetId: string) => void
  onOpenTask: (taskId: string) => void
}

export default function Conversation({
  state,
  dispatch,
  model,
  onPickSample,
  onPickUpload,
  onSubmitGoal,
  onRun,
  onStop,
  onOpenHistory,
  onOpenDataset,
  onOpenTask,
}: ConversationProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [composer, setComposer] = useState(defaultGoal)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [state.step, state.progress.length, state.parsing.length, state.report])

  // 数据出域提示：model 状态由 AppShell 统一拉取后下传
  const modelConfigured = model?.status === 'configured' && Boolean(model.model)
  const egressTarget = modelConfigured ? `你配置的模型 ${model?.model}` : '你配置的模型'

  const dataset = state.dataset
  const sourceName = dataset?.data_source_ref.name ?? ''

  if (state.mode === 'tasks') {
    return <TaskLibrary state={state} onOpenTask={onOpenTask} />
  }

  if (state.mode === 'history') {
    return <HistoryLibrary state={state} onOpenHistory={onOpenHistory} />
  }

  if (state.mode === 'dataset') {
    return <DatasetLibrary state={state} onOpenDataset={onOpenDataset} />
  }

  function submit() {
    if (!dataset) {
      onPickSample()
      return
    }
    onSubmitGoal(composer)
  }

  return (
    <section className="conv">
      <div className="conv-hd">
        <div>
          <div className="title">{state.task?.task_title ?? '周度零售经营复盘'}</div>
          <div className="sub">
            {dataset ? (
              <>
                已连接 · <span className="mono">{sourceName}</span> ·{' '}
                {dataset.row_count.toLocaleString('zh-CN')} 行
              </>
            ) : (
              '还没有连接数据源'
            )}
          </div>
        </div>
        <div className="actions">
          <button className="btn subtle" onClick={() => dispatch({ type: 'RESET' })}>
            <Ico.Loop size={12} /> 重置
          </button>
        </div>
      </div>

      <div className="conv-scroll" ref={scrollRef}>
        <AgentMsg plain>
          <div style={{ padding: '2px 0 4px', color: 'var(--ink-2)', fontSize: 13, marginBottom: state.step === 'empty' ? 12 : 0 }}>
            👋 我是 Data Insight Agent。我会自己取数、逐步分析、出图，每个结论都附带可核对的 SQL 与数据来源。
          </div>
          {state.step === 'empty' && (
            <HeroBlock onPickSample={onPickSample} onPickUpload={onPickUpload} />
          )}
        </AgentMsg>

        {dataset && (
          <>
            <UserMsg>
              <div className="hstack" style={{ gap: 6 }}>
                <Ico.Database size={12} />
                <span>{sourceName}</span>
              </div>
            </UserMsg>
            <AgentMsg>
              <p>
                已载入 <b>{sourceName}</b>。
              </p>
              <p style={{ color: 'var(--ink-2)' }}>
                共 {dataset.row_count.toLocaleString('zh-CN')} 行、{dataset.column_count} 个字段，
                {dataset.field_profile.is_valid ? '已完成字段映射' : '部分字段待确认'}
                ——你可以在右边核对识别结果。接下来直接告诉我想看什么，比如：
              </p>
              <div className="suggest-row">
                {SUGGESTED_QUESTIONS.map((q, i) => (
                  <button
                    key={i}
                    className="suggest-chip"
                    disabled={state.busy === 'parse' || state.busy === 'report'}
                    onClick={() => onSubmitGoal(q)}
                  >
                    <Ico.Sparkle size={10} /> {q}
                  </button>
                ))}
              </div>
            </AgentMsg>
          </>
        )}

        {state.userGoal && <UserMsg>{state.userGoal}</UserMsg>}

        {state.parsing.length > 0 && (
          <AgentMsg>
            <div style={{ fontSize: 12.5, color: 'var(--ink-3)', marginBottom: 8 }}>
              {state.step === 'task_ready' ? '✓ 解析完成' : '正在解析任务…'}
            </div>
            <GenProgress progress={state.parsing} />
            {state.step === 'task_ready' &&
              state.parseWarnings.map((w) => (
                <div className="warn-line" key={w.code}>
                  <Ico.Warn size={12} /> {w.message}
                </div>
              ))}
          </AgentMsg>
        )}

        {state.task && state.step === 'task_ready' && (
          <AgentMsg>
            <p style={{ color: 'var(--ink-2)' }}>
              已理解成下面这个分析任务，指标、维度、对比方式都能直接点选编辑，也可在右侧核对：
            </p>
            <TaskCard state={state} dispatch={dispatch} onRun={onRun} />
          </AgentMsg>
        )}

        {state.step === 'generating' && state.task && (
          <>
            <UserMsg>
              <Ico.Sparkle size={12} /> 确认任务，开始生成
            </UserMsg>
            <AgentMsg>
              <div style={{ fontSize: 12.5, color: 'var(--ink-3)', marginBottom: 8 }}>
                正在<b style={{ color: 'var(--ink-1)' }}>自动取数、逐步分析并出图</b>，每个结论都会记录 SQL 依据…
              </div>
              <GenProgress progress={state.progress} />
            </AgentMsg>
          </>
        )}

        {state.step === 'report' && state.report && (
          <AgentMsg>
            <p>
              报告完成 · 共 <b>{state.report.findings.length} 项洞察</b>。
            </p>
            <p style={{ color: 'var(--ink-2)' }}>{state.report.summary}</p>
            {state.report.status === 'partial' && (
              <div className="warn-line">
                <Ico.Warn size={12} /> 预算触顶，已返回部分报告。
              </div>
            )}
            {state.report.warnings.map((w) => (
              <div className="warn-line" key={w.code}>
                <Ico.Warn size={12} /> {w.message}
              </div>
            ))}
            {state.tasks.length > 0 && !state.currentReportTaskId && (
              <button className="task-reuse-hint" onClick={() => dispatch({ type: 'NAV_TASKS' })}>
                <Ico.Template size={13} />
                <span>
                  如果这是某个已保存任务的下期数据，请到任务详情上传重跑，以获得上期对比。
                </span>
                <Ico.Caret size={10} />
              </button>
            )}
          </AgentMsg>
        )}
      </div>

      <div className="composer-wrap">
        {state.step === 'generating' ? (
          <div className="gen-bar">
            <span className="gen-bar-status">
              <Ico.Loop size={13} /> 正在生成报告 · 已用 {state.elapsed || '0.0'}s
            </span>
            <button className="btn danger sm" onClick={onStop}>
              <Ico.X size={11} /> 停止
            </button>
          </div>
        ) : (
          <>
            {state.step === 'task_ready' && (
              <div className="composer-hint">
                想换个分析方向？在下方重新提问会生成一份新的分析任务，替换上面的任务卡。
              </div>
            )}
            <div className="composer">
              <textarea
                value={composer}
                onChange={(e) => setComposer(e.target.value)}
                rows={3}
                placeholder={
                  !dataset
                    ? '先选择数据源，再开始提问'
                    : state.step === 'task_ready'
                      ? '换个问题重新提问，会重新生成分析任务…'
                      : '提个分析需求，或回复 Agent…'
                }
              />
              <div className="composer-row">
                <div className="pills">
                  {dataset ? (
                    <span className="attach-pill">
                      <Ico.Database size={11} /> {sourceName}
                      <button className="x" onClick={() => dispatch({ type: 'RESET' })}>
                        <Ico.X size={8} />
                      </button>
                    </span>
                  ) : (
                    <button className="suggest-chip" onClick={onPickUpload}>
                      <Ico.Plus size={10} /> 附加数据源
                    </button>
                  )}
                </div>
                <div className="right">
                  <span className="kbd">⏎</span>
                  <button
                    className="btn primary sm"
                    onClick={submit}
                    disabled={state.busy === 'parse' || state.busy === 'report'}
                  >
                    <Ico.Send size={12} /> {state.step === 'task_ready' ? '重新解析' : '发送'}
                  </button>
                </div>
              </div>
            </div>
            <p className="egress-note">
              本次分析会向{egressTarget}发送：数据结构、分析场景设定、聚合统计结果，以及分析过程中的提示与结论文本；
              <b>不会发送原始单行明细</b>。
              {model?.status === 'not_configured' && '（当前尚未配置模型）'}
            </p>
          </>
        )}
      </div>
    </section>
  )
}
