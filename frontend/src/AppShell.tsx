// Top-level orchestrator: three-column shell + state machine wired to real backend API.
// Generation uses simulated progress animation backfilled with real analysis_steps.
import { useEffect, useReducer, useRef, useState } from 'react'
import {
  asApiError,
  fetchModelStatus,
  loadSample,
  parseTask,
  runReport,
  selectSheet,
  uploadFile,
  type AnalysisStep,
  type ModelStatus,
} from './api/client'
import Sidebar from './components/Sidebar'
import Conversation from './components/Conversation'
import ArtifactPane from './components/ArtifactPane'
import { Ico } from './components/icons'
import { INITIAL, reducer, type ProgressStep } from './lib/state'

// Simulated parse steps shown while POST /tasks/parse is in flight.
const PARSE_STEPS = ['理解分析目标', '匹配分析场景与指标定义', '识别维度与对比方式', '生成结构化任务']

// Simulated generation steps shown while POST /reports/run is in flight.
const GEN_STEPS: { label: string; detail: string }[] = [
  { label: '规划分析路径', detail: '拆解指标与维度，确定取数顺序' },
  { label: '执行取数查询', detail: '生成并校验 SQL，拉取结果集' },
  { label: '逐步下钻异常', detail: '对偏离基线的维度继续下钻' },
  { label: '生成图表与结论', detail: '为关键发现配图并记录依据' },
  { label: '组装可追溯报告', detail: '汇总 KPI、洞察与证据链' },
]

const TOOL_LABEL: Record<string, string> = {
  run_sql: '执行 SQL 取数',
  execute_sql: '执行 SQL 取数',
  query: '执行 SQL 取数',
  build_echarts_spec: '生成图表',
  create_chart: '生成图表',
  record_finding: '记录洞察',
  python: '运行分析脚本',
  run_python: '运行分析脚本',
  finish: '组装报告',
}

function toolLabel(tool: string): string {
  return TOOL_LABEL[tool] ?? tool
}

// Backfill: real analysis_steps → progress timeline (all done). Fallback to GEN_STEPS done.
function stepsFromAnalysis(steps: AnalysisStep[] | undefined): ProgressStep[] {
  if (!steps || steps.length === 0) {
    return GEN_STEPS.map((s) => ({ state: 'done' as const, label: s.label, detail: s.detail }))
  }
  return steps.map((s) => ({
    state: 'done' as const,
    label: `第 ${s.iteration} 步 · ${toolLabel(s.tool)}`,
    detail: s.summary || s.sql || s.code || undefined,
  }))
}

export default function AppShell() {
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const [model, setModel] = useState<ModelStatus | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const timersRef = useRef<number[]>([])
  const abortRef = useRef<AbortController | null>(null)

  function clearTimers() {
    timersRef.current.forEach((id) => window.clearInterval(id))
    timersRef.current = []
  }

  useEffect(() => {
    // Retry model-status a couple times before giving up — a transient fetch failure
    // must not be reported as "not configured" (which would be misleading).
    const loadModel = async (retries = 2): Promise<void> => {
      try {
        setModel(await fetchModelStatus())
      } catch {
        if (retries > 0) {
          await new Promise((r) => window.setTimeout(r, 800))
          return loadModel(retries - 1)
        }
        setModel({ status: 'unknown' })
      }
    }
    void loadModel()
    return clearTimers
  }, [])

  async function onPickSample() {
    clearTimers()
    dispatch({ type: 'SET_BUSY', busy: 'dataset' })
    try {
      const dataset = await loadSample()
      dispatch({ type: 'DATASET_LOADED', dataset })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
    }
  }

  function onPickUpload() {
    fileRef.current?.click()
  }

  async function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting same file
    if (!file) return
    clearTimers()
    dispatch({ type: 'SET_BUSY', busy: 'dataset' })
    try {
      const dataset = await uploadFile(file)
      dispatch({ type: 'DATASET_LOADED', dataset })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
    }
  }

  async function onSelectSheet(sheet: string) {
    if (!state.dataset?.session_id) return
    dispatch({ type: 'SET_BUSY', busy: 'dataset' })
    try {
      const dataset = await selectSheet(state.dataset.session_id, sheet)
      dispatch({ type: 'DATASET_LOADED', dataset })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
    }
  }

  async function onSubmitGoal(goal: string) {
    if (!state.dataset) return
    dispatch({ type: 'SUBMIT_GOAL', goal })
    dispatch({ type: 'SET_BUSY', busy: 'parse' })

    // Simulated parse progress while the real call is in flight.
    let idx = 0
    const seed: ProgressStep[] = PARSE_STEPS.map((label, i) => ({
      state: i === 0 ? 'active' : 'pending',
      label,
    }))
    dispatch({ type: 'PARSE_PROGRESS', parsing: seed })
    const timer = window.setInterval(() => {
      idx = Math.min(idx + 1, PARSE_STEPS.length - 1)
      const next: ProgressStep[] = PARSE_STEPS.map((label, i) => ({
        state: i < idx ? 'done' : i === idx ? 'active' : 'pending',
        label,
      }))
      dispatch({ type: 'PARSE_PROGRESS', parsing: next })
    }, 600)
    timersRef.current.push(timer)

    try {
      const res = await parseTask(goal, state.dataset.data_source_ref)
      clearTimers()
      const done: ProgressStep[] = PARSE_STEPS.map((label) => ({ state: 'done', label }))
      dispatch({
        type: 'TASK_READY',
        task: res.task,
        warnings: res.warnings ?? [],
        parsing: done,
        dimensionOptions: res.dimension_options ?? [],
      })
    } catch (err) {
      clearTimers()
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
      dispatch({ type: 'ABORT_TASK' })
    }
  }

  async function onRun() {
    if (!state.dataset || !state.task) return
    dispatch({ type: 'RUN_REPORT' })
    dispatch({ type: 'SET_BUSY', busy: 'report' })

    // Simulated progress: step through GEN_STEPS once, then enter an honest
    // "still analysing" waiting state until the real (blocking) call returns.
    // No fake iteration cap or token climb — long real runs must not look frozen.
    let stepIdx = 0
    const start = Date.now()
    const seed: ProgressStep[] = GEN_STEPS.map((s, i) => ({
      state: i === 0 ? 'active' : 'pending',
      label: s.label,
      detail: s.detail,
    }))
    dispatch({ type: 'GEN_PROGRESS', progress: seed, iter: 1 })

    const stepTimer = window.setInterval(() => {
      stepIdx += 1
      if (stepIdx < GEN_STEPS.length) {
        const next: ProgressStep[] = GEN_STEPS.map((s, i) => ({
          state: i < stepIdx ? 'done' : i === stepIdx ? 'active' : 'pending',
          label: s.label,
          detail: s.detail,
        }))
        dispatch({ type: 'GEN_PROGRESS', progress: next, iter: stepIdx + 1 })
      } else {
        // All simulated steps shown — switch to indeterminate waiting.
        const done: ProgressStep[] = GEN_STEPS.map((s) => ({
          state: 'done',
          label: s.label,
          detail: s.detail,
        }))
        dispatch({ type: 'GEN_PROGRESS', progress: done, waiting: true })
        window.clearInterval(stepTimer)
      }
    }, 900)
    timersRef.current.push(stepTimer)

    const tickTimer = window.setInterval(() => {
      dispatch({ type: 'GEN_TICK', elapsed: ((Date.now() - start) / 1000).toFixed(1) })
    }, 1000)
    timersRef.current.push(tickTimer)

    const controller = new AbortController()
    abortRef.current = controller
    try {
      const res = await runReport(
        state.userGoal,
        state.dataset.data_source_ref,
        state.task,
        controller.signal,
      )
      clearTimers()
      const progress = stepsFromAnalysis(res.report.analysis_steps)
      dispatch({ type: 'REPORT_DONE', report: res.report, progress })
    } catch (err) {
      clearTimers()
      // User-initiated abort is handled by onStop; don't surface it as an error.
      if (err instanceof DOMException && err.name === 'AbortError') return
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
      dispatch({ type: 'ABORT_TASK' })
    } finally {
      abortRef.current = null
    }
  }

  function onStop() {
    abortRef.current?.abort()
    clearTimers()
    dispatch({ type: 'STOP_GEN' })
  }

  function onNewSession() {
    clearTimers()
    dispatch({ type: 'RESET' })
  }

  return (
    <div className="app" data-tone="forest">
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx"
        style={{ display: 'none' }}
        onChange={onFileChange}
      />
      <Sidebar model={model} onNewSession={onNewSession} hasSession={Boolean(state.dataset)} />
      <Conversation
        state={state}
        dispatch={dispatch}
        model={model}
        onPickSample={onPickSample}
        onPickUpload={onPickUpload}
        onSubmitGoal={onSubmitGoal}
        onRun={onRun}
        onStop={onStop}
      />
      <ArtifactPane
        state={state}
        dispatch={dispatch}
        onSelectSheet={onSelectSheet}
        onPickSample={onPickSample}
        onPickUpload={onPickUpload}
      />
      {state.error && (
        <div className="error-band">
          <Ico.Warn size={14} />
          <span>
            <b>{state.error.code}</b> · {state.error.message}
          </span>
          <button className="x" onClick={() => dispatch({ type: 'SET_ERROR', error: null })}>
            <Ico.X size={10} />
          </button>
        </div>
      )}
    </div>
  )
}
