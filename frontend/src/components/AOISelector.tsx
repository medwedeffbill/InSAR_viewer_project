import { useAppStore } from '@/store/useAppStore'
import { Link } from 'react-router-dom'
import clsx from 'clsx'

export default function AOISelector() {
  const aois       = useAppStore((s) => s.aois)
  const selected   = useAppStore((s) => s.selectedAOI)
  const selectAOI  = useAppStore((s) => s.selectAOI)

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-muted">Area of Interest</h3>

      {aois.length === 0 ? (
        <p className="text-xs text-muted">Loading AOIs…</p>
      ) : (
        <div className="space-y-1.5">
          {aois.map((aoi) => (
            <button
              key={aoi.id}
              onClick={() => selectAOI(aoi.id)}
              className={clsx(
                'w-full text-left rounded-lg px-3 py-2.5 transition-all duration-150 border',
                selected?.id === aoi.id
                  ? 'border-accent bg-accent/10 text-white'
                  : 'border-surface-2 bg-surface-1 text-slate-300 hover:border-accent/30 hover:bg-surface-2',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium leading-tight">{aoi.name}</p>
                  {aoi.date_range.length === 2 && (
                    <p className="text-[10px] text-muted mt-0.5">
                      {aoi.date_range[0]} → {aoi.date_range[1]}
                    </p>
                  )}
                </div>
                {aoi.featured && (
                  <span className="badge bg-accent/20 text-accent-light flex-shrink-0 mt-0.5">
                    Featured
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {selected?.case_study && (
        <Link
          to={`/cases/${selected.case_study}`}
          className="block text-center text-xs text-accent-light hover:text-accent mt-2 underline underline-offset-2"
        >
          Read case study →
        </Link>
      )}
    </div>
  )
}
