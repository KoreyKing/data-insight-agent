// Top-level orchestrator: three-column shell + state machine wired to real backend API.
// Generation uses simulated progress animation backfilled with real analysis_steps.
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import {
  asApiError,
  fetchDataset,
  fetchDatasets,
  fetchModelStatus,
  fetchReportDetail,
  fetchReports,
  fetchTaskDetail,
  fetchTasks,
  getContextPack,
  loadSample,
  parseTask,
  refreshUpload,
  renameTask,
  rerunTask,
  runReport,
  saveTask,
  selectSheet,
  uploadFile,
  type AnalysisTaskDetail,
  type AnalysisStep,
  type ContextPackState,
  type DatasetPayload,
  type ModelStatus,
} from './api/client'
import Sidebar from './components/Sidebar'
import Conversation from './components/Conversation'
import ArtifactPane from './components/ArtifactPane'
import ContextPackEditor from './components/ContextPackEditor'
import ModelConfigDialog from './components/ModelConfigDialog'
import { Ico } from './components/icons'
import { INITIAL, reducer, type ProgressStep } from './lib/state'
import { datasetDetailToPayload, reportDetailToView } from './lib/history'

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

function hasMatchingCanonicalFields(task: AnalysisTaskDetail, dataset: DatasetPayload): boolean {
  // UI hint only: the rerun endpoint's fingerprint comparison is authoritative (§2.3 v0.13).
  const expected = new Set(task.canonical_fields.map((field) => field.name))
  const actual = new Set(
    Object.values(dataset.field_profile.mappings ?? {})
      .map((mapping) => mapping.canonical_field?.trim())
      .filter((field): field is string => Boolean(field)),
  )
  return expected.size === actual.size && [...expected].every((field) => actual.has(field))
}

type Notice = { kind: 'success' | 'warning'; text: string }

export default function AppShell() {
  const [state, dispatch] = useReducer(reducer, INITIAL)
  const [model, setModel] = useState<ModelStatus | null>(null)
  const [modelConfigOpen, setModelConfigOpen] = useState(false)
  const [pack, setPack] = useState<ContextPackState | null>(null)
  const [packUnavailable, setPackUnavailable] = useState(false)
  const [packEditorOpen, setPackEditorOpen] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const taskFileRef = useRef<HTMLInputElement>(null)
  const timersRef = useRef<number[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const runSequenceRef = useRef(0)
  const parseSequenceRef = useRef(0)
  const currentDatasetSequenceRef = useRef(0)
  const taskDatasetSequenceRef = useRef(0)
  const taskListSequenceRef = useRef(0)
  const reportListSequenceRef = useRef(0)
  const datasetListSequenceRef = useRef(0)

  function clearTimers() {
    timersRef.current.forEach((id) => window.clearInterval(id))
    timersRef.current = []
  }

  function abortTaskRerunIfLeaving(nextTaskId?: string) {
    if (state.activeRunOrigin !== 'task-rerun') return
    if (nextTaskId && state.selectedTaskId === nextTaskId) return
    const controller = abortRef.current
    controller?.abort()
    if (abortRef.current === controller) abortRef.current = null
    clearTimers()
    dispatch({ type: 'STOP_TASK_RERUN' })
  }

  const refreshModelStatus = useCallback(async (retries = 2): Promise<void> => {
    // Retry model-status a couple times before giving up — a transient fetch failure
    // must not be reported as "not configured" (which would be misleading).
    let remaining = retries
    while (true) {
      try {
        setModel(await fetchModelStatus())
        return
      } catch {
        if (remaining <= 0) {
          setModel({ status: 'unknown' })
          return
        }
        remaining -= 1
        await new Promise((r) => window.setTimeout(r, 800))
      }
    }
  }, [])

  const refreshReports = useCallback(async (): Promise<void> => {
    const requestId = ++reportListSequenceRef.current
    dispatch({ type: 'HISTORY_LIST_LOADING' })
    try {
      const res = await fetchReports()
      if (requestId !== reportListSequenceRef.current) return
      dispatch({ type: 'HISTORY_LIST_LOADED', reports: res.items, total: res.total })
    } catch (err) {
      if (requestId !== reportListSequenceRef.current) return
      dispatch({ type: 'HISTORY_LIST_ERROR', error: asApiError(err) })
    }
  }, [])

  const refreshTasks = useCallback(async (): Promise<void> => {
    const requestId = ++taskListSequenceRef.current
    dispatch({ type: 'TASKS_LIST_LOADING' })
    try {
      const res = await fetchTasks()
      if (requestId !== taskListSequenceRef.current) return
      dispatch({ type: 'TASKS_LIST_LOADED', tasks: res.tasks })
    } catch (err) {
      if (requestId !== taskListSequenceRef.current) return
      dispatch({ type: 'TASKS_LIST_ERROR', error: asApiError(err) })
    }
  }, [])

  const refreshDatasets = useCallback(async (): Promise<void> => {
    const requestId = ++datasetListSequenceRef.current
    dispatch({ type: 'DATASETS_LIST_LOADING' })
    try {
      const res = await fetchDatasets()
      if (requestId !== datasetListSequenceRef.current) return
      dispatch({ type: 'DATASETS_LIST_LOADED', datasets: res.items, total: res.total })
    } catch (err) {
      if (requestId !== datasetListSequenceRef.current) return
      dispatch({ type: 'DATASETS_LIST_ERROR', error: asApiError(err) })
    }
  }, [])

  const refreshPack = useCallback(async (): Promise<void> => {
    try {
      setPack(await getContextPack())
      setPackUnavailable(false)
    } catch {
      setPackUnavailable(true)
    }
  }, [])

  const onPackChanged = useCallback((next: ContextPackState) => {
    setPack(next)
    setPackUnavailable(false)
    dispatch({ type: 'PACK_CHANGED' })
  }, [])

  useEffect(() => {
    void refreshModelStatus()
    void refreshPack()
    void refreshTasks()
    void refreshReports()
    void refreshDatasets()
    return clearTimers
  }, [refreshModelStatus, refreshPack, refreshTasks, refreshReports, refreshDatasets])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 8000)
    return () => window.clearTimeout(timer)
  }, [notice])

  async function onPickSample() {
    const requestId = ++currentDatasetSequenceRef.current
    parseSequenceRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    clearTimers()
    dispatch({ type: 'SET_BUSY', busy: 'dataset' })
    try {
      const dataset = await loadSample()
      if (requestId !== currentDatasetSequenceRef.current) return
      dispatch({ type: 'DATASET_LOADED', dataset })
    } catch (err) {
      if (requestId !== currentDatasetSequenceRef.current) return
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
    const requestId = ++currentDatasetSequenceRef.current
    parseSequenceRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    clearTimers()
    dispatch({ type: 'SET_BUSY', busy: 'dataset' })
    try {
      const dataset = await uploadFile(file)
      if (requestId !== currentDatasetSequenceRef.current) return
      dispatch({ type: 'DATASET_LOADED', dataset })
    } catch (err) {
      if (requestId !== currentDatasetSequenceRef.current) return
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
    }
  }

  async function onSelectSheet(sheet: string) {
    if (!state.dataset?.session_id) return
    const requestId = ++currentDatasetSequenceRef.current
    dispatch({ type: 'SET_BUSY', busy: 'dataset' })
    try {
      const dataset = await selectSheet(state.dataset.session_id, sheet)
      if (requestId !== currentDatasetSequenceRef.current) return
      dispatch({ type: 'DATASET_LOADED', dataset })
    } catch (err) {
      if (requestId !== currentDatasetSequenceRef.current) return
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
    }
  }

  async function onSubmitGoal(goal: string) {
    if (!state.dataset) return
    const requestId = ++parseSequenceRef.current
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
      if (requestId !== parseSequenceRef.current) return
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
      if (requestId !== parseSequenceRef.current) return
      clearTimers()
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
      dispatch({ type: 'ABORT_TASK' })
    }
  }

  function startGenerationProgress(existing?: AbortController): AbortController {
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

    const controller = existing ?? new AbortController()
    abortRef.current = controller
    return controller
  }

  async function onRun() {
    if (!state.dataset || !state.task) return
    const runId = `run-${++runSequenceRef.current}`
    dispatch({ type: 'RUN_REPORT', runId })
    dispatch({ type: 'SET_BUSY', busy: 'report' })
    const controller = startGenerationProgress()
    try {
      const res = await runReport(
        state.userGoal,
        state.dataset.data_source_ref,
        state.task,
        controller.signal,
      )
      clearTimers()
      const progress = stepsFromAnalysis(res.report.analysis_steps)
      dispatch({ type: 'REPORT_DONE', runId, reportId: res.report_id, report: res.report, progress })
      void refreshReports()
      void refreshDatasets()
    } catch (err) {
      clearTimers()
      // User-initiated abort is handled by onStop; don't surface it as an error.
      if (err instanceof DOMException && err.name === 'AbortError') return
      dispatch({ type: 'SET_ERROR', error: asApiError(err) })
      dispatch({ type: 'ABORT_TASK' })
    } finally {
      if (abortRef.current === controller) abortRef.current = null
    }
  }

  function onStop() {
    const controller = abortRef.current
    controller?.abort()
    if (abortRef.current === controller) abortRef.current = null
    clearTimers()
    dispatch({
      type:
        state.busy === 'task-rerun' || state.busy === 'task-rerun-check'
          ? 'STOP_TASK_RERUN'
          : 'STOP_GEN',
    })
  }

  function onNewSession() {
    abortRef.current?.abort()
    abortRef.current = null
    parseSequenceRef.current += 1
    currentDatasetSequenceRef.current += 1
    taskDatasetSequenceRef.current += 1
    clearTimers()
    dispatch({ type: 'RESET' })
  }

  function onSelectCurrent() {
    abortTaskRerunIfLeaving()
    dispatch({ type: 'NAV_CURRENT' })
  }

  function onSelectTasks() {
    currentDatasetSequenceRef.current += 1
    dispatch({ type: 'NAV_TASKS' })
    if (!state.tasksLoading) void refreshTasks()
    if (state.selectedTaskId) void onOpenTask(state.selectedTaskId)
  }

  function onSelectHistory() {
    abortTaskRerunIfLeaving()
    currentDatasetSequenceRef.current += 1
    dispatch({ type: 'NAV_HISTORY' })
    if (state.historyReports.length === 0 && !state.historyLoading) void refreshReports()
  }

  function onSelectDatasets() {
    abortTaskRerunIfLeaving()
    currentDatasetSequenceRef.current += 1
    dispatch({ type: 'NAV_DATASETS' })
    if (state.datasets.length === 0 && !state.datasetsLoading) void refreshDatasets()
  }

  async function onOpenTask(taskId: string) {
    if (state.activeRunOrigin === 'task-rerun' && state.selectedTaskId === taskId) return
    abortTaskRerunIfLeaving(taskId)
    currentDatasetSequenceRef.current += 1
    taskDatasetSequenceRef.current += 1
    dispatch({ type: 'TASK_DETAIL_LOADING', taskId })
    try {
      const detail = await fetchTaskDetail(taskId)
      dispatch({ type: 'TASK_DETAIL_LOADED', detail })
    } catch (err) {
      dispatch({ type: 'TASK_DETAIL_ERROR', taskId, error: asApiError(err) })
    }
  }

  async function onSaveTask(reportId: string, title: string): Promise<void> {
    const task = await saveTask(reportId, title)
    dispatch({ type: 'REPORT_TASK_LINKED', reportId, task })
    const duplicate = task.warnings?.[0]
    setNotice(
      duplicate
        ? {
            kind: 'warning',
            text: `已保存。已存在结构相同的任务「${duplicate.task_title}」，如属同一周期任务建议在该任务下重跑。`,
          }
        : { kind: 'success', text: `已保存为任务「${task.title}」。` },
    )
  }

  async function onRenameTask(taskId: string, title: string): Promise<void> {
    dispatch({ type: 'SET_BUSY', busy: 'task-rename' })
    try {
      const detail = await renameTask(taskId, title)
      dispatch({ type: 'TASK_RENAMED', detail })
      setNotice({ kind: 'success', text: `任务已改名为「${detail.title}」。` })
    } finally {
      dispatch({ type: 'SET_BUSY', busy: null })
    }
  }

  function onPickTaskUpload() {
    taskFileRef.current?.click()
  }

  async function onTaskFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    const requestId = ++taskDatasetSequenceRef.current
    dispatch({ type: 'TASK_RERUN_UPLOAD_START' })
    try {
      const dataset = await uploadFile(file)
      if (requestId !== taskDatasetSequenceRef.current) return
      dispatch({ type: 'TASK_RERUN_DATASET_LOADED', dataset })
    } catch (err) {
      if (requestId !== taskDatasetSequenceRef.current) return
      dispatch({ type: 'TASK_RERUN_ERROR', error: asApiError(err) })
    }
  }

  async function onSelectTaskSheet(sheet: string) {
    if (!state.taskRerunDataset?.session_id) return
    const requestId = ++taskDatasetSequenceRef.current
    dispatch({ type: 'SET_BUSY', busy: 'task-upload' })
    try {
      const dataset = await selectSheet(state.taskRerunDataset.session_id, sheet)
      if (requestId !== taskDatasetSequenceRef.current) return
      dispatch({ type: 'TASK_RERUN_DATASET_LOADED', dataset })
    } catch (err) {
      if (requestId !== taskDatasetSequenceRef.current) return
      dispatch({ type: 'TASK_RERUN_ERROR', error: asApiError(err) })
    }
  }

  async function onConfirmTaskRerun() {
    const task = state.taskDetail
    const dataset = state.taskRerunDataset
    if (!task || !dataset) return

    // 先停在「核对中」：口径可能在上传后被编辑，按当前活动口径刷新识别后再决定是否进入
    // 生成进度；不一致时照常请求，由服务端权威比对返回 SCHEMA_MISMATCH（§2.3 v0.13）。
    // 新的重跑取代仍在进行的上一次重跑，保证同一时刻只有一个重跑请求在途。
    if (state.activeRunOrigin === 'task-rerun') {
      abortRef.current?.abort()
      clearTimers()
    }
    const runId = `run-${++runSequenceRef.current}`
    dispatch({ type: 'TASK_RERUN_CHECK_START', runId, taskId: task.id })
    const controller = new AbortController()
    abortRef.current = controller

    try {
      let current = dataset
      if (dataset.session_id) {
        current = await refreshUpload(dataset.session_id, dataset.selected_sheet, controller.signal)
        if (controller.signal.aborted || abortRef.current !== controller) return
        dispatch({ type: 'TASK_RERUN_DATASET_REFRESHED', runId, dataset: current })
      }
      if (hasMatchingCanonicalFields(task, current)) {
        dispatch({ type: 'TASK_RERUN_GENERATING', runId })
        startGenerationProgress(controller)
      }
      const res = await rerunTask(task.id, current.data_source_ref, controller.signal)
      clearTimers()
      dispatch({
        type: 'REPORT_DONE',
        runId,
        reportId: res.report_id,
        report: res.report,
        progress: stepsFromAnalysis(res.report.analysis_steps),
        linkedTask: { id: task.id, title: task.title },
      })
      void refreshTasks()
      void refreshReports()
      void refreshDatasets()
    } catch (err) {
      clearTimers()
      if (err instanceof DOMException && err.name === 'AbortError') return
      dispatch({ type: 'TASK_RERUN_ERROR', runId, error: asApiError(err) })
    } finally {
      if (abortRef.current === controller) abortRef.current = null
    }
  }

  async function onOpenHistory(reportId: string) {
    abortTaskRerunIfLeaving()
    currentDatasetSequenceRef.current += 1
    clearTimers()
    dispatch({ type: 'HISTORY_DETAIL_LOADING', reportId })
    try {
      const detail = await fetchReportDetail(reportId)
      const datasetDetail = await fetchDataset(detail.dataset_id)
      const view = reportDetailToView(detail, datasetDetail)
      dispatch({
        type: 'HISTORY_DETAIL_LOADED',
        detail,
        dataset: view.dataset,
        task: view.task,
        report: view.report,
        progress: stepsFromAnalysis(view.report.analysis_steps),
        userGoal: view.userGoal,
      })
    } catch (err) {
      dispatch({ type: 'HISTORY_DETAIL_ERROR', reportId, error: asApiError(err) })
    }
  }

  async function onOpenDataset(datasetId: string) {
    abortTaskRerunIfLeaving()
    currentDatasetSequenceRef.current += 1
    clearTimers()
    dispatch({ type: 'DATASET_DETAIL_LOADING', datasetId })
    try {
      const detail = await fetchDataset(datasetId)
      dispatch({
        type: 'DATASET_DETAIL_LOADED',
        detail,
        dataset: datasetDetailToPayload(detail),
      })
    } catch (err) {
      dispatch({ type: 'DATASET_DETAIL_ERROR', datasetId, error: asApiError(err) })
    }
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
      <input
        ref={taskFileRef}
        type="file"
        accept=".csv,.xlsx"
        style={{ display: 'none' }}
        onChange={onTaskFileChange}
      />
      <Sidebar
        model={model}
        onNewSession={onNewSession}
        onSelectCurrent={onSelectCurrent}
        onSelectTasks={onSelectTasks}
        onSelectHistory={onSelectHistory}
        onSelectDatasets={onSelectDatasets}
        onOpenHistory={onOpenHistory}
        hasSession={Boolean(state.dataset)}
        activeMode={state.mode}
        tasksTotal={state.tasks.length}
        tasksLoading={state.tasksLoading}
        historyReports={state.historyReports}
        historyTotal={state.historyTotal}
        historyLoading={state.historyLoading}
        selectedHistoryId={state.selectedHistoryId}
        datasetsTotal={state.datasetsTotal}
        datasetsLoading={state.datasetsLoading}
        onOpenModelConfig={() => setModelConfigOpen(true)}
        pack={pack}
        packUnavailable={packUnavailable}
        onOpenContextPack={() => setPackEditorOpen(true)}
      />
      <Conversation
        state={state}
        dispatch={dispatch}
        model={model}
        onPickSample={onPickSample}
        onPickUpload={onPickUpload}
        onSubmitGoal={onSubmitGoal}
        onRun={onRun}
        onStop={onStop}
        onOpenHistory={onOpenHistory}
        onOpenDataset={onOpenDataset}
        onOpenTask={onOpenTask}
      />
      <ArtifactPane
        state={state}
        dispatch={dispatch}
        onSelectSheet={onSelectSheet}
        onPickSample={onPickSample}
        onPickUpload={onPickUpload}
        onOpenHistory={onOpenHistory}
        onOpenTask={onOpenTask}
        onSaveTask={onSaveTask}
        onRenameTask={onRenameTask}
        onPickTaskUpload={onPickTaskUpload}
        onSelectTaskSheet={onSelectTaskSheet}
        onConfirmTaskRerun={onConfirmTaskRerun}
        onStopTaskRerun={onStop}
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
      {notice && (
        <div className={`notice-band ${notice.kind}`} role="status">
          {notice.kind === 'success' ? <Ico.Check size={14} /> : <Ico.Warn size={14} />}
          <span>{notice.text}</span>
          <button className="x" onClick={() => setNotice(null)} aria-label="关闭提示">
            <Ico.X size={10} />
          </button>
        </div>
      )}
      <ModelConfigDialog
        open={modelConfigOpen}
        onClose={() => setModelConfigOpen(false)}
        onSaved={() => refreshModelStatus(0)}
      />
      {packEditorOpen && (
        <ContextPackEditor onClose={() => setPackEditorOpen(false)} onChanged={onPackChanged} />
      )}
    </div>
  )
}
