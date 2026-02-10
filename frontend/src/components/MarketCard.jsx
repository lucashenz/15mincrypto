function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

export default function MarketCard({ market }) {
  const down = Number(market.change_24h) < 0
  return (
    <div className="panel market-card">
      <div className="row top">
        <span className="asset">{market.asset}</span>
        <div className="row badge-row">
          <span className={`pill ${market.odds_live ? 'green' : 'red'}`}>{market.odds_live ? 'LIVE' : 'FALLBACK'}</span>
          <span className="pill">{market.odds_source || 'UNKNOWN'}</span>
          <span className={`pill ${down ? 'red' : 'green'}`}>{down ? 'DOWN' : 'UP'}</span>
        </div>
      </div>
      <div className="price">{formatMoney(market.spot_price)}</div>
      <div className={`change ${down ? 'red' : 'green'}`}>
        {Number(market.change_24h).toFixed(3)}%
      </div>
      <div className="row mini">
        <span>YES</span>
        <strong>{Math.round(Number(market.yes_odds || 0) * 100)}¢</strong>
      </div>
      <div className="row mini">
        <span>NO</span>
        <strong>{Math.round(Number(market.no_odds || 0) * 100)}¢</strong>
      </div>
    </div>
  )
}
