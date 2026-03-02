import { Link } from 'react-router-dom'
import AOISelector from './AOISelector'
import LayerControls from './LayerControls'

export default function LeftPanel() {
  return (
    <aside className="w-72 flex-shrink-0 panel flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-surface-2">
        <Link to="/" className="flex items-center gap-2 group">
          <span className="text-lg font-bold text-white group-hover:text-accent-light transition-colors">
            InSAR Explorer
          </span>
        </Link>
        <p className="text-[10px] text-muted mt-0.5">Sentinel-1 deformation + ML anomaly detection</p>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        <AOISelector />
        <div className="border-t border-surface-2" />
        <LayerControls />
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-surface-2">
        <p className="text-[10px] text-muted leading-relaxed">
          Data: <span className="text-slate-400">ESA Sentinel-1, processed via ASF HyP3 + MintPy.</span>
          {' '}Anomaly detection via Isolation Forest on STL-decomposed time series.
        </p>
      </div>
    </aside>
  )
}
