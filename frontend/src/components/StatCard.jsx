export default function StatCard({ label, value, hint, tone = 'neutral' }) {
  return (
    <div className="panel stat-card">
      <span className="label">{label}</span>
      <strong className={`value ${tone}`}>{value}</strong>
      {hint ? <small className="hint">{hint}</small> : null}
    </div>
  )
}
