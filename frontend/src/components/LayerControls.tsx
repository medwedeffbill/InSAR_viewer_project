import { useAppStore } from '@/store/useAppStore'
import { getColorScale } from '@/lib/colorScales'
import type { LayerId } from '@/types'
import clsx from 'clsx'

const LAYER_META: Record<LayerId, { label: string; description: string }> = {
  velocity: {
    label: 'LOS Velocity',
    description: 'Mean line-of-sight displacement rate (mm/yr). Blue = moving toward satellite (uplift/eastward), red = moving away (subsidence/westward).',
  },
  coherence: {
    label: 'Coherence',
    description: 'Mean temporal coherence [0–1]. Low coherence indicates decorrelated pixels — treat data there with caution.',
  },
  anomaly_score: {
    label: 'Anomaly Score',
    description: 'ML Isolation Forest score [0–1]. High values flag pixels with unusual deformation patterns (high residual, change points, rapid trends).',
  },
  seasonal_amplitude: {
    label: 'Seasonal Amplitude',
    description: 'Peak-to-peak amplitude of the annual sinusoidal component (mm). Large values indicate strong hydrological or thermal loading cycles.',
  },
}

export default function LayerControls() {
  const activeLayers    = useAppStore((s) => s.activeLayers)
  const setLayerVisible = useAppStore((s) => s.setLayerVisible)
  const setLayerOpacity = useAppStore((s) => s.setLayerOpacity)
  const selectedAOI     = useAppStore((s) => s.selectedAOI)

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-muted">Layers</h3>

      {activeLayers.map((layer) => {
        const meta  = LAYER_META[layer.id]
        const scale = getColorScale(layer.id === 'velocity' ? 'velocity_mm_yr' : layer.id)
        const disabled = !selectedAOI

        return (
          <div
            key={layer.id}
            className={clsx(
              'rounded-lg border p-3 space-y-2 transition-all',
              layer.visible && !disabled
                ? 'border-accent/40 bg-surface-2'
                : 'border-surface-2 bg-surface-1 opacity-60',
            )}
          >
            {/* Toggle row */}
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <button
                  role="checkbox"
                  aria-checked={layer.visible}
                  disabled={disabled}
                  onClick={() => setLayerVisible(layer.id, !layer.visible)}
                  className={clsx(
                    'w-8 h-4 rounded-full transition-colors duration-200 relative flex-shrink-0',
                    layer.visible ? 'bg-accent' : 'bg-surface-3',
                    disabled && 'cursor-not-allowed',
                  )}
                >
                  <span
                    className={clsx(
                      'block w-3 h-3 bg-white rounded-full absolute top-0.5 transition-transform duration-200',
                      layer.visible ? 'translate-x-4' : 'translate-x-0.5',
                    )}
                  />
                </button>
                <span className="text-sm font-medium text-slate-200">{meta.label}</span>
              </label>
            </div>

            {/* Colour scale legend */}
            {layer.visible && scale && !disabled && (
              <div className="space-y-1">
                <div
                  className="h-2 w-full rounded-full"
                  style={{ background: scale.gradient }}
                />
                <div className="flex justify-between text-[10px] text-muted">
                  {scale.ticks.map((t) => (
                    <span key={t.value}>{t.label}</span>
                  ))}
                </div>
                {scale.unit && (
                  <p className="text-[10px] text-muted text-right">{scale.unit}</p>
                )}
              </div>
            )}

            {/* Opacity slider */}
            {layer.visible && !disabled && (
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-muted w-10">Opacity</span>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={layer.opacity}
                  onChange={(e) => setLayerOpacity(layer.id, parseFloat(e.target.value))}
                  className="flex-1 h-1 accent-accent"
                />
                <span className="text-[10px] text-muted w-7 text-right">
                  {Math.round(layer.opacity * 100)}%
                </span>
              </div>
            )}

            {/* Description tooltip on hover */}
            <p className="text-[10px] text-muted leading-relaxed hidden group-hover:block">
              {meta.description}
            </p>
          </div>
        )
      })}

      {!selectedAOI && (
        <p className="text-xs text-muted text-center pt-1">Select an AOI to enable layers.</p>
      )}
    </div>
  )
}
