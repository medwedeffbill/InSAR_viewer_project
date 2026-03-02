import type { AnomalyInfo } from '@/types'

const SCORE_COLOR = (score: number) => {
  if (score >= 0.85) return 'bg-danger/20 text-red-300 border-danger/40'
  if (score >= 0.65) return 'bg-warning/20 text-yellow-300 border-warning/40'
  return 'bg-success/20 text-green-300 border-success/40'
}

const SCORE_LABEL = (score: number) => {
  if (score >= 0.85) return 'High anomaly'
  if (score >= 0.65) return 'Moderate anomaly'
  return 'Low anomaly'
}

interface Props {
  anomaly: AnomalyInfo
}

export default function WhyFlaggedBadge({ anomaly }: Props) {
  const colorClass = SCORE_COLOR(anomaly.score)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-widest text-muted">Anomaly detection</h4>
        <span className={`badge border text-xs font-semibold ${colorClass}`}>
          {SCORE_LABEL(anomaly.score)} ({(anomaly.score * 100).toFixed(0)}%)
        </span>
      </div>

      {/* Score bar */}
      <div className="w-full h-1.5 bg-surface-3 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${anomaly.score * 100}%`,
            background: anomaly.score >= 0.85 ? '#f43f5e' : anomaly.score >= 0.65 ? '#f59e0b' : '#10b981',
          }}
        />
      </div>

      {/* Reason labels */}
      {anomaly.labels.length > 0 ? (
        <ul className="space-y-1">
          {anomaly.labels.map((label, i) => (
            <li key={i} className="flex items-start gap-1.5 text-xs text-slate-300">
              <span className="mt-0.5 text-warning flex-shrink-0">›</span>
              {label}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted">No specific reason flags triggered.</p>
      )}

      {anomaly.change_point_date && (
        <div className="flex items-center gap-1.5 mt-1 text-xs text-slate-400 bg-surface-2 rounded-lg px-2.5 py-1.5">
          <span className="text-warning">⚡</span>
          Change point: <span className="text-slate-200 font-medium">{anomaly.change_point_date}</span>
        </div>
      )}
    </div>
  )
}
