// Tiny inline-SVG sparkline used in the KPI strip. Ported from design charts.jsx.

type SparklineProps = {
  data: number[]
  width?: number
  height?: number
  color: string
}

export default function Sparkline({ data, width = 120, height = 22, color }: SparklineProps) {
  if (!data || data.length < 2) return null
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const stepX = width / (data.length - 1)
  const pts = data.map((v, i): [number, number] => [
    i * stepX,
    height - ((v - min) / range) * (height - 3) - 1.5,
  ])
  const d = pts
    .map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ' ' + p[1].toFixed(1))
    .join(' ')
  const area = d + ` L ${width} ${height} L 0 ${height} Z`
  const last = pts[pts.length - 1]
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <path d={area} fill={color} fillOpacity="0.12" />
      <path d={d} fill="none" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="2.4" fill={color} />
    </svg>
  )
}
