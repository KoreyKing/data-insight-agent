// Renders a finding's chart from the backend echarts_spec.
// On render failure: catch, report CHART_RENDER_FAILED upward, show a degraded placeholder — never crash the report.
import { Component, type ReactNode } from 'react'
import ReactECharts from 'echarts-for-react'

type FindingChartProps = {
  spec: Record<string, unknown>
  title?: string
  onRenderError?: (chartTitle: string) => void
}

type BoundaryProps = {
  fallback: ReactNode
  onError?: () => void
  children: ReactNode
}

type BoundaryState = { failed: boolean }

class ChartErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false }

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true }
  }

  componentDidCatch() {
    this.props.onError?.()
  }

  render() {
    if (this.state.failed) return this.props.fallback
    return this.props.children
  }
}

function DegradedPlaceholder({ title }: { title?: string }) {
  return (
    <div className="chart-degraded">
      <span>图表渲染失败，已降级</span>
      {title ? <small>{title}</small> : null}
    </div>
  )
}

export default function FindingChart({ spec, title, onRenderError }: FindingChartProps) {
  if (!spec || typeof spec !== 'object' || Object.keys(spec).length === 0) {
    return <DegradedPlaceholder title={title} />
  }
  return (
    <ChartErrorBoundary
      fallback={<DegradedPlaceholder title={title} />}
      onError={() => onRenderError?.(title || '')}
    >
      <ReactECharts
        option={spec}
        notMerge
        lazyUpdate
        style={{ height: 220, width: '100%' }}
        opts={{ renderer: 'svg' }}
      />
    </ChartErrorBoundary>
  )
}
