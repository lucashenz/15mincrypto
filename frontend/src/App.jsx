import { useEffect, useMemo, useState } from 'react'
import MarketCard from './components/MarketCard'
import StatCard from './components/StatCard'
import TradeTable from './components/TradeTable'
import WinLossChart from './components/WinLossChart'

const allAssets = ['BTC', 'ETH', 'SOL']

const emptyState = {
  stats: { balance: 0, today_pnl: 0, all_time_pnl: 0, trades: 0, wins: 0, win_rate: 0, avg_pnl: 0 },
  config: {
    enabled_assets: allAssets,
    entry_threshold: 0.9,
    entry_window_seconds: 180,
    use_macd_confirmation: true,
    confidence_threshold: 0.9
  },
  markets: {},
  history: [],
  running: false,
  tick_count: 0,
  last_tick_at: null,
  last_decision_by_asset: {}
}

function formatUsd(value) {
  return Number(value || 0).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })
}

function fmtTime(value) {
  if (!value) return '--'
  return new Date(value).toLocaleTimeString('pt-BR', { hour12: false })
}

export default function App() {
  const [state, setState] = useState(emptyState)
  const [running, setRunning] = useState(false)
  const [configDraft, setConfigDraft] = useState(emptyState.config)
  const [configDirty, setConfigDirty] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

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
    setRunning(Boolean(data.running))
    if (data.config && !configDirty) {
      setConfigDraft(data.config)
    }
  }

  const toggleBot = async () => {
    const route = running ? '/api/bot/stop' : '/api/bot/start'
    await fetch(route, { method: 'POST' })
    await refresh()
  }

  const forceTick = async () => {
    await fetch('/api/bot/tick', { method: 'POST' })
    await refresh()
  }

  const toggleAsset = (asset) => {
    setConfigDirty(true)
    setConfigDraft((prev) => {
      const has = prev.enabled_assets.includes(asset)
      const next = has ? prev.enabled_assets.filter((a) => a !== asset) : [...prev.enabled_assets, asset]
      return { ...prev, enabled_assets: next }
    })
  }

  const saveConfig = async () => {
    const payload = {
      ...configDraft,
      confidence_threshold: Number(configDraft.confidence_threshold),
      entry_threshold: Number(configDraft.entry_threshold) || 0.9,
      entry_window_seconds: Number(configDraft.entry_window_seconds) || 180,
      use_macd_confirmation: Boolean(configDraft.use_macd_confirmation),
      enabled_indicators: configDraft.enabled_indicators || ['MACD', 'POLY_PRICE']
    }
    const response = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Erro ao salvar configuração' }))
      setSaveMsg(`Erro: ${err.detail || 'falha de validação'}`)
      return
    }

    setConfigDirty(false)
    setSaveMsg('Configuração salva ✅')
    await refresh()
    setTimeout(() => setSaveMsg(''), 2500)
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 1000)
    return () => clearInterval(id)
  }, [configDirty])

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
          <span className="mode">Ticks: {state.tick_count || 0}</span>
          <span className="mode">Último tick: {fmtTime(state.last_tick_at)}</span>
          <span className="mode">Janela: {state.window_seconds_remaining ?? '--'}s</span>
          <button onClick={forceTick}>Tick now</button>
          <button onClick={toggleBot}>{running ? 'Pause' : 'Start'}</button>
        </div>
      </header>

      <section className="panel controls">
        <div className="control-block">
          <h3>Ativos para operar</h3>
          <div className="chips">
            {allAssets.map((asset) => (
              <button type="button" key={asset} className={configDraft.enabled_assets.includes(asset) ? 'chip active' : 'chip'} onClick={() => toggleAsset(asset)}>{asset}</button>
            ))}
          </div>
        </div>

        <div className="control-block">
          <h3>Usar MACD</h3>
          <button
            type="button"
            className={`chip ${configDraft.use_macd_confirmation ? 'active' : ''}`}
            onClick={() => {
              setConfigDirty(true)
              setConfigDraft((p) => ({ ...p, use_macd_confirmation: !p.use_macd_confirmation }))
            }}
          >
            {configDraft.use_macd_confirmation ? 'Sim' : 'Não'}
          </button>
        </div>

        <div className="control-block">
          <h3>% mínimo para entrada</h3>
          <input
            type="number"
            min="0.5"
            max="1"
            step="0.05"
            value={configDraft.entry_threshold ?? 0.9}
            onChange={(e) => {
              setConfigDirty(true)
              setConfigDraft((prev) => ({ ...prev, entry_threshold: e.target.value }))
            }}
          />
          <small className="hint-inline">Ex: 0.9 = 90%</small>
        </div>

        <div className="control-block">
          <h3>Janela (seg)</h3>
          <input
            type="number"
            min="60"
            max="300"
            step="30"
            value={configDraft.entry_window_seconds ?? 180}
            onChange={(e) => {
              setConfigDirty(true)
              setConfigDraft((prev) => ({ ...prev, entry_window_seconds: e.target.value }))
            }}
          />
          <small className="hint-inline">Faltando X seg</small>
        </div>

        <button className="save" type="button" onClick={saveConfig}>Salvar configuração</button>
      </section>

      {saveMsg ? <section className="panel save-msg">{saveMsg}</section> : null}

      <section className="stats-grid">
        <StatCard label="Balance" value={formatUsd(stats.balance)} tone={stats.balance >= 0 ? 'green' : 'red'} />
        <StatCard label="Today P&L" value={formatUsd(stats.today_pnl)} tone={stats.today_pnl >= 0 ? 'green' : 'red'} />
        <StatCard label="All-time P&L" value={formatUsd(stats.all_time_pnl)} tone={stats.all_time_pnl >= 0 ? 'green' : 'red'} />
        <StatCard label="Trades" value={String(stats.trades)} />
        <StatCard label="Win Rate" value={`${(Number(stats.win_rate || 0) * 100).toFixed(1)}%`} tone="green" />
        <StatCard label="Avg P&L" value={formatUsd(stats.avg_pnl)} tone={stats.avg_pnl >= 0 ? 'green' : 'red'} />
      </section>

      <section className="panel">
        <h3 className="title-row">Gráfico Acertos x Erros</h3>
        <WinLossChart wins={stats.wins ?? 0} losses={Math.max(0, (stats.trades ?? 0) - (stats.wins ?? 0))} />
      </section>

      <section className="panel">
        <div className="title-row">
          <h2>Current Window</h2>
        </div>
        <div className="market-grid">
          {markets.length === 0 ? <div className="empty-block">Aguardando dados do backend...</div> : markets.map((market) => <MarketCard key={market.asset} market={market} decision={state.last_decision_by_asset?.[market.asset]} />)}
        </div>
      </section>

      <TradeTable trades={state.history || []} />
    </div>
  )
}
