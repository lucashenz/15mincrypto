export default function WinLossChart({ wins = 0, losses = 0 }) {
  const total = wins + losses
  const winPct = total ? (wins / total) * 100 : 0
  const lossPct = total ? (losses / total) * 100 : 0

  return (
    <div className="win-loss-chart">
      <div className="chart-legend">
        <span className="legend-item green">Acertos: {wins}</span>
        <span className="legend-item red">Erros: {losses}</span>
      </div>
      <div className="chart-bars">
        <div
          className="bar bar-win"
          style={{ width: `${winPct}%` }}
          title={`${wins} acertos (${winPct.toFixed(0)}%)`}
        />
        <div
          className="bar bar-loss"
          style={{ width: `${lossPct}%` }}
          title={`${losses} erros (${lossPct.toFixed(0)}%)`}
        />
      </div>
      <div className="chart-labels">
        <span style={{ width: `${winPct}%` }}>{winPct > 10 ? `${winPct.toFixed(0)}%` : ''}</span>
        <span style={{ width: `${lossPct}%` }}>{lossPct > 10 ? `${lossPct.toFixed(0)}%` : ''}</span>
      </div>
    </div>
  )
}
