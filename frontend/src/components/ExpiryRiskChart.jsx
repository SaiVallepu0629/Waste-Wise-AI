export default function ExpiryRiskChart({ riskCounts, snapshotCounts }) {
  const riskEntries = Object.entries(riskCounts || {})
  const snapshotEntries = Object.entries(snapshotCounts || {})
  const totalRiskRows = riskEntries.reduce((total, [, count]) => total + count, 0)
  const totalSnapshots = snapshotEntries.reduce((total, [, count]) => total + count, 0)

  if (riskEntries.length === 0) {
    return <div className="chart-empty">No expiry-risk labels are available.</div>
  }

  return (
    <div className="risk-chart">
      <div className="chart-group">
        <div className="chart-heading">
          <div>
            <h3>Source risk labels</h3>
            <p>Counts from the dataset; these are not new predictions.</p>
          </div>
          <strong>{totalRiskRows.toLocaleString()} batches</strong>
        </div>
        {riskEntries.map(([label, count]) => (
          <div className="bar-row" key={label}>
            <span>{label}</span>
            <div className="bar-track">
              <div
                className={`bar-fill ${label.startsWith('Flagged') ? 'risk' : 'safe'}`}
                style={{ width: `${totalRiskRows ? (count / totalRiskRows) * 100 : 0}%` }}
              />
            </div>
            <strong>{count.toLocaleString()}</strong>
          </div>
        ))}
      </div>

      <div className="chart-group snapshot-group">
        <div className="chart-heading">
          <div>
            <h3>Snapshot timeline</h3>
            <p>Historical and future-dated rows are shown separately.</p>
          </div>
          <strong>{totalSnapshots.toLocaleString()} rows</strong>
        </div>
        {snapshotEntries.map(([label, count]) => (
          <div className="bar-row" key={label}>
            <span>{label.replaceAll('_', ' ')}</span>
            <div className="bar-track">
              <div
                className={`bar-fill ${label === 'future_snapshot' ? 'future' : 'safe'}`}
                style={{ width: `${totalSnapshots ? (count / totalSnapshots) * 100 : 0}%` }}
              />
            </div>
            <strong>{count.toLocaleString()}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}
