// 业务口径设置（architecture.md §2.3 / §6.4）：指标口径 / 字段别名 / 异常阈值三块编辑，
// 保存走服务端四层校验，失败逐条定位；恢复默认与放弃修改都需二次确认。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  asApiError,
  getContextPack,
  resetContextPack,
  saveContextPack,
  type ApiError,
  type ContextPackIssue,
  type ContextPackPayload,
  type ContextPackState,
  type PackColumn,
  type PackMetric,
} from '../api/client'
import {
  baseVersion,
  clonePayload,
  isDirty,
  locateIssue,
  nextVersion,
  packColumns,
  versionLabel,
  type IssueLocation,
  type PackSection,
} from '../lib/context-pack'
import { friendlyContextPack } from '../lib/view'
import { Ico } from './icons'

// 只在打开时挂载（AppShell 条件渲染）：每次打开都是全新状态，不会闪现上次的草稿。
type ContextPackEditorProps = {
  onClose: () => void
  onChanged: (state: ContextPackState) => void
}

type Outcome = { kind: 'saved' | 'reset'; version: string; warnings: ContextPackIssue[] }
type ThresholdKey = 'significant_pct' | 'critical_pct'

const SECTIONS: { key: PackSection; label: string }[] = [
  { key: 'metrics', label: '指标口径' },
  { key: 'fields', label: '字段别名' },
  { key: 'thresholds', label: '异常阈值' },
]

const THRESHOLDS: { key: ThresholdKey; label: string; hint: string }[] = [
  { key: 'significant_pct', label: '标黄阈值', hint: '变化幅度达到该值标黄' },
  { key: 'critical_pct', label: '标红阈值', hint: '变化幅度达到该值标红，须大于标黄阈值' },
]

const CALCULATION_BOUNDARY =
  '口径表达式用于指导 AI 分析叙事；系统 KPI 卡当前按内置口径计算，不随此表达式变化'
// 保存与恢复默认都会改变字段识别，重跑影响提示两处共用（双向因果：删别名可能让重跑缺字段，加别名可能让重跑多字段）。
const RERUN_IMPACT_NOTE =
  '已保存任务重跑时：删除别名可能导致提示缺少字段，新增别名可能导致提示多出字段——如遇结构不一致提示，请先回到这里核对别名设置。'
const SAVE_EFFECT_NOTE = `新口径自下一次分析生效。${RERUN_IMPACT_NOTE}`
const ALIAS_SEPARATORS = /[,，、\n]/

function aliasKey(alias: string): string {
  return alias.trim().toLowerCase().replace(/[_\s]/g, '')
}

function readIssues(error: ApiError): ContextPackIssue[] {
  const list = error.details?.errors
  if (!Array.isArray(list)) return []
  return list.filter(
    (item): item is ContextPackIssue =>
      Boolean(item) && typeof item === 'object' && typeof item.message === 'string',
  )
}

function AliasInput({
  id,
  label,
  aliases,
  invalid,
  disabled,
  onChange,
  onPendingChange,
}: {
  id: string
  label: string
  aliases: string[]
  invalid: boolean
  disabled: boolean
  onChange: (aliases: string[]) => void
  onPendingChange: (id: string, pending: boolean) => void
}) {
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // 已输入未回车的别名也算未保存修改：footer 状态与关闭确认都要感知到。
  useEffect(() => {
    onPendingChange(id, text.trim() !== '')
    return () => onPendingChange(id, false)
  }, [id, text, onPendingChange])

  function commit(raw: string) {
    setText('')
    const next = [...aliases]
    for (const part of raw.split(ALIAS_SEPARATORS).map((value) => value.trim())) {
      if (part && !next.some((alias) => aliasKey(alias) === aliasKey(part))) next.push(part)
    }
    if (next.length !== aliases.length) onChange(next)
  }

  return (
    <div
      className={`alias-input ${invalid ? 'invalid' : ''} ${disabled ? 'disabled' : ''}`}
      onClick={() => inputRef.current?.focus()}
    >
      {aliases.map((alias, index) => (
        <span className="alias-chip" key={`${alias}-${index}`}>
          {alias}
          <button
            type="button"
            aria-label={`删除别名「${alias}」`}
            disabled={disabled}
            onClick={(event) => {
              event.stopPropagation()
              onChange(aliases.filter((_, position) => position !== index))
            }}
          >
            <Ico.X size={8} />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        id={id}
        value={text}
        aria-label={label}
        disabled={disabled}
        placeholder={aliases.length ? '添加别名…' : '输入别名，回车添加'}
        onChange={(event) => {
          const value = event.target.value
          if (ALIAS_SEPARATORS.test(value)) commit(value)
          else setText(value)
        }}
        onKeyDown={(event) => {
          // 中文输入法组字时的回车只是确认拼写，不能提交半截别名（Safari 以 keyCode 229 标识）。
          if (event.key !== 'Enter' || event.nativeEvent.isComposing || event.keyCode === 229) return
          event.preventDefault()
          commit(text)
        }}
        onBlur={() => commit(text)}
      />
    </div>
  )
}

export default function ContextPackEditor({ onClose, onChanged }: ContextPackEditorProps) {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<ApiError | null>(null)
  const [loadToken, setLoadToken] = useState(0)
  const [saved, setSaved] = useState<ContextPackState | null>(null)
  const [draft, setDraft] = useState<ContextPackPayload | null>(null)
  const [section, setSection] = useState<PackSection>('metrics')
  const [busy, setBusy] = useState<'save' | 'reset' | null>(null)
  const [issues, setIssues] = useState<ContextPackIssue[]>([])
  const [actionError, setActionError] = useState<ApiError | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [confirm, setConfirm] = useState<'reset' | 'discard' | null>(null)
  const [pendingFocus, setPendingFocus] = useState<string | null>(null)
  const [pendingAliases, setPendingAliases] = useState<ReadonlySet<string>>(new Set())
  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const outcomeRef = useRef<HTMLDivElement>(null)
  const issuesRef = useRef<HTMLDivElement>(null)
  const confirmSafeRef = useRef<HTMLButtonElement>(null)
  const confirmOriginRef = useRef<HTMLElement | null>(null)
  const pressedOnBackdrop = useRef(false)

  const dirty = isDirty(draft, saved) || pendingAliases.size > 0
  const working = busy !== null

  // 键盘监听每次打开只挂一次，通过 ref 读取最新状态与回调。
  const latest = useRef({ working, confirm, dirty, onClose, onChanged })
  latest.current = { working, confirm, dirty, onClose, onChanged }

  const onPendingChange = useCallback((id: string, pending: boolean) => {
    setPendingAliases((current) => {
      if (current.has(id) === pending) return current
      const next = new Set(current)
      if (pending) next.add(id)
      else next.delete(id)
      return next
    })
  }, [])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setLoadError(null)
    getContextPack()
      .then((state) => {
        if (!alive) return
        setSaved(state)
        setDraft(clonePayload(state.payload))
        latest.current.onChanged(state)
      })
      .catch((err) => {
        if (alive) setLoadError(asApiError(err))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [loadToken])

  useEffect(() => {
    const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const frame = window.requestAnimationFrame(() => panelRef.current?.focus())
    return () => {
      window.cancelAnimationFrame(frame)
      returnFocus?.focus()
    }
  }, [])

  useEffect(() => {
    if (!pendingFocus) return
    const element = document.getElementById(pendingFocus)
    if (element) {
      element.scrollIntoView({ block: 'center' })
      element.focus()
    }
    setPendingFocus(null)
  }, [pendingFocus, section])

  // 确认条出现时焦点移到安全按钮；关闭后回到触发它的控件（不可用时回到对话框本身）。
  useEffect(() => {
    if (confirm) {
      confirmSafeRef.current?.focus()
      return
    }
    const origin = confirmOriginRef.current
    confirmOriginRef.current = null
    if (!origin) return
    const usable = document.contains(origin) && !(origin as HTMLButtonElement).disabled
    ;(usable ? origin : panelRef.current)?.focus()
  }, [confirm])

  // 保存 / 恢复 / 校验失败后把焦点放到结果面板，避免焦点随被禁用的按钮落到页面 body。
  useEffect(() => {
    if (outcome) outcomeRef.current?.focus()
  }, [outcome])
  useEffect(() => {
    if (issues.length > 0) issuesRef.current?.focus()
  }, [issues])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        // 输入法候选框里的 Esc 只取消组字，不关闭对话框。
        if (event.isComposing || event.keyCode === 229) return
        const state = latest.current
        if (state.working) return
        if (state.confirm) setConfirm(null)
        else if (state.dirty) openConfirm('discard')
        else state.onClose()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = [
        ...(panelRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]):not([tabindex="-1"]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? []),
      ]
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panelRef.current)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const locations = useMemo(
    () => issues.map((issue) => ({ issue, location: locateIssue(issue.path, draft) })),
    [issues, draft],
  )
  const invalidAnchors = useMemo(
    () => new Set(locations.map(({ location }) => location.anchor).filter(Boolean)),
    [locations],
  )
  const sectionIssues = useMemo(() => {
    const counts: Record<PackSection, number> = { metrics: 0, fields: 0, thresholds: 0 }
    for (const { location } of locations) if (location.section) counts[location.section] += 1
    return counts
  }, [locations])

  function openConfirm(kind: 'reset' | 'discard') {
    confirmOriginRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    setConfirm(kind)
  }

  function requestClose() {
    if (working) return
    if (dirty) {
      openConfirm('discard')
      return
    }
    onClose()
  }

  function edited(update: (current: ContextPackPayload) => ContextPackPayload) {
    setDraft((current) => (current ? update(current) : current))
    setOutcome(null)
  }

  function updateMetric(index: number, patch: Partial<PackMetric>) {
    edited((current) => ({
      ...current,
      metrics: current.metrics.map((metric, position) =>
        position === index ? { ...metric, ...patch } : metric,
      ),
    }))
  }

  function updateColumn(index: number, patch: Partial<PackColumn>) {
    edited((current) => {
      const [table, ...rest] = current.data_dictionary.tables
      const columns = table.columns.map((column, position) =>
        position === index ? { ...column, ...patch } : column,
      )
      return {
        ...current,
        data_dictionary: { ...current.data_dictionary, tables: [{ ...table, columns }, ...rest] },
      }
    })
  }

  function updateThreshold(key: ThresholdKey, raw: string) {
    const value = raw.trim() === '' ? null : Number(raw)
    edited((current) => ({
      ...current,
      report_preferences: {
        ...current.report_preferences,
        anomaly_thresholds: { ...current.report_preferences.anomaly_thresholds, [key]: value },
      },
    }))
  }

  function jumpTo(location: IssueLocation) {
    if (!location.section) return
    setSection(location.section)
    setPendingFocus(location.anchor)
  }

  async function save() {
    if (!draft || !dirty || working) return
    setBusy('save')
    setActionError(null)
    setIssues([])
    setOutcome(null)
    setConfirm(null)
    try {
      const next = await saveContextPack(draft)
      setSaved(next)
      setDraft(clonePayload(next.payload))
      setIssues([])
      setOutcome({ kind: 'saved', version: next.version, warnings: next.warnings ?? [] })
      onChanged(next)
    } catch (err) {
      const error = asApiError(err)
      const errors = error.code === 'CONTEXT_PACK_VALIDATION_FAILED' ? readIssues(error) : []
      if (errors.length > 0) {
        setIssues(errors)
        const first = locateIssue(errors[0].path, draft)
        if (first.section) setSection(first.section)
      } else {
        setActionError(error)
      }
    } finally {
      setBusy(null)
      bodyRef.current?.scrollTo({ top: 0 })
    }
  }

  async function restoreDefaults() {
    setBusy('reset')
    setActionError(null)
    setOutcome(null)
    try {
      const next = await resetContextPack()
      setSaved(next)
      setDraft(clonePayload(next.payload))
      setIssues([])
      setOutcome({ kind: 'reset', version: next.version, warnings: [] })
      onChanged(next)
    } catch (err) {
      setActionError(asApiError(err))
    } finally {
      setConfirm(null)
      setBusy(null)
      bodyRef.current?.scrollTo({ top: 0 })
    }
  }

  // 「标黄须小于标红」是两者共同的问题：整组阈值一起标出。
  const thresholdPairInvalid = issues.some(
    (issue) => issue.path === 'report_preferences.anomaly_thresholds',
  )
  const invalid = (anchor: string) =>
    invalidAnchors.has(anchor) || (thresholdPairInvalid && anchor.startsWith('pack-threshold-'))
  const columns = draft ? packColumns(draft) : []
  const thresholds = draft?.report_preferences.anomaly_thresholds
  const sectionCounts: Record<PackSection, number> = {
    metrics: draft?.metrics.length ?? 0,
    fields: columns.length,
    thresholds: THRESHOLDS.length,
  }
  const significant = thresholds?.significant_pct
  const critical = thresholds?.critical_pct
  const scaleReady =
    typeof significant === 'number' &&
    typeof critical === 'number' &&
    significant > 0 &&
    significant < critical

  return (
    <div
      className="modal-backdrop pack-editor-backdrop"
      // 只有在遮罩上按下并松开才算关闭：从输入框拖选文字到遮罩上松手不应关闭。
      onMouseDown={(event) => {
        pressedOnBackdrop.current = event.target === event.currentTarget
      }}
      onClick={(event) => {
        if (pressedOnBackdrop.current && event.target === event.currentTarget) requestClose()
        pressedOnBackdrop.current = false
      }}
    >
      <div
        ref={panelRef}
        className="modal-panel pack-editor-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="pack-editor-title"
        aria-describedby="pack-editor-version"
        tabIndex={-1}
      >
        <div className="model-config-hd">
          <div>
            <div className="model-config-eyebrow">BUSINESS METRICS</div>
            <h2 id="pack-editor-title">业务口径设置</h2>
            <div className="pack-editor-version" id="pack-editor-version">
              {saved
                ? `${friendlyContextPack(saved.name)} · ${versionLabel(saved)}`
                : '正在读取当前口径…'}
            </div>
          </div>
          <button className="btn subtle xs" type="button" onClick={requestClose} disabled={working}>
            <Ico.X size={10} /> 关闭
          </button>
        </div>

        {draft && (
          <div
            className="pack-editor-tabs"
            role="tablist"
            aria-label="口径分类"
            onKeyDown={(event) => {
              const keys = ['ArrowRight', 'ArrowLeft', 'Home', 'End']
              if (!keys.includes(event.key)) return
              event.preventDefault()
              const index = SECTIONS.findIndex(({ key }) => key === section)
              const nextIndex =
                event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? SECTIONS.length - 1
                    : (index + (event.key === 'ArrowRight' ? 1 : -1) + SECTIONS.length) %
                      SECTIONS.length
              const next = SECTIONS[nextIndex].key
              setSection(next)
              document.getElementById(`pack-tab-${next}`)?.focus()
            }}
          >
            {SECTIONS.map(({ key, label }) => (
              <button
                key={key}
                id={`pack-tab-${key}`}
                type="button"
                role="tab"
                aria-selected={section === key}
                aria-controls="pack-editor-section"
                aria-label={`${label}，${sectionCounts[key]} 项${sectionIssues[key] > 0 ? `，${sectionIssues[key]} 处问题` : ''}`}
                tabIndex={section === key ? 0 : -1}
                className={`pack-tab ${section === key ? 'active' : ''}`}
                onClick={() => setSection(key)}
              >
                {label}
                <span className="pack-tab-count" aria-hidden="true">
                  {sectionCounts[key]}
                </span>
                {sectionIssues[key] > 0 && (
                  <span className="pack-tab-issues" aria-hidden="true">
                    {sectionIssues[key]}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        <div ref={bodyRef} className="modal-body pack-editor-body">
          {loading && <div className="pack-editor-empty">正在读取业务口径…</div>}

          {loadError && (
            <div className="model-config-alert error" role="alert">
              <Ico.Warn size={13} />
              <span>{loadError.message}</span>
              <button className="btn subtle xs" type="button" onClick={() => setLoadToken((token) => token + 1)}>
                重试
              </button>
            </div>
          )}

          {outcome && (
            <div className="pack-outcome" role="status" ref={outcomeRef} tabIndex={-1}>
              <div className="pack-outcome-title">
                <Ico.Check size={13} />
                {outcome.kind === 'saved'
                  ? `已保存 · 口径版本 ${outcome.version}`
                  : `已恢复出厂口径 · 口径版本 ${outcome.version}`}
              </div>
              <p>
                {outcome.kind === 'saved'
                  ? SAVE_EFFECT_NOTE
                  : `出厂内容已还原；版本号继续递增，不会回到 ${baseVersion(outcome.version)}。新口径自下一次分析生效。${RERUN_IMPACT_NOTE}`}
              </p>
              {outcome.warnings.length > 0 && (
                <ul className="pack-warnings">
                  {outcome.warnings.map((warning, index) => (
                    <li key={`${warning.path}-${index}`}>
                      <Ico.Warn size={11} />
                      <span>
                        {locateIssue(warning.path, draft).label && (
                          <b>{locateIssue(warning.path, draft).label} </b>
                        )}
                        {warning.message}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {issues.length > 0 && (
            <div className="pack-issues" role="alert" ref={issuesRef} tabIndex={-1}>
              <div className="pack-issues-title">
                <Ico.Warn size={13} /> 口径设置有 {issues.length} 处问题，尚未保存
              </div>
              <ol>
                {locations.map(({ issue, location }, index) => (
                  <li key={`${issue.path}-${index}`}>
                    <button
                      type="button"
                      className="pack-issue"
                      onClick={() => jumpTo(location)}
                      disabled={!location.section}
                    >
                      {location.label && <span className="pack-issue-where">{location.label}</span>}
                      <span className="pack-issue-message">{issue.message}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {actionError && (
            <div className="model-config-alert error" role="alert">
              <Ico.Warn size={13} />
              <span>{actionError.message}</span>
            </div>
          )}

          {draft && (
            <div id="pack-editor-section" role="tabpanel" aria-labelledby={`pack-tab-${section}`}>
              {section === 'metrics' && (
                <>
                  <p className="pack-intro">
                    指标口径决定 AI 如何理解与叙述每个指标。可修改口径表达式、别名、单位与说明；指标本身不可增删。
                  </p>
                  {draft.metrics.map((metric, index) => (
                    <section
                      className={`pack-item ${invalid(`pack-metric-${index}`) ? 'invalid' : ''}`}
                      key={metric.name}
                      id={`pack-metric-${index}`}
                      aria-label={`指标「${metric.name}」`}
                      tabIndex={-1}
                    >
                      <header className="pack-item-hd">
                        <h4>{metric.name}</h4>
                        <label className="pack-unit">
                          <span>单位</span>
                          <input
                            id={`pack-metric-${index}-unit`}
                            aria-label={`${metric.name}的单位`}
                            className={invalid(`pack-metric-${index}-unit`) ? 'invalid' : ''}
                            value={metric.unit ?? ''}
                            disabled={working}
                            onChange={(event) => updateMetric(index, { unit: event.target.value })}
                          />
                        </label>
                      </header>
                      <div className="pack-item-grid">
                        <div>
                          <label className="pack-label" htmlFor={`pack-metric-${index}-calculation`}>
                            口径表达式
                          </label>
                          <textarea
                            id={`pack-metric-${index}-calculation`}
                            className={`pack-textarea mono ${invalid(`pack-metric-${index}-calculation`) ? 'invalid' : ''}`}
                            rows={3}
                            spellCheck={false}
                            aria-label={`${metric.name}的口径表达式`}
                            value={metric.calculation ?? ''}
                            disabled={working}
                            aria-describedby={`pack-metric-${index}-boundary`}
                            onChange={(event) => updateMetric(index, { calculation: event.target.value })}
                          />
                          <p className="pack-boundary" id={`pack-metric-${index}-boundary`}>
                            {CALCULATION_BOUNDARY}
                          </p>
                        </div>
                        <div>
                          <label className="pack-label" htmlFor={`pack-metric-${index}-aliases`}>
                            别名
                          </label>
                          <AliasInput
                            id={`pack-metric-${index}-aliases`}
                            label={`${metric.name}的别名`}
                            aliases={metric.aliases ?? []}
                            invalid={invalid(`pack-metric-${index}-aliases`)}
                            disabled={working}
                            onChange={(aliases) => updateMetric(index, { aliases })}
                            onPendingChange={onPendingChange}
                          />
                          <label className="pack-label" htmlFor={`pack-metric-${index}-notes`}>
                            说明
                          </label>
                          <textarea
                            id={`pack-metric-${index}-notes`}
                            className={`pack-textarea ${invalid(`pack-metric-${index}-notes`) ? 'invalid' : ''}`}
                            rows={2}
                            aria-label={`${metric.name}的说明`}
                            value={metric.notes ?? ''}
                            disabled={working}
                            onChange={(event) => updateMetric(index, { notes: event.target.value })}
                          />
                        </div>
                      </div>
                    </section>
                  ))}
                </>
              )}

              {section === 'fields' && (
                <>
                  <p className="pack-intro">
                    字段别名决定上传文件的表头能否被识别成对应的业务字段。字段与显示名不可修改；删除别名后，已保存任务重跑时可能提示缺少字段。
                  </p>
                  <div className="pack-field-head" aria-hidden="true">
                    <span>业务字段</span>
                    <span>别名（表头写法）</span>
                    <span>说明</span>
                  </div>
                  {columns.map((column, index) => (
                    <div
                      className={`pack-field-row ${invalid(`pack-field-${index}`) ? 'invalid' : ''}`}
                      key={column.name}
                      id={`pack-field-${index}`}
                      tabIndex={-1}
                    >
                      <div className="pack-field-name" title={`字段标识：${column.name}`}>
                        <strong>{column.display_name}</strong>
                      </div>
                      <AliasInput
                        id={`pack-field-${index}-aliases`}
                        label={`${column.display_name}的别名`}
                        aliases={column.aliases ?? []}
                        invalid={invalid(`pack-field-${index}-aliases`)}
                        disabled={working}
                        onChange={(aliases) => updateColumn(index, { aliases })}
                        onPendingChange={onPendingChange}
                      />
                      <input
                        id={`pack-field-${index}-description`}
                        className={`pack-input ${invalid(`pack-field-${index}-description`) ? 'invalid' : ''}`}
                        aria-label={`${column.display_name}的说明`}
                        value={column.description ?? ''}
                        disabled={working}
                        onChange={(event) => updateColumn(index, { description: event.target.value })}
                      />
                    </div>
                  ))}
                </>
              )}

              {section === 'thresholds' && thresholds && (
                <>
                  <p className="pack-intro">
                    对比上期时，金额与数量类指标的变化幅度达到阈值会被着色；率值指标（如退款率）按百分点呈现，不参与着色。
                  </p>
                  <div className="pack-threshold-grid">
                    {THRESHOLDS.map(({ key, label, hint }) => (
                      <label
                        key={key}
                        className={`pack-threshold ${key} ${invalid(`pack-threshold-${key}`) ? 'invalid' : ''}`}
                      >
                        <span className="pack-threshold-name">{label}</span>
                        <span className="pack-threshold-input">
                          <input
                            id={`pack-threshold-${key}`}
                            aria-label={`${label}（%）`}
                            type="number"
                            min={0}
                            step={0.5}
                            inputMode="decimal"
                            value={thresholds[key] ?? ''}
                            disabled={working}
                            onChange={(event) => updateThreshold(key, event.target.value)}
                          />
                          <em>%</em>
                        </span>
                        <small>{hint}</small>
                      </label>
                    ))}
                  </div>
                  <p className="pack-threshold-rule">
                    {scaleReady
                      ? `当前规则：变化幅度 < ${significant}% 不着色；${significant}% ~ ${critical}% 标黄；≥ ${critical}% 标红。`
                      : '标黄阈值需大于 0 且小于标红阈值，保存时会再次校验。'}
                  </p>
                </>
              )}
            </div>
          )}
        </div>

        <div className="pack-editor-actions">
          {confirm ? (
            <div className="pack-confirm" role="alertdialog" aria-label="确认操作">
              <span>
                {confirm === 'reset' && saved
                  ? `恢复默认会把指标口径、字段别名、异常阈值全部还原为出厂设置，版本号继续递增为 ${nextVersion(saved)}（不会回到 ${baseVersion(saved.version)}）。${dirty ? '未保存的修改也会一并放弃。' : ''}`
                  : '有未保存的修改，关闭后将丢失。'}
              </span>
              <button
                ref={confirmSafeRef}
                className="btn subtle"
                type="button"
                onClick={() => setConfirm(null)}
                disabled={working}
              >
                {confirm === 'reset' ? '取消' : '继续编辑'}
              </button>
              {confirm === 'reset' ? (
                <button className="btn danger" type="button" onClick={restoreDefaults} disabled={working}>
                  {busy === 'reset' ? '正在恢复…' : '确认恢复默认'}
                </button>
              ) : (
                <button className="btn danger" type="button" onClick={onClose}>
                  放弃修改并关闭
                </button>
              )}
            </div>
          ) : (
            <>
              <button
                className="btn ghost"
                type="button"
                onClick={() => openConfirm('reset')}
                disabled={!saved?.is_modified || working}
                aria-label="恢复默认"
                title={saved && !saved.is_modified ? '当前已是出厂口径' : undefined}
              >
                <Ico.Loop size={11} /> 恢复默认
              </button>
              <span className={`pack-editor-dirty ${dirty ? 'on' : ''}`} aria-live="polite">
                {dirty ? '有未保存的修改' : saved ? '修改已全部保存' : ''}
              </span>
              <button className="btn subtle" type="button" onClick={requestClose} disabled={working}>
                关闭
              </button>
              <button className="btn primary" type="button" onClick={save} disabled={!dirty || working}>
                {busy === 'save' ? '正在校验并保存…' : '保存口径'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
