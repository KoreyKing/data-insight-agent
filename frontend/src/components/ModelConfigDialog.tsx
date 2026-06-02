import { useEffect, useState, type FormEvent } from 'react'
import {
  asApiError,
  getLlmConfig,
  saveLlmConfig,
  testLlmConnection,
  type ApiError,
  type LlmConfig,
  type SaveLlmConfigPayload,
} from '../api/client'
import { Ico } from './icons'

type ProviderOption = {
  value: string
  label: string
}

const PROVIDERS: ProviderOption[] = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'dashscope', label: 'DashScope / 通义千问' },
  { value: 'kimi', label: 'Kimi / Moonshot' },
  { value: 'zhipu', label: '智谱 GLM' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'ollama', label: 'Ollama' },
  { value: 'vllm', label: 'vLLM' },
  { value: 'custom', label: 'Custom OpenAI-compatible' },
]

type ModelConfigDialogProps = {
  open: boolean
  onClose: () => void
  onSaved: () => Promise<void> | void
}

export default function ModelConfigDialog({ open, onClose, onSaved }: ModelConfigDialogProps) {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [provider, setProvider] = useState('openai')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [hasSavedKey, setHasSavedKey] = useState(false)
  const [source, setSource] = useState<LlmConfig['source']>('none')
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [testMessage, setTestMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(
    null,
  )

  useEffect(() => {
    if (!open) return
    let alive = true
    setLoading(true)
    setError(null)
    setTestMessage(null)
    setEnabled(true)
    setProvider('openai')
    setBaseUrl('')
    setModel('')
    setHasSavedKey(false)
    setSource('none')
    setApiKey('')
    setShowKey(false)
    getLlmConfig()
      .then((config) => {
        if (!alive) return
        setEnabled(config.enabled)
        setProvider(config.provider ?? 'openai')
        setBaseUrl(config.base_url ?? '')
        setModel(config.model ?? '')
        setHasSavedKey(config.has_key)
        setSource(config.source)
      })
      .catch((err) => {
        if (!alive) return
        setError(asApiError(err))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !saving && !testing) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose, saving, testing])

  if (!open) return null

  function buildPayload(): SaveLlmConfigPayload {
    const payload: SaveLlmConfigPayload = {
      provider,
      model: model.trim(),
      enabled,
    }
    const key = apiKey.trim()
    const url = baseUrl.trim()
    if (key) payload.api_key = key
    if (url) payload.base_url = url
    return payload
  }

  async function onTest() {
    setTesting(true)
    setError(null)
    setTestMessage(null)
    try {
      const result = await testLlmConnection(buildPayload())
      if (result.ok) {
        setTestMessage({ kind: 'ok', text: '连接测试通过。' })
      } else {
        setTestMessage({ kind: 'error', text: result.error ?? '连接测试失败。' })
      }
    } catch (err) {
      setError(asApiError(err))
    } finally {
      setTesting(false)
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    setTestMessage(null)
    try {
      await saveLlmConfig(buildPayload())
      await onSaved()
      onClose()
    } catch (err) {
      setError(asApiError(err))
    } finally {
      setSaving(false)
    }
  }

  const busy = loading || saving || testing
  const keyWasTyped = apiKey.trim().length > 0
  const canReuseSavedKey = source === 'ui' && hasSavedKey

  return (
    <div className="modal-backdrop model-config-backdrop" onClick={busy ? undefined : onClose}>
      <form className="modal-panel model-config-panel" onSubmit={onSubmit} onClick={(e) => e.stopPropagation()}>
        <div className="model-config-hd">
          <div>
            <div className="model-config-eyebrow">LLM</div>
            <h2>模型配置</h2>
          </div>
          <button className="btn subtle xs" type="button" onClick={onClose} disabled={busy}>
            <Ico.X size={10} /> 关闭
          </button>
        </div>

        <div className="modal-body model-config-body">
          <div className="model-config-row switch-row">
            <div>
              <label className="model-config-label">启用模型</label>
              <div className="model-config-help">
                关闭后进入体验模式，已保存配置仍会保留。
              </div>
            </div>
            <button
              type="button"
              className={`toggle ${enabled ? 'on' : ''}`}
              role="switch"
              aria-label="启用模型"
              aria-checked={enabled}
              onClick={() => setEnabled((value) => !value)}
              disabled={busy}
            >
              <span />
            </button>
          </div>

          <div className="model-config-grid">
            <label className="model-config-field">
              <span>供应商</span>
              <select
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                disabled={busy}
              >
                {PROVIDERS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="model-config-field">
              <span>模型名称</span>
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="deepseek-chat"
                disabled={busy}
              />
            </label>
          </div>

          <label className="model-config-field">
            <span>API Key</span>
            <div className="secret-input">
              <input
                type={showKey && keyWasTyped ? 'text' : 'password'}
                value={apiKey}
                onChange={(event) => {
                  setApiKey(event.target.value)
                  setTestMessage(null)
                }}
                placeholder={hasSavedKey ? '已保存密钥（不返回明文）' : 'sk-...'}
                disabled={busy}
                autoComplete="off"
              />
              <button
                type="button"
                className={`secret-eye ${showKey ? 'active' : ''}`}
                onClick={() => setShowKey((value) => !value)}
                disabled={!keyWasTyped || busy}
                title={showKey ? '隐藏 API Key' : '显示 API Key'}
                aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
              >
                <Ico.Eye size={14} />
              </button>
            </div>
            <span className="model-config-help">
              {keyWasTyped
                ? '当前输入只保存在本次弹窗中。'
                : canReuseSavedKey
                  ? '保存和测试将沿用已保存密钥。'
                  : hasSavedKey
                    ? '已有模型密钥可用；如需在这里保存配置，请输入新密钥。'
                    : 'Ollama / vLLM 可留空。'}
            </span>
          </label>

          <label className="model-config-field">
            <span>Base URL</span>
            <input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="留空使用供应商默认地址"
              disabled={busy}
            />
          </label>

          {error ? (
            <div className="model-config-alert error">
              <Ico.Warn size={13} />
              <span>{error.message}</span>
            </div>
          ) : null}

          {testMessage ? (
            <div className={`model-config-alert ${testMessage.kind}`}>
              {testMessage.kind === 'ok' ? <Ico.Check size={13} /> : <Ico.Warn size={13} />}
              <span>{testMessage.text}</span>
            </div>
          ) : null}
        </div>

        <div className="model-config-actions">
          <button className="btn ghost" type="button" onClick={onTest} disabled={busy}>
            {testing ? '测试中...' : '测试连接'}
          </button>
          <button className="btn primary" type="submit" disabled={busy || !provider || !model.trim()}>
            {saving ? '保存中...' : '保存配置'}
          </button>
        </div>
      </form>
    </div>
  )
}
