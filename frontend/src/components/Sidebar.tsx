// Left rail: current session, read-only history, data sources, model status.
import type { HistoryReportListItem, ModelStatus } from '../api/client'
import type { AppMode } from '../lib/state'
import { formatHistoryDate, historySummary, statusLabel } from '../lib/history'
import { Ico } from './icons'

function ModelStatusCard({
  model,
  onOpenModelConfig,
}: {
  model: ModelStatus | null
  onOpenModelConfig: () => void
}) {
  const status = model?.status ?? 'unknown'
  const dotColor =
    status === 'configured'
      ? 'var(--forest-500)'
      : status === 'failed'
        ? 'var(--rust-500)'
        : status === 'unknown'
          ? 'var(--ink-4)'
          : 'var(--amber-500)'
  const labelColor =
    status === 'configured'
      ? 'var(--forest-700)'
      : status === 'failed'
        ? 'var(--rust-600)'
        : status === 'unknown'
          ? 'var(--ink-3)'
          : 'var(--amber-500)'
  const label =
    status === 'configured'
      ? '模型已配置'
      : status === 'failed'
        ? '连接异常'
        : status === 'disabled'
          ? '模型已关闭'
          : status === 'unknown'
            ? '状态未知'
            : '体验模式'
  const actionLabel = status === 'configured' || status === 'disabled' ? '编辑模型配置' : '配置模型'

  return (
    <div className="model-card">
      <div className="model-hd">
        <span className="model-key">LLM</span>
        <span className="model-st" style={{ color: labelColor }}>
          <span
            className="model-dot"
            style={{ background: dotColor, boxShadow: `0 0 0 3px ${dotColor}22` }}
          />
          {label}
        </span>
      </div>
      {status === 'configured' && (
        <>
          <div className="model-name">{model?.model ?? '已配置'}</div>
          <div className="model-host">模型来源 · {model?.provider ?? 'custom'}</div>
          <button className="model-foot-link" onClick={onOpenModelConfig}>
            <Ico.Cog size={12} /> {actionLabel}
            <span className="model-foot-arrow">→</span>
          </button>
        </>
      )}
      {status === 'disabled' && (
        <>
          <div className="model-name muted">{model?.model ?? '模型已关闭'}</div>
          <div className="model-host" style={{ color: 'var(--ink-3)' }}>
            已保存配置，当前不调用模型。
          </div>
          <button className="model-foot-link" onClick={onOpenModelConfig}>
            <Ico.Cog size={12} /> {actionLabel}
            <span className="model-foot-arrow">→</span>
          </button>
        </>
      )}
      {status === 'not_configured' && (
        <>
          <div className="model-name muted">体验模式 · 未配置模型</div>
          <div className="model-host" style={{ color: 'var(--ink-3)' }}>
            未配置 AI 大模型，使用默认模板产出示例报告。配置模型后可用自然语言定制分析。
          </div>
          <div className="model-foot">
            <button className="model-link primary" onClick={onOpenModelConfig}>
              <Ico.Cog size={11} /> {actionLabel}
            </button>
          </div>
        </>
      )}
      {status === 'failed' && (
        <>
          <div className="model-name">{model?.model ?? '调用失败'}</div>
          <div className="model-host" style={{ color: 'var(--rust-600)' }}>
            最近一次调用失败 · 见报告告警
          </div>
          <div className="model-foot">
            <button className="model-link primary" onClick={onOpenModelConfig}>
              <Ico.Cog size={11} /> 检查配置
            </button>
          </div>
        </>
      )}
      {status === 'unknown' && (
        <>
          <div className="model-name muted">暂时无法获取模型状态</div>
          <div className="model-host" style={{ color: 'var(--ink-3)' }}>
            请确认分析服务是否已启动；恢复后会自动刷新。
          </div>
          <div className="model-foot">
            <button className="model-link primary" onClick={onOpenModelConfig}>
              <Ico.Cog size={11} /> 打开配置
            </button>
          </div>
        </>
      )}
    </div>
  )
}

type SidebarProps = {
  model: ModelStatus | null
  onNewSession: () => void
  onSelectCurrent: () => void
  onSelectHistory: () => void
  onSelectDatasets: () => void
  onOpenHistory: (reportId: string) => void
  hasSession: boolean
  activeMode: AppMode
  historyReports: HistoryReportListItem[]
  historyTotal: number
  historyLoading: boolean
  selectedHistoryId: string | null
  datasetsTotal: number
  datasetsLoading: boolean
  onOpenModelConfig: () => void
}

export default function Sidebar({
  model,
  onNewSession,
  onSelectCurrent,
  onSelectHistory,
  onSelectDatasets,
  onOpenHistory,
  hasSession,
  activeMode,
  historyReports,
  historyTotal,
  historyLoading,
  selectedHistoryId,
  datasetsTotal,
  datasetsLoading,
  onOpenModelConfig,
}: SidebarProps) {
  const recentReports = historyReports.slice(0, 4)
  return (
    <aside className="rail">
      <div className="rail-hd">
        <div className="rail-logo">
          <span className="mark">D</span>
          <span>Data Insight</span>
        </div>
        <div className="rail-byline">AI 数据分析助手</div>
      </div>

      <div className="rail-section">
        <button
          className="btn primary"
          style={{ width: '100%', justifyContent: 'center', height: 34 }}
          onClick={onNewSession}
        >
          <Ico.Plus size={12} /> 新建会话
        </button>
      </div>

      <div className="rail-section">
        <h6>工作区</h6>
        <div className="rail-list">
          <button
            className={`rail-item ${activeMode === 'current' ? 'active' : ''}`}
            onClick={onSelectCurrent}
          >
            <span className="ic">
              <Ico.Chat />
            </span>
            <span className="grow">当前会话</span>
            {hasSession ? <span className="meta">进行中</span> : null}
          </button>
          <button
            className={`rail-item ${activeMode === 'history' ? 'active' : ''}`}
            onClick={onSelectHistory}
          >
            <span className="ic">
              <Ico.Doc />
            </span>
            <span className="grow">历史报告</span>
            <span className="meta">{historyLoading ? '加载' : historyTotal}</span>
          </button>
          <button
            className={`rail-item ${activeMode === 'dataset' ? 'active' : ''}`}
            onClick={onSelectDatasets}
          >
            <span className="ic">
              <Ico.Database />
            </span>
            <span className="grow">数据源</span>
            <span className="meta">{datasetsLoading ? '加载' : datasetsTotal}</span>
          </button>
        </div>
      </div>

      <div className="rail-section rail-section-grow">
        <h6>
          最近报告
          <span className="badge">{historyTotal}</span>
        </h6>
        <div className="rail-hist">
          {historyLoading && <div className="hist-empty">正在读取历史报告…</div>}
          {!historyLoading && recentReports.length === 0 && (
            <div className="hist-empty">暂无历史报告</div>
          )}
          {!historyLoading &&
            recentReports.map((report) => (
              <button
                key={report.id}
                className={`hist-row ${selectedHistoryId === report.id ? 'active' : ''}`}
                onClick={() => onOpenHistory(report.id)}
              >
                <span className="ttl">{report.title}</span>
                <span className="sub">
                  <span className={`dot ${report.status === 'partial' ? 'amber' : ''}`} />
                  {formatHistoryDate(report.ran_at)}
                  <span>·</span>
                  <span>{statusLabel(report.status)}</span>
                </span>
                <span className="hist-note">{historySummary(report.summary, 42)}</span>
              </button>
            ))}
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0 }} />

      <div className="rail-foot">
        <ModelStatusCard model={model} onOpenModelConfig={onOpenModelConfig} />
      </div>
    </aside>
  )
}
