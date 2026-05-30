// Left rail: nav (current session), model status card. 后续能力（报告库/数据源/设置等）随对应版本上线时再引入入口。
import type { ModelStatus } from '../api/client'
import { Ico } from './icons'

function ModelStatusCard({ model }: { model: ModelStatus | null }) {
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
        : status === 'unknown'
          ? '状态未知'
          : '体验模式'

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
          <button className="model-foot-link">
            模型配置见 README
            <span style={{ marginLeft: 'auto', color: 'var(--ink-4)' }}>→</span>
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
            <button className="model-link primary">
              <Ico.Doc size={11} /> 查看配置说明
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
            <span>请检查模型密钥与网络连接</span>
          </div>
        </>
      )}
      {status === 'unknown' && (
        <>
          <div className="model-name muted">暂时无法获取模型状态</div>
          <div className="model-host" style={{ color: 'var(--ink-3)' }}>
            请确认分析服务是否已启动；恢复后会自动刷新。
          </div>
        </>
      )}
    </div>
  )
}

type SidebarProps = {
  model: ModelStatus | null
  onNewSession: () => void
  hasSession: boolean
}

export default function Sidebar({ model, onNewSession, hasSession }: SidebarProps) {
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
          <button className="rail-item active">
            <span className="ic">
              <Ico.Chat />
            </span>
            <span className="grow">当前会话</span>
            {hasSession ? <span className="meta">进行中</span> : null}
          </button>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0 }} />

      <div className="rail-foot">
        <ModelStatusCard model={model} />
      </div>
    </aside>
  )
}
