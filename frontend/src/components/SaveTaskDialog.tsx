import { useEffect, useRef, useState, type FormEvent } from 'react'
import { asApiError, type ApiError } from '../api/client'
import { Ico } from './icons'

type SaveTaskDialogProps = {
  open: boolean
  initialTitle: string
  onClose: () => void
  onSave: (title: string) => Promise<void>
}

export default function SaveTaskDialog({
  open,
  initialTitle,
  onClose,
  onSave,
}: SaveTaskDialogProps) {
  const [title, setTitle] = useState(initialTitle)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLFormElement>(null)

  useEffect(() => {
    if (!open) return
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setTitle(initialTitle)
    setError(null)
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus())
    return () => {
      window.cancelAnimationFrame(frame)
      returnFocus?.focus()
    }
  }, [open, initialTitle])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !saving) onClose()
      if (event.key !== 'Tab') return
      const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [])]
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose, saving])

  if (!open) return null

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalized = title.trim()
    if (!normalized || normalized.length > 255) {
      setError({ code: 'TASK_TITLE_INVALID', message: '任务名不能为空，且不超过 255 字。' })
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSave(normalized)
      onClose()
    } catch (value) {
      setError(asApiError(value))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop save-task-backdrop" onClick={saving ? undefined : onClose}>
      <form
        ref={dialogRef}
        className="modal-panel save-task-panel"
        onSubmit={handleSubmit}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="保存为分析任务"
        aria-describedby={error ? 'save-task-description save-task-error' : 'save-task-description'}
      >
        <div className="model-config-hd">
          <div>
            <div className="model-config-eyebrow">REUSABLE TASK</div>
            <h2>保存为分析任务</h2>
          </div>
          <button className="btn subtle xs" type="button" onClick={onClose} disabled={saving}>
            <Ico.X size={10} /> 关闭
          </button>
        </div>
        <div className="save-task-body">
          <p id="save-task-description">保存报告当时的任务定义与数据结构。下期上传同结构文件即可直接重跑。</p>
          <label className="model-config-field">
            <span>任务名称</span>
            <input
              ref={inputRef}
              value={title}
              maxLength={255}
              onChange={(event) => setTitle(event.target.value)}
              disabled={saving}
            />
            <span className="model-config-help">{title.trim().length}/255 字</span>
          </label>
          {error && (
            <div className="model-config-alert error" id="save-task-error" role="alert">
              <Ico.Warn size={12} /> {error.message}
            </div>
          )}
        </div>
        <div className="save-task-actions">
          <button className="btn subtle" type="button" onClick={onClose} disabled={saving}>
            取消
          </button>
          <button className="btn primary" type="submit" disabled={saving}>
            <Ico.Template size={12} /> {saving ? '正在保存…' : '确认保存'}
          </button>
        </div>
      </form>
    </div>
  )
}
