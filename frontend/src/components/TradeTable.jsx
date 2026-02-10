function fmtTime(value) {
  if (!value) return '--'
  const dt = new Date(value)
  return dt.toLocaleTimeString('en-GB', { hour12: false })
}

export default function TradeTable({ trades }) {
  return (
    <div className="panel table-wrap">
      <div className="title-row">
        <h3>Trade History</h3>
      </div>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Asset</th>
            <th>Side</th>
            <th>Mode</th>
            <th>Status</th>
            <th>P&L</th>
          </tr>
        </thead>
        <tbody>
          {trades.length === 0 ? (
            <tr>
              <td colSpan="6" className="empty">Sem trades ainda</td>
            </tr>
          ) : (
            trades.slice(0, 20).map((trade) => (
              <tr key={trade.id}>
                <td>{fmtTime(trade.closed_at || trade.opened_at)}</td>
                <td>{trade.asset}</td>
                <td>{trade.direction}</td>
                <td>{trade.api_mode}</td>
                <td>{trade.status}</td>
                <td className={Number(trade.pnl) >= 0 ? 'green' : 'red'}>
                  {Number(trade.pnl).toFixed(2)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
