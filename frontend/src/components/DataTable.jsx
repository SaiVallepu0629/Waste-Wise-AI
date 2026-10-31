export default function DataTable({
  columns,
  rows,
  rowKey,
  emptyMessage,
  maxRows = 100,
}) {
  const visibleRows = rows.slice(0, maxRows)

  if (rows.length === 0) {
    return <div className="table-empty">{emptyMessage}</div>
  }

  return (
    <>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((column) => <th key={column.key}>{column.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={row[rowKey] ?? index}>
                {columns.map((column) => (
                  <td key={column.key}>
                    {column.render ? column.render(row) : (row[column.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > maxRows && (
        <p className="table-footnote">
          Showing {maxRows} of {rows.length.toLocaleString()} matching records.
        </p>
      )}
    </>
  )
}
