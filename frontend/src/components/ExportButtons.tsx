import type { PixelTimeSeries } from '@/types'

interface Props {
  data: PixelTimeSeries
}

function downloadCsv(data: PixelTimeSeries): void {
  const { dates, displacement, trend, seasonal, residual } = data

  const header = ['date', 'displacement_mm', 'trend_mm', 'seasonal_mm', 'residual_mm'].join(',')
  const rows = dates.map((d, i) =>
    [
      d,
      isNaN(displacement[i]) ? '' : displacement[i].toFixed(3),
      trend[i]?.toFixed(3)    ?? '',
      seasonal[i]?.toFixed(3) ?? '',
      residual[i]?.toFixed(3) ?? '',
    ].join(','),
  )

  const csv = [header, ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = `insar_ts_${data.lat.toFixed(4)}_${data.lng.toFixed(4)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export default function ExportButtons({ data }: Props) {
  return (
    <div className="flex gap-2 pt-1">
      <button
        onClick={() => downloadCsv(data)}
        className="btn-ghost text-xs"
        title="Download time series as CSV"
      >
        ↓ CSV
      </button>
      <span className="text-xs text-muted self-center">
        {data.dates.length} observations · {data.lat.toFixed(4)}°, {data.lng.toFixed(4)}°
      </span>
    </div>
  )
}
