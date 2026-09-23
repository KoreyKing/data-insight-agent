// App state machine: empty → dataset → parsing → task_ready → generating → report.
import type {
  AnalysisTaskDetail,
  AnalysisTaskListItem,
  ApiError,
  ApiWarning,
  DatasetPayload,
  DimensionOption,
  HistoryDatasetDetail,
  HistoryDatasetListItem,
  HistoryReportDetail,
  HistoryReportListItem,
  ReportPayload,
  StructuredTask,
} from '../api/client'

export type Step = 'empty' | 'dataset' | 'parsing' | 'task_ready' | 'generating' | 'report'

export type ArtifactTab = 'report' | 'dataset' | 'task' | 'trace'

export type AppMode = 'current' | 'tasks' | 'history' | 'dataset'

export type ProgressStep = {
  state: 'pending' | 'active' | 'done'
  label: string
  detail?: string
  time?: string
}

export type AppState = {
  mode: AppMode
  step: Step
  dataset: DatasetPayload | null
  userGoal: string
  parsing: ProgressStep[]
  parseWarnings: ApiWarning[]
  task: StructuredTask | null
  dimensionOptions: DimensionOption[]
  compare: string
  progress: ProgressStep[]
  iter: number
  tokensUsed: number
  elapsed: string
  report: ReportPayload | null
  currentReportId: string | null
  currentReportTaskId: string | null
  currentReportTaskTitle: string | null
  artifactTab: ArtifactTab
  error: ApiError | null
  busy: string | null
  chartErrors: string[]
  genWaiting: boolean
  activeRunId: string | null
  activeRunOrigin: 'current' | 'task-rerun' | null
  activeRunTaskId: string | null
  historyReports: HistoryReportListItem[]
  historyTotal: number
  historyLoading: boolean
  historyError: ApiError | null
  selectedHistoryId: string | null
  historyDetailLoading: boolean
  historyDetail: HistoryReportDetail | null
  historyDataset: DatasetPayload | null
  historyTask: StructuredTask | null
  historyReport: ReportPayload | null
  historyProgress: ProgressStep[]
  historyUserGoal: string
  tasks: AnalysisTaskListItem[]
  tasksLoading: boolean
  tasksError: ApiError | null
  selectedTaskId: string | null
  taskDetailLoading: boolean
  taskDetail: AnalysisTaskDetail | null
  taskRerunDataset: DatasetPayload | null
  taskRerunError: ApiError | null
  datasets: HistoryDatasetListItem[]
  datasetsTotal: number
  datasetsLoading: boolean
  datasetsError: ApiError | null
  selectedDatasetId: string | null
  datasetDetailLoading: boolean
  datasetDetail: HistoryDatasetDetail | null
  datasetPreview: DatasetPayload | null
}

export const INITIAL: AppState = {
  mode: 'current',
  step: 'empty',
  dataset: null,
  userGoal: '',
  parsing: [],
  parseWarnings: [],
  task: null,
  dimensionOptions: [],
  compare: '环比',
  progress: [],
  iter: 0,
  tokensUsed: 0,
  elapsed: '0.0',
  report: null,
  currentReportId: null,
  currentReportTaskId: null,
  currentReportTaskTitle: null,
  artifactTab: 'report',
  error: null,
  busy: null,
  chartErrors: [],
  genWaiting: false,
  activeRunId: null,
  activeRunOrigin: null,
  activeRunTaskId: null,
  historyReports: [],
  historyTotal: 0,
  historyLoading: false,
  historyError: null,
  selectedHistoryId: null,
  historyDetailLoading: false,
  historyDetail: null,
  historyDataset: null,
  historyTask: null,
  historyReport: null,
  historyProgress: [],
  historyUserGoal: '',
  tasks: [],
  tasksLoading: false,
  tasksError: null,
  selectedTaskId: null,
  taskDetailLoading: false,
  taskDetail: null,
  taskRerunDataset: null,
  taskRerunError: null,
  datasets: [],
  datasetsTotal: 0,
  datasetsLoading: false,
  datasetsError: null,
  selectedDatasetId: null,
  datasetDetailLoading: false,
  datasetDetail: null,
  datasetPreview: null,
}

export type Action =
  | { type: 'RESET' }
  | { type: 'NAV_CURRENT' }
  | { type: 'NAV_TASKS' }
  | { type: 'PACK_CHANGED' }
  | { type: 'NAV_HISTORY' }
  | { type: 'NAV_DATASETS' }
  | { type: 'SET_BUSY'; busy: string | null }
  | { type: 'SET_ERROR'; error: ApiError | null }
  | { type: 'DATASET_LOADED'; dataset: DatasetPayload }
  | { type: 'SUBMIT_GOAL'; goal: string }
  | { type: 'PARSE_PROGRESS'; parsing: ProgressStep[] }
  | {
      type: 'TASK_READY'
      task: StructuredTask
      warnings: ApiWarning[]
      parsing: ProgressStep[]
      dimensionOptions: DimensionOption[]
    }
  | { type: 'CHIP_REMOVE'; group: 'metrics' | 'dims'; index: number }
  | { type: 'ADD_DIM'; value: string }
  | { type: 'SET_COMPARE'; value: string }
  | { type: 'ABORT_TASK' }
  | { type: 'RUN_REPORT'; runId: string }
  | { type: 'STOP_GEN' }
  | { type: 'GEN_PROGRESS'; progress: ProgressStep[]; iter?: number; waiting?: boolean }
  | { type: 'GEN_TICK'; elapsed: string }
  | {
      type: 'REPORT_DONE'
      runId: string
      reportId: string
      report: ReportPayload
      progress: ProgressStep[]
      linkedTask?: { id: string; title: string } | null
    }
  | { type: 'REPORT_TASK_LINKED'; reportId: string; task: AnalysisTaskDetail }
  | { type: 'TAB'; tab: ArtifactTab }
  | { type: 'CHART_ERROR'; title: string }
  | { type: 'HISTORY_LIST_LOADING' }
  | {
      type: 'HISTORY_LIST_LOADED'
      reports: HistoryReportListItem[]
      total: number
    }
  | { type: 'HISTORY_LIST_ERROR'; error: ApiError }
  | { type: 'DATASETS_LIST_LOADING' }
  | {
      type: 'DATASETS_LIST_LOADED'
      datasets: HistoryDatasetListItem[]
      total: number
    }
  | { type: 'DATASETS_LIST_ERROR'; error: ApiError }
  | { type: 'HISTORY_DETAIL_LOADING'; reportId: string }
  | {
      type: 'HISTORY_DETAIL_LOADED'
      detail: HistoryReportDetail
      dataset: DatasetPayload
      task: StructuredTask
      report: ReportPayload
      progress: ProgressStep[]
      userGoal: string
    }
  | { type: 'HISTORY_DETAIL_ERROR'; reportId: string; error: ApiError }
  | { type: 'TASKS_LIST_LOADING' }
  | { type: 'TASKS_LIST_LOADED'; tasks: AnalysisTaskListItem[] }
  | { type: 'TASKS_LIST_ERROR'; error: ApiError }
  | { type: 'TASK_DETAIL_LOADING'; taskId: string }
  | { type: 'TASK_DETAIL_LOADED'; detail: AnalysisTaskDetail }
  | { type: 'TASK_DETAIL_ERROR'; taskId: string; error: ApiError }
  | { type: 'TASK_RENAMED'; detail: AnalysisTaskDetail }
  | { type: 'TASK_RERUN_UPLOAD_START' }
  | { type: 'TASK_RERUN_DATASET_LOADED'; dataset: DatasetPayload }
  | { type: 'TASK_RERUN_ERROR'; error: ApiError | null; runId?: string }
  | { type: 'TASK_RERUN_CHECK_START'; runId: string; taskId: string }
  | { type: 'TASK_RERUN_DATASET_REFRESHED'; runId: string; dataset: DatasetPayload }
  | { type: 'TASK_RERUN_GENERATING'; runId: string }
  | { type: 'STOP_TASK_RERUN' }
  | { type: 'DATASET_DETAIL_LOADING'; datasetId: string }
  | {
      type: 'DATASET_DETAIL_LOADED'
      detail: HistoryDatasetDetail
      dataset: DatasetPayload
    }
  | { type: 'DATASET_DETAIL_ERROR'; datasetId: string; error: ApiError }

function preservedLibrary(state: AppState): Partial<AppState> {
  return {
    historyReports: state.historyReports,
    historyTotal: state.historyTotal,
    historyLoading: state.historyLoading,
    historyError: state.historyError,
    selectedHistoryId: state.selectedHistoryId,
    historyDetailLoading: state.historyDetailLoading,
    historyDetail: state.historyDetail,
    historyDataset: state.historyDataset,
    historyTask: state.historyTask,
    historyReport: state.historyReport,
    historyProgress: state.historyProgress,
    historyUserGoal: state.historyUserGoal,
    tasks: state.tasks,
    tasksLoading: state.tasksLoading,
    tasksError: state.tasksError,
    selectedTaskId: state.selectedTaskId,
    taskDetailLoading: state.taskDetailLoading,
    taskDetail: state.taskDetail,
    taskRerunDataset: state.taskRerunDataset,
    taskRerunError: state.taskRerunError,
    datasets: state.datasets,
    datasetsTotal: state.datasetsTotal,
    datasetsLoading: state.datasetsLoading,
    datasetsError: state.datasetsError,
    selectedDatasetId: state.selectedDatasetId,
    datasetDetailLoading: state.datasetDetailLoading,
    datasetDetail: state.datasetDetail,
    datasetPreview: state.datasetPreview,
  }
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'RESET':
      return { ...INITIAL, ...preservedLibrary(state), mode: 'current' }
    case 'NAV_CURRENT':
      return { ...state, mode: 'current', busy: null, error: null }
    case 'NAV_TASKS':
      // 进行中的任务重跑保持核对 / 生成态，避免按钮重新可点而并发发起第二次重跑。
      return {
        ...state,
        mode: 'tasks',
        busy: state.activeRunOrigin === 'task-rerun' ? state.busy : null,
        error: null,
      }
    case 'PACK_CHANGED':
      // 口径已变：上一次「结构不一致」结论可能过期，允许直接重试（点击时会按新口径重新核对）。
      if (state.activeRunId || state.taskRerunError?.code !== 'SCHEMA_MISMATCH') return state
      return { ...state, taskRerunError: null }
    case 'NAV_HISTORY':
      return { ...state, mode: 'history', busy: null, error: null }
    case 'NAV_DATASETS':
      return { ...state, mode: 'dataset', busy: null, error: null }
    case 'SET_BUSY':
      return { ...state, busy: action.busy }
    case 'SET_ERROR':
      return { ...state, error: action.error, busy: null }
    case 'DATASET_LOADED':
      return {
        ...state,
        mode: 'current',
        step: 'dataset',
        dataset: action.dataset,
        task: null,
        report: null,
        currentReportId: null,
        currentReportTaskId: null,
        currentReportTaskTitle: null,
        userGoal: '',
        parsing: [],
        parseWarnings: [],
        error: null,
        busy: null,
        chartErrors: [],
        activeRunId: null,
        activeRunOrigin: null,
        activeRunTaskId: null,
        artifactTab: 'dataset',
      }
    case 'SUBMIT_GOAL':
      return {
        ...state,
        mode: 'current',
        userGoal: action.goal,
        step: 'parsing',
        parsing: [],
        report: null,
        currentReportId: null,
        currentReportTaskId: null,
        currentReportTaskTitle: null,
        error: null,
        activeRunId: null,
        activeRunOrigin: null,
        activeRunTaskId: null,
      }
    case 'PARSE_PROGRESS':
      return { ...state, parsing: action.parsing }
    case 'TASK_READY':
      return {
        ...state,
        step: 'task_ready',
        task: action.task,
        dimensionOptions: action.dimensionOptions,
        compare: action.task.comparison || '环比',
        parseWarnings: action.warnings,
        parsing: action.parsing,
        busy: null,
      }
    case 'CHIP_REMOVE': {
      if (!state.task) return state
      const task = { ...state.task }
      if (action.group === 'metrics') {
        task.metrics = task.metrics.filter((_, i) => i !== action.index)
      } else {
        task.dimensions = task.dimensions.filter((_, i) => i !== action.index)
      }
      return { ...state, task }
    }
    case 'ADD_DIM': {
      if (!state.task) return state
      if (state.task.dimensions.includes(action.value)) return state
      return {
        ...state,
        task: { ...state.task, dimensions: [...state.task.dimensions, action.value] },
      }
    }
    case 'SET_COMPARE':
      if (!state.task) return state
      return { ...state, compare: action.value, task: { ...state.task, comparison: action.value } }
    case 'ABORT_TASK':
      return {
        ...state,
        step: 'dataset',
        userGoal: '',
        task: null,
        parsing: [],
        parseWarnings: [],
        activeRunId: null,
        activeRunOrigin: null,
        activeRunTaskId: null,
      }
    case 'RUN_REPORT':
      return {
        ...state,
        mode: 'current',
        step: 'generating',
        progress: [],
        iter: 0,
        tokensUsed: 0,
        elapsed: '0.0',
        genWaiting: false,
        error: null,
        chartErrors: [],
        activeRunId: action.runId,
        activeRunOrigin: 'current',
        activeRunTaskId: null,
      }
    case 'STOP_GEN':
      // User aborted the in-flight run — return to the (kept) task for re-run.
      return {
        ...state,
        step: 'task_ready',
        progress: [],
        genWaiting: false,
        iter: 0,
        elapsed: '0.0',
        busy: null,
        activeRunId: null,
        activeRunOrigin: null,
        activeRunTaskId: null,
      }
    case 'GEN_PROGRESS':
      return {
        ...state,
        progress: action.progress.length ? action.progress : state.progress,
        iter: action.iter ?? state.iter,
        genWaiting: action.waiting ?? state.genWaiting,
      }
    case 'GEN_TICK':
      return { ...state, elapsed: action.elapsed }
    case 'REPORT_DONE': {
      if (state.activeRunId !== action.runId) return state
        if (
          state.activeRunOrigin === 'task-rerun' &&
          (state.mode !== 'tasks' || state.selectedTaskId !== state.activeRunTaskId)
        ) {
          return {
            ...state,
            busy: null,
            activeRunId: null,
            activeRunOrigin: null,
            activeRunTaskId: null,
          }
        }
        const rerunDataset = action.linkedTask ? state.taskRerunDataset : null
        const rerunTask =
          action.linkedTask && state.taskDetail && rerunDataset
            ? {
                ...state.taskDetail.structured_task,
                data_source_ref: rerunDataset.data_source_ref,
              }
            : null
        const shouldActivate =
          state.activeRunOrigin === 'current'
            ? state.mode === 'current'
            : state.activeRunOrigin === 'task-rerun'
              ? state.mode === 'tasks' && state.selectedTaskId === state.activeRunTaskId
              : false
        return {
        ...state,
        mode: shouldActivate ? 'current' : state.mode,
        step: 'report',
        dataset: rerunDataset ?? state.dataset,
        task: rerunTask ?? state.task,
        userGoal: rerunTask ? state.taskDetail?.analysis_goal ?? '' : state.userGoal,
        compare: rerunTask?.comparison || state.compare,
        report: action.report,
        currentReportId: action.reportId,
        currentReportTaskId: action.linkedTask?.id ?? null,
        currentReportTaskTitle: action.linkedTask?.title ?? null,
        progress: action.progress,
        genWaiting: false,
        artifactTab: 'report',
        busy: null,
        activeRunId: null,
        activeRunOrigin: null,
        activeRunTaskId: null,
        }
      }
    case 'REPORT_TASK_LINKED': {
      const task = action.task
      const nextTasks = [
        { ...task },
        ...state.tasks.filter((item) => item.id !== task.id),
      ]
      return {
        ...state,
        tasks: nextTasks,
        currentReportTaskId:
          state.currentReportId === action.reportId ? task.id : state.currentReportTaskId,
        currentReportTaskTitle:
          state.currentReportId === action.reportId ? task.title : state.currentReportTaskTitle,
        historyDetail:
          state.historyDetail?.id === action.reportId
            ? { ...state.historyDetail, task_id: task.id, task_title: task.title }
            : state.historyDetail,
        taskDetail: task,
        selectedTaskId: task.id,
      }
    }
    case 'TAB':
      return { ...state, artifactTab: action.tab }
    case 'CHART_ERROR':
      if (state.chartErrors.includes(action.title)) return state
      return { ...state, chartErrors: [...state.chartErrors, action.title] }
    case 'HISTORY_LIST_LOADING':
      return { ...state, historyLoading: true, historyError: null }
    case 'HISTORY_LIST_LOADED':
      return {
        ...state,
        historyReports: action.reports,
        historyTotal: action.total,
        historyLoading: false,
        historyError: null,
      }
    case 'HISTORY_LIST_ERROR':
      return { ...state, historyLoading: false, historyError: action.error }
    case 'DATASETS_LIST_LOADING':
      return { ...state, datasetsLoading: true, datasetsError: null }
    case 'DATASETS_LIST_LOADED':
      return {
        ...state,
        datasets: action.datasets,
        datasetsTotal: action.total,
        datasetsLoading: false,
        datasetsError: null,
      }
    case 'DATASETS_LIST_ERROR':
      return { ...state, datasetsLoading: false, datasetsError: action.error }
    case 'HISTORY_DETAIL_LOADING':
      return {
        ...state,
        mode: 'history',
        selectedHistoryId: action.reportId,
        historyDetailLoading: true,
        historyError: null,
        error: null,
        artifactTab: 'report',
      }
    case 'HISTORY_DETAIL_LOADED':
      if (state.mode !== 'history' || state.selectedHistoryId !== action.detail.id) return state
      return {
        ...state,
        mode: 'history',
        selectedHistoryId: action.detail.id,
        historyDetailLoading: false,
        historyDetail: action.detail,
        historyDataset: action.dataset,
        historyTask: action.task,
        historyReport: action.report,
        historyProgress: action.progress,
        historyUserGoal: action.userGoal,
        historyError: null,
        artifactTab: 'report',
      }
    case 'HISTORY_DETAIL_ERROR':
      if (state.mode !== 'history' || state.selectedHistoryId !== action.reportId) return state
      return {
        ...state,
        historyDetailLoading: false,
        historyError: action.error,
        error: action.error,
      }
    case 'TASKS_LIST_LOADING':
      return { ...state, tasksLoading: true, tasksError: null }
    case 'TASKS_LIST_LOADED':
      return { ...state, tasks: action.tasks, tasksLoading: false, tasksError: null }
    case 'TASKS_LIST_ERROR':
      return { ...state, tasksLoading: false, tasksError: action.error }
    case 'TASK_DETAIL_LOADING':
      return {
        ...state,
        mode: 'tasks',
        selectedTaskId: action.taskId,
        taskDetailLoading: true,
        tasksError: null,
        taskRerunDataset: null,
        taskRerunError: null,
        error: null,
      }
    case 'TASK_DETAIL_LOADED':
      if (state.mode !== 'tasks' || state.selectedTaskId !== action.detail.id) return state
      return {
        ...state,
        mode: 'tasks',
        selectedTaskId: action.detail.id,
        taskDetailLoading: false,
        taskDetail: action.detail,
        tasksError: null,
      }
    case 'TASK_DETAIL_ERROR':
      if (state.mode !== 'tasks' || state.selectedTaskId !== action.taskId) return state
      return {
        ...state,
        taskDetailLoading: false,
        tasksError: action.error,
        error: action.error,
      }
    case 'TASK_RENAMED':
      return {
        ...state,
        taskDetail: action.detail,
        tasks: state.tasks.map((task) =>
          task.id === action.detail.id ? { ...task, title: action.detail.title } : task,
        ),
        currentReportTaskTitle:
          state.currentReportTaskId === action.detail.id
            ? action.detail.title
            : state.currentReportTaskTitle,
        historyDetail:
          state.historyDetail?.task_id === action.detail.id
            ? { ...state.historyDetail, task_title: action.detail.title }
            : state.historyDetail,
      }
    case 'TASK_RERUN_UPLOAD_START':
      return {
        ...state,
        taskRerunDataset: null,
        taskRerunError: null,
        busy: 'task-upload',
      }
    case 'TASK_RERUN_DATASET_LOADED':
      return {
        ...state,
        taskRerunDataset: action.dataset,
        taskRerunError: null,
        busy: null,
      }
    case 'TASK_RERUN_ERROR':
      if (action.runId && state.activeRunId !== action.runId) return state
      return {
        ...state,
        taskRerunError: action.error,
        busy: null,
        activeRunId: null,
        activeRunOrigin: null,
        activeRunTaskId: null,
      }
    case 'TASK_RERUN_CHECK_START':
      return {
        ...state,
        taskRerunError: null,
        busy: 'task-rerun-check',
        activeRunId: action.runId,
        activeRunOrigin: 'task-rerun',
        activeRunTaskId: action.taskId,
      }
    case 'TASK_RERUN_DATASET_REFRESHED':
      // 点击重跑时按当前口径刷新的识别结果；仅对仍在进行的这次重跑生效。
      if (state.activeRunId !== action.runId) return state
      return { ...state, taskRerunDataset: action.dataset }
    case 'TASK_RERUN_GENERATING':
      // 刷新后的识别与任务一致才从「核对中」切到生成进度（§2.3 v0.13）。
      if (state.activeRunId !== action.runId || !state.taskDetail || !state.taskRerunDataset) {
        return state
      }
      return {
        ...state,
        progress: [],
        iter: 0,
        tokensUsed: 0,
        elapsed: '0.0',
        genWaiting: false,
        error: null,
        taskRerunError: null,
        busy: 'task-rerun',
        chartErrors: [],
        artifactTab: 'report',
      }
    case 'STOP_TASK_RERUN':
      return {
        ...state,
        progress: [],
        genWaiting: false,
        iter: 0,
        elapsed: '0.0',
        busy: null,
        activeRunId: null,
        activeRunOrigin: null,
        activeRunTaskId: null,
      }
    case 'DATASET_DETAIL_LOADING':
      return {
        ...state,
        mode: 'dataset',
        selectedDatasetId: action.datasetId,
        datasetDetailLoading: true,
        datasetsError: null,
        error: null,
        artifactTab: 'dataset',
      }
    case 'DATASET_DETAIL_LOADED':
      if (state.mode !== 'dataset' || state.selectedDatasetId !== action.detail.id) return state
      return {
        ...state,
        mode: 'dataset',
        selectedDatasetId: action.detail.id,
        datasetDetailLoading: false,
        datasetDetail: action.detail,
        datasetPreview: action.dataset,
        datasetsError: null,
        artifactTab: 'dataset',
      }
    case 'DATASET_DETAIL_ERROR':
      if (state.mode !== 'dataset' || state.selectedDatasetId !== action.datasetId) return state
      return {
        ...state,
        datasetDetailLoading: false,
        datasetsError: action.error,
        error: action.error,
      }
    default:
      return state
  }
}

// View-model adapter: StructuredTask → design TaskCard shape.
export type TaskView = {
  title: string
  context: string
  metrics: string[]
  dims: string[]
  compare: string
}

export function taskView(task: StructuredTask, compare: string): TaskView {
  return {
    title: task.task_title,
    context: task.context_pack_name,
    metrics: task.metrics,
    dims: task.dimensions,
    compare,
  }
}
