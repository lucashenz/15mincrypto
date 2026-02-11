function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
  return Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function formatPct(v) {
  return `${(Number(v || 0) * 100).toFixed(1)}%`
}

export default function MarketCard({ market, decision }) {
  const down = Number(market.change_24h) < 0

  return (
    <article className="panel market-card">
      <header className="row top">
        <div>
          <div className="asset">{market.asset}</div>
          <div className="sub">Up or Down · 15m</div>
        </div>
        <div className="badge-row">
          <span className={`pill ${market.odds_live ? 'green' : 'red'}`}>{market.odds_live ? 'LIVE' : 'FALLBACK'}</span>
          <span className="pill subtle">{market.odds_source || 'UNKNOWN'}</span>
        </div>
      </header>

      <div className="price">{formatMoney(market.spot_price)}</div>
      <div className={`change ${down ? 'red' : 'green'}`}>{Number(market.change_24h).toFixed(3)}%</div>

      <div className="odds-grid">
        <div className="odds-row">
          <span>UP</span>
          <strong>{formatPct(market.yes_odds)}</strong>
        </div>
        <div className="odds-row">
          <span>DOWN</span>
          <strong>{formatPct(market.no_odds)}</strong>
        </div>
      </div>

      <footer className="meta-row">
        <span className="meta-item">price: {market.price_source || 'UNKNOWN'}</span>
        <span className="meta-item">age: {market.price_age_seconds ?? '--'}s</span>
        <span className="meta-item">window: {market.window_ts ?? '--'}</span>
      </footer>

      <div className="decision">{decision || 'NO_DECISION_YET'}</div>
    </article>
  )
}
