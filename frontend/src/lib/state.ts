// App state machine: empty → dataset → parsing → task_ready → generating → report.
import type {
  ApiError,
  ApiWarning,
  DatasetPayload,
  DimensionOption,
  ReportPayload,
  StructuredTask,
} from '../api/client'

export type Step = 'empty' | 'dataset' | 'parsing' | 'task_ready' | 'generating' | 'report'

export type ArtifactTab = 'report' | 'dataset' | 'task' | 'trace'

export type ProgressStep = {
  state: 'pending' | 'active' | 'done'
  label: string
  detail?: string
  time?: string
}

export type AppState = {
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
}

export const INITIAL: AppState = {
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
}

export type Action =
  | { type: 'RESET' }
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

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'RESET':
      return { ...INITIAL }
    case 'SET_BUSY':
      return { ...state, busy: action.busy }
    case 'SET_ERROR':
      return { ...state, error: action.error, busy: null }
    case 'DATASET_LOADED':
      return {
        ...state,
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
      }
    case 'SUBMIT_GOAL':
      return {
        ...state,
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
