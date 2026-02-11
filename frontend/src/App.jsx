import { useEffect, useMemo, useState } from 'react'
import MarketCard from './components/MarketCard'
import StatCard from './components/StatCard'
import TradeTable from './components/TradeTable'

const allAssets = ['BTC', 'ETH', 'SOL']

const emptyState = {
  stats: { balance: 0, today_pnl: 0, all_time_pnl: 0, trades: 0, win_rate: 0, avg_pnl: 0 },
  config: {
    enabled_assets: allAssets,
    enabled_indicators: ['POLY_PRICE'],
    confidence_threshold: 0.85,
    entry_probability_threshold: 0.85,
    late_entry_seconds: 180,
    stop_loss_pct: 0.2
  },
  execution_config: { mode: 'TEST', wallet_configured: false, wallet_masked: '' },
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
  const [executionDraft, setExecutionDraft] = useState({ mode: 'TEST', wallet_secret: '' })
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
    if (data.config && !configDirty) setConfigDraft(data.config)
    if (data.execution_config && !configDirty) {
      setExecutionDraft((prev) => ({ ...prev, mode: data.execution_config.mode }))
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

  const setNumeric = (key, value) => {
    setConfigDirty(true)
    setConfigDraft((prev) => ({ ...prev, [key]: value }))
  }

  const saveConfig = async () => {
    const payload = {
      ...configDraft,
      enabled_indicators: ['POLY_PRICE'],
      confidence_threshold: Number(configDraft.confidence_threshold),
      entry_probability_threshold: Number(configDraft.entry_probability_threshold),
      late_entry_seconds: Number(configDraft.late_entry_seconds),
      stop_loss_pct: Number(configDraft.stop_loss_pct)
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

  const saveExecutionConfig = async () => {
    const response = await fetch('/api/execution-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(executionDraft)
    })

    if (!response.ok) {
      setSaveMsg('Erro ao salvar modo/carteira')
      return
    }

    setSaveMsg('Modo/carteira salvos ✅')
    setExecutionDraft((prev) => ({ ...prev, wallet_secret: '' }))
    await refresh()
    setTimeout(() => setSaveMsg(''), 2500)
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [configDirty])

  const stats = state.stats || emptyState.stats

  return (
    <div className="app">
      <header className="header panel">
        <div>
          <h1>Polymarket Sniper</h1>
          <p>Gamma: dados | CLOB: execução</p>
        </div>
        <div className="header-actions">
          <span className={`status-dot ${running ? 'green' : 'red'}`} />
          <span className="mode">{running ? 'Ativo' : 'Pausado'}</span>
          <span className="mode">Modo: {state.execution_config?.mode || 'TEST'}</span>
          <span className="mode">Ticks: {state.tick_count || 0}</span>
          <span className="mode">Último tick: {fmtTime(state.last_tick_at)}</span>
          <button onClick={forceTick}>Tick now</button>
          <button onClick={toggleBot}>{running ? 'Pause' : 'Start'}</button>
        </div>
      </header>

      <section className="panel controls">
        <div className="control-block">
          <h3>Ativos</h3>
          <div className="chips">
            {allAssets.map((asset) => (
              <button type="button" key={asset} className={configDraft.enabled_assets.includes(asset) ? 'chip active' : 'chip'} onClick={() => toggleAsset(asset)}>{asset}</button>
            ))}
          </div>
        </div>

        <div className="control-block">
          <h3>Probabilidade mínima (YES/NO)</h3>
          <input type="number" min="0.5" max="1" step="0.01" value={configDraft.entry_probability_threshold} onChange={(e) => setNumeric('entry_probability_threshold', e.target.value)} />
        </div>

        <div className="control-block">
          <h3>Janela de entrada (seg)</h3>
          <input type="number" min="30" max="900" step="10" value={configDraft.late_entry_seconds} onChange={(e) => setNumeric('late_entry_seconds', e.target.value)} />
        </div>

        <div className="control-block">
          <h3>Stop loss (%)</h3>
          <input type="number" min="0" max="95" step="1" value={Number(configDraft.stop_loss_pct) * 100} onChange={(e) => setNumeric('stop_loss_pct', Number(e.target.value) / 100)} />
        </div>

        <button className="save" type="button" onClick={saveConfig}>Salvar estratégia</button>
      </section>

      <section className="panel controls execution-controls">
        <div className="control-block">
          <h3>Modo de execução</h3>
          <select value={executionDraft.mode} onChange={(e) => setExecutionDraft((prev) => ({ ...prev, mode: e.target.value }))}>
            <option value="TEST">TESTE</option>
            <option value="REAL">REAL</option>
          </select>
        </div>
        <div className="control-block span-2">
          <h3>Carteira Poly (private key)</h3>
          <input type="password" placeholder="cole sua chave privada" value={executionDraft.wallet_secret} onChange={(e) => setExecutionDraft((prev) => ({ ...prev, wallet_secret: e.target.value }))} />
          <small className="muted-text">Configurada: {state.execution_config?.wallet_configured ? state.execution_config.wallet_masked : 'não'}</small>
        </div>
        <button className="save" type="button" onClick={saveExecutionConfig}>Salvar modo/carteira</button>
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
