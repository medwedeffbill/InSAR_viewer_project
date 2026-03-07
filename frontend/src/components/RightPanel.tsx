import { useState } from 'react'
import { useAppStore } from '@/store/useAppStore'
import TimeSeriesPlot from './TimeSeriesPlot'
import WhyFlaggedBadge from './WhyFlaggedBadge'
import ExportButtons from './ExportButtons'

export default function RightPanel() {
  const selectedPixel    = useAppStore((s) => s.selectedPixel)
  const pixelStatus      = useAppStore((s) => s.pixelStatus)
  const pixelMessage     = useAppStore((s) => s.pixelMessage)
  const selectedAOI     = useAppStore((s) => s.selectedAOI)
  const setSelectedPixel = useAppStore((s) => s.setSelectedPixel)

  const [showDecomp, setShowDecomp] = useState(false)

  // Panel is hidden when no AOI selected
  if (!selectedAOI) return null

  return (
    <aside className="w-96 flex-shrink-0 panel flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-surface-2 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Pixel Inspector</h3>
          <p className="text-[10px] text-muted">Click a pixel on the map</p>
        </div>
        {selectedPixel && (
          <button
            onClick={() => setSelectedPixel(null)}
            className="text-muted hover:text-white transition-colors text-lg leading-none"
            aria-label="Close inspector"
          >
            ×
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {/* Loading state */}
        {pixelStatus === 'loading' && (
          <div className="flex flex-col items-center justify-center h-40 gap-3">
            <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            <p className="text-xs text-muted">Loading time series…</p>
          </div>
        )}

        {/* No-data state */}
        {pixelStatus === 'no-data' && !selectedPixel && (
          <div className="flex flex-col items-center justify-center h-40 gap-2 text-center">
            <div className="text-3xl opacity-30">◎</div>
            <p className="text-sm text-amber-400">No time series found for that pixel</p>
            {pixelMessage && <p className="text-xs text-muted">{pixelMessage}</p>}
          </div>
        )}

        {/* Error state */}
        {pixelStatus === 'error' && !selectedPixel && (
          <div className="flex flex-col items-center justify-center h-40 gap-2 text-center">
            <div className="text-3xl opacity-30">⚠</div>
            <p className="text-sm text-red-400">Error loading pixel</p>
            {pixelMessage && <p className="text-xs text-muted break-all px-2">{pixelMessage}</p>}
          </div>
        )}

        {/* Idle empty state */}
        {pixelStatus === 'idle' && !selectedPixel && (
          <div className="flex flex-col items-center justify-center h-40 gap-2 text-center">
            <div className="text-3xl opacity-30">◎</div>
            <p className="text-sm text-muted">Click any pixel within the AOI</p>
            <p className="text-xs text-muted/70">to view displacement time series and anomaly details</p>
          </div>
        )}

        {/* Data */}
        {selectedPixel && (
          <div className="space-y-5">
            {/* Anomaly badge (if flagged) */}
            {selectedPixel.anomaly && selectedPixel.anomaly.score >= 0.5 && (
              <>
                <WhyFlaggedBadge anomaly={selectedPixel.anomaly} />
                <div className="border-t border-surface-2" />
              </>
            )}

            {/* Normal pixel with no anomaly */}
            {(!selectedPixel.anomaly || selectedPixel.anomaly.score < 0.5) && (
              <div className="flex items-center gap-2 bg-success/10 border border-success/20 rounded-lg px-3 py-2">
                <span className="text-success text-sm">✓</span>
                <p className="text-xs text-slate-300">No significant anomaly detected at this pixel.</p>
              </div>
            )}

            {/* Time series plot */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-semibold uppercase tracking-widest text-muted">
                  Time Series
                </h4>
                <button
                  onClick={() => setShowDecomp((v) => !v)}
                  className="text-[10px] text-accent-light hover:text-accent transition-colors"
                >
                  {showDecomp ? 'Hide' : 'Show'} decomposition
                </button>
              </div>
              <TimeSeriesPlot data={selectedPixel} showDecomposition={showDecomp} />
            </div>

            <div className="border-t border-surface-2" />
            <ExportButtons data={selectedPixel} />
          </div>
        )}
      </div>
    </aside>
  )
}
