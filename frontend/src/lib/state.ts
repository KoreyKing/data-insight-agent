// App state machine: empty → dataset → parsing → task_ready → generating → report.
import type {
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

export type AppMode = 'current' | 'history' | 'dataset'

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
  artifactTab: ArtifactTab
  error: ApiError | null
  busy: string | null
  chartErrors: string[]
  genWaiting: boolean
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
  artifactTab: 'report',
  error: null,
  busy: null,
  chartErrors: [],
  genWaiting: false,
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
  | { type: 'RUN_REPORT' }
  | { type: 'STOP_GEN' }
  | { type: 'GEN_PROGRESS'; progress: ProgressStep[]; iter?: number; waiting?: boolean }
  | { type: 'GEN_TICK'; elapsed: string }
  | { type: 'REPORT_DONE'; report: ReportPayload; progress: ProgressStep[] }
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
  | { type: 'HISTORY_DETAIL_ERROR'; error: ApiError }
  | { type: 'DATASET_DETAIL_LOADING'; datasetId: string }
  | {
      type: 'DATASET_DETAIL_LOADED'
      detail: HistoryDatasetDetail
      dataset: DatasetPayload
    }
  | { type: 'DATASET_DETAIL_ERROR'; error: ApiError }

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
        userGoal: '',
        parsing: [],
        parseWarnings: [],
        error: null,
        busy: null,
        chartErrors: [],
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
        error: null,
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
      return { ...state, step: 'dataset', userGoal: '', task: null, parsing: [], parseWarnings: [] }
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
    case 'REPORT_DONE':
      return {
        ...state,
        mode: 'current',
        step: 'report',
        report: action.report,
        progress: action.progress,
        genWaiting: false,
        artifactTab: 'report',
        busy: null,
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
      return {
        ...state,
        historyDetailLoading: false,
        historyError: action.error,
        error: action.error,
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
