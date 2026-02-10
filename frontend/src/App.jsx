import { useEffect, useMemo, useState } from 'react'
import MarketCard from './components/MarketCard'
import StatCard from './components/StatCard'
import TradeTable from './components/TradeTable'

const emptyState = {
  stats: {
    balance: 0,
    today_pnl: 0,
    all_time_pnl: 0,
    trades: 0,
    win_rate: 0,
    avg_pnl: 0
  },
  markets: {},
  open_trades: [],
  history: []
}

function formatUsd(value) {
  return Number(value || 0).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })
}

export default function App() {
  const [state, setState] = useState(emptyState)
  const [running, setRunning] = useState(false)

  const markets = useMemo(() => {
    const list = Object.values(state.markets || {})
    const order = ['BTC', 'ETH', 'SOL']
    return list.sort((a, b) => order.indexOf(a.asset) - order.indexOf(b.asset))
  }, [state.markets])

  const refresh = async () => {
    const response = await fetch('/api/state')
    if (!response.ok) return
    const data = await response.json()
    setState(data)
  }

  const loadHealth = async () => {
    const response = await fetch('/api/health')
    if (!response.ok) return
    const data = await response.json()
    setRunning(Boolean(data.running))
  }

  const toggleBot = async () => {
    const route = running ? '/api/bot/stop' : '/api/bot/start'
    await fetch(route, { method: 'POST' })
    await loadHealth()
    await refresh()
  }

  useEffect(() => {
    loadHealth()
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [])

  const stats = state.stats || emptyState.stats

  return (
    <div className="app">
      <header className="header panel">
        <div>
          <h1>Polymarket Sniper</h1>
          <p>15-min crypto prediction markets</p>
        </div>
        <div className="header-actions">
          <span className={`status-dot ${running ? 'green' : 'red'}`} />
          <span className="mode">{running ? 'Sniper active (paper)' : 'Sniper paused'}</span>
          <button onClick={toggleBot}>{running ? 'Pause' : 'Start'}</button>
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Balance" value={formatUsd(stats.balance)} tone={stats.balance >= 0 ? 'green' : 'red'} />
        <StatCard label="Today P&L" value={formatUsd(stats.today_pnl)} tone={stats.today_pnl >= 0 ? 'green' : 'red'} />
        <StatCard label="All-time P&L" value={formatUsd(stats.all_time_pnl)} tone={stats.all_time_pnl >= 0 ? 'green' : 'red'} />
        <StatCard label="Trades" value={String(stats.trades)} />
        <StatCard label="Win Rate" value={`${(Number(stats.win_rate || 0) * 100).toFixed(1)}%`} tone="green" />
        <StatCard label="Avg P&L" value={formatUsd(stats.avg_pnl)} tone={stats.avg_pnl >= 0 ? 'green' : 'red'} />
      </section>

      <section className="panel">
        <div className="title-row">
          <h2>Current Window</h2>
        </div>
        <div className="market-grid">
          {markets.length === 0 ? <div className="empty-block">Aguardando dados do backend...</div> : markets.map((market) => <MarketCard key={market.asset} market={market} />)}
        </div>
      </section>

      <TradeTable trades={state.history || []} />
    </div>
  )
}
