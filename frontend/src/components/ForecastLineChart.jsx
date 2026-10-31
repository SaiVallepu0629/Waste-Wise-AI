function buildPath(points, xForDate, yForValue) {
  return points.map((point, index) => {
    const command = index === 0 ? 'M' : 'L'
    return `${command}${xForDate(point.date).toFixed(2)},${yForValue(point.value).toFixed(2)}`
  }).join(' ')
}

export default function ForecastLineChart({
  title,
  description,
  lines,
  emptyMessage,
}) {
  const width = 820
  const height = 270
  const margin = { top: 20, right: 24, bottom: 40, left: 48 }
  const allPoints = lines.flatMap((line) => line.points)

  if (allPoints.length === 0) {
    return <div className="chart-empty">{emptyMessage}</div>
  }

  const dates = allPoints.map((point) => new Date(`${point.date}T00:00:00`).getTime())
  const minimumDate = Math.min(...dates)
  const maximumDate = Math.max(...dates)
  const maximumValue = Math.max(1, ...allPoints.map((point) => point.value))
  const chartWidth = width - margin.left - margin.right
  const chartHeight = height - margin.top - margin.bottom
  const xForDate = (date) => {
    const timestamp = new Date(`${date}T00:00:00`).getTime()
    const span = maximumDate - minimumDate
    return margin.left + (span === 0 ? 0.5 : (timestamp - minimumDate) / span) * chartWidth
  }
  const yForValue = (value) => (
    margin.top + chartHeight - (value / maximumValue) * chartHeight
  )
  const yTicks = Array.from({ length: 5 }, (_, index) => (
    Math.round((maximumValue * index) / 4)
  ))
  const xTickCount = 5
  const xTicks = Array.from({ length: xTickCount }, (_, index) => {
    const timestamp = minimumDate + ((maximumDate - minimumDate) * index) / (xTickCount - 1)
    const date = new Date(timestamp)
    return {
      x: margin.left + (chartWidth * index) / (xTickCount - 1),
      label: `${date.getUTCMonth() + 1}/${date.getUTCDate()}`,
    }
  })

  return (
    <div className="forecast-chart">
      <div className="chart-heading">
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
      </div>
      <div className="forecast-legend">
        {lines.map((line) => (
          <span key={line.name}>
            <i className={`legend-line ${line.className}`} />
            {line.name}
          </span>
        ))}
      </div>
      <div className="forecast-svg-wrap">
        <svg
          aria-label={title}
          className="forecast-svg"
          role="img"
          viewBox={`0 0 ${width} ${height}`}
        >
          <title>{title}</title>
          {yTicks.map((tick) => {
            const y = yForValue(tick)
            return (
              <g key={tick}>
                <line
                  className="chart-grid-line"
                  x1={margin.left}
                  x2={width - margin.right}
                  y1={y}
                  y2={y}
                />
                <text className="chart-axis-label" textAnchor="end" x={margin.left - 8} y={y + 3}>
                  {tick}
                </text>
              </g>
            )
          })}
          {xTicks.map((tick) => (
            <text
              className="chart-axis-label"
              key={`${tick.x}-${tick.label}`}
              textAnchor="middle"
              x={tick.x}
              y={height - 13}
            >
              {tick.label}
            </text>
          ))}
          {lines.map((line) => (
            <path
              className={`chart-series ${line.className}`}
              d={buildPath(line.points, xForDate, yForValue)}
              key={line.name}
            />
          ))}
        </svg>
      </div>
    </div>
  )
}
