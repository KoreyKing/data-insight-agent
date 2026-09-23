import { useEffect, useId, useRef, useState } from 'react'
import {
  asApiError,
  fetchReportFeedback,
  submitReportFeedback,
  type ApiError,
  type FeedbackVerdict,
  type ReportFeedbackRecord,
} from '../api/client'
import { formatHistoryDate } from '../lib/history'
import { Ico } from './icons'

const MAX_COMMENT_LENGTH = 500
const VERDICTS: { value: FeedbackVerdict; label: string }[] = [
  { value: 'useful', label: '有用' },
  { value: 'not_useful', label: '没用' },
]

// 未保存的补充按报告暂存在内存：切到数据集 / SQL 标签再切回时组件会重建，输入不应丢失。
// 只暂存读到库内反馈之后写下的补充；刷新页面即清空。
const unsavedDrafts = new Map<string, string>()

// 与服务端同口径（architecture.md §2.3 v0.14）：去首尾空白后按 Unicode 码点计数。
function commentLength(text: string): number {
  return Array.from(text.trim()).length
}

function verdictLabel(verdict: FeedbackVerdict): string {
  return VERDICTS.find((item) => item.value === verdict)?.label ?? verdict
}

function feedbackError(value: unknown): ApiError {
  const error = asApiError(value)
  // 报告已不在当前数据库（如换库后仍停留在旧页面）：重试不会成功，直接说明结论。
  return error.code === 'REPORT_NOT_FOUND'
    ? { ...error, message: '没有找到这份报告，无法反馈。' }
    : error
}

// 报告底部反馈点：点「有用 / 没用」即提交，一句话补充随票提交或事后单独保存；一报告一票，可改票。
// 调用方以 key={reportId} 挂载：切换报告即重建组件，旧请求的响应不会落到新报告上。
export default function ReportFeedback({ reportId }: { reportId: string }) {
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [saved, setSaved] = useState<ReportFeedbackRecord | null>(null)
  const [draft, setDraft] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const alive = useRef(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const id = useId()

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    let active = true
    fetchReportFeedback(reportId)
      .then(({ feedback }) => {
        if (!active) return
        setSaved(feedback)
        setDraft(unsavedDrafts.get(reportId) ?? feedback?.comment ?? '')
        setLoadState('ready')
      })
      .catch((value: unknown) => {
        if (!active) return
        setError(feedbackError(value))
        setLoadState('failed')
      })
    return () => {
      active = false
    }
  }, [reportId, loadAttempt])

  const ready = loadState === 'ready'
  const comment = draft.trim()
  const length = commentLength(draft)
  const tooLong = length > MAX_COMMENT_LENGTH
  const commentDirty = comment !== (saved?.comment ?? '')
  const reportMissing = error?.code === 'REPORT_NOT_FOUND'
  // 回显读取完成前锁定投票与补充输入：提交会整条覆盖库内反馈，没读到、没展示已存补充时不能提交；
  // 同时避免较早发出的读取结果覆盖刚提交的票。
  // 锁定用 aria-disabled 而非 disabled：被禁用的按钮会失焦，键盘用户的焦点会落回页面顶部。
  const locked = !ready || submitting || tooLong

  useEffect(() => {
    if (!ready) return
    if (commentDirty) unsavedDrafts.set(reportId, draft)
    else unsavedDrafts.delete(reportId)
  }, [reportId, ready, draft, commentDirty])

  function retryLoad() {
    setError(null)
    setLoadState('loading')
    setLoadAttempt((attempt) => attempt + 1)
    // 「重新读取」随错误提示一起消失：焦点移到补充输入框（读取期间只读）。
    inputRef.current?.focus()
  }

  async function submit(verdict: FeedbackVerdict): Promise<boolean> {
    if (locked) return false
    if (saved?.verdict === verdict && !commentDirty) return false
    setSubmitting(true)
    setError(null)
    try {
      const next = await submitReportFeedback(reportId, verdict, comment)
      if (!alive.current) return false
      setSaved(next)
      // 提交期间若又改了补充，保留新输入；否则同步为服务端去空白后的文本。
      setDraft((current) => (current.trim() === comment ? next.comment : current))
      return true
    } catch (value) {
      if (alive.current) setError(feedbackError(value))
      return false
    } finally {
      if (alive.current) setSubmitting(false)
    }
  }

  async function saveComment() {
    if (!saved) return
    // 保存成功后「保存补充」随之消失：焦点移回输入框。
    if (await submit(saved.verdict)) inputRef.current?.focus()
  }

  let status = '点选即提交，仅保存在本系统，不会外发。'
  if (loadState === 'loading') status = '正在读取反馈…'
  else if (loadState === 'failed')
    status = reportMissing
      ? '无法对这份报告投票。'
      : '未能读取这份报告的反馈记录，重新读取后才能投票和填写补充。'
  else if (submitting) status = '正在提交…'
  else if (tooLong) status = `反馈内容过长（最多 ${MAX_COMMENT_LENGTH} 字），缩短后才能提交。`
  else if (saved)
    status = `已记录「${verdictLabel(saved.verdict)}」· ${formatHistoryDate(saved.updated_at)} · ${
      commentDirty ? '补充尚未保存' : '可随时改票'
    }`
  else if (comment) status = '点「有用 / 没用」时会一并提交这句补充。'

  const questionId = `${id}-question`
  const inputId = `${id}-comment`
  const statusId = `${id}-status`
  const countId = `${id}-count`

  return (
    <section className="rep-feedback" aria-labelledby={questionId}>
      <div className="rep-feedback-hd">
        <h3 id={questionId}>这份报告对你有用吗？</h3>
        <div className="rep-feedback-choices">
          {VERDICTS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              className={`btn ghost sm rep-feedback-choice ${value}`}
              aria-pressed={saved?.verdict === value}
              aria-disabled={locked}
              aria-describedby={statusId}
              onClick={() => void submit(value)}
            >
              {value === 'useful' ? <Ico.ThumbUp size={12} /> : <Ico.ThumbDown size={12} />} {label}
            </button>
          ))}
        </div>
      </div>
      <label className="rep-feedback-label" htmlFor={inputId}>
        补充一句（可选）
      </label>
      <textarea
        ref={inputRef}
        id={inputId}
        className={`rep-feedback-input${tooLong ? ' invalid' : ''}${loadState === 'failed' ? ' locked' : ''}`}
        rows={2}
        value={draft}
        readOnly={!ready}
        placeholder="比如：哪条结论帮到了你，或哪里不准"
        onChange={(event) => setDraft(event.target.value)}
        aria-invalid={tooLong}
        aria-describedby={`${countId} ${statusId}`}
      />
      <div className="rep-feedback-foot">
        <span id={statusId} className="rep-feedback-status" aria-live="polite">
          {status}
        </span>
        <span id={countId} className={`rep-feedback-count${tooLong ? ' over' : ''}`}>
          {length}/{MAX_COMMENT_LENGTH} 字
        </span>
        {saved && commentDirty && (
          <button
            type="button"
            className="btn primary sm"
            aria-disabled={locked}
            aria-describedby={statusId}
            onClick={() => void saveComment()}
          >
            保存补充
          </button>
        )}
      </div>
      {error && (
        <div className="rep-feedback-error" role="alert">
          <Ico.Warn size={12} /> {error.message}
          {loadState === 'failed' && !reportMissing && (
            <button type="button" className="btn ghost xs" onClick={retryLoad}>
              重新读取
            </button>
          )}
        </div>
      )}
    </section>
  )
}
