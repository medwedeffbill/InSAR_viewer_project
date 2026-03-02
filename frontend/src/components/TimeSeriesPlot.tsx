/**
 * Displacement time series + STL decomposition plots.
 */

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from 'recharts'
import type { PixelTimeSeries } from '@/types'

interface Props {
  data: PixelTimeSeries
  showDecomposition?: boolean
}

// Format YYYYMMDD → "Jan 2022"
function formatDate(raw: string): string {
  if (raw.length === 8) {
    const y = raw.slice(0, 4)
    const m = parseInt(raw.slice(4, 6)) - 1
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return `${months[m]} ${y}`
  }
  return raw
}

// Tick formatter: show every ~6th label to avoid crowding
function makeTickFormatter(dates: string[]) {
  return (value: string, index: number) => {
    if (index % Math.max(1, Math.floor(dates.length / 8)) !== 0) return ''
    return formatDate(value)
  }
}

const TOOLTIP_STYLE = {
  backgroundColor: '#1a1d2e',
  border: '1px solid #2e3250',
  borderRadius: '8px',
  fontSize: '12px',
  color: '#e2e8f0',
}

export default function TimeSeriesPlot({ data, showDecomposition = false }: Props) {
  const { dates, displacement, trend, seasonal, residual, anomaly } = data

  const mainChartData = dates.map((d, i) => ({
    date: d,
    displacement: isNaN(displacement[i]) ? null : +displacement[i].toFixed(2),
    trend:    trend.length    ? +trend[i].toFixed(2)    : undefined,
    seasonal: seasonal.length ? +seasonal[i].toFixed(2) : undefined,
  }))

  const residualData = residual.length
    ? dates.map((d, i) => ({ date: d, residual: +residual[i].toFixed(2) }))
    : []

  const tickFormatter = makeTickFormatter(dates)

  return (
    <div className="space-y-4">
      {/* Main: displacement + trend */}
      <div>
        <h5 className="text-xs font-semibold text-muted uppercase tracking-widest mb-2">
          LOS Displacement
        </h5>
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={mainChartData} margin={{ top: 4, right: 8, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2e3250" />
            <XAxis
              dataKey="date"
              tickFormatter={tickFormatter}
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={{ stroke: '#2e3250' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#64748b', fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              unit=" mm"
              width={52}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(v: number) => [`${v} mm`, '']}
              labelFormatter={formatDate}
            />
            <ReferenceLine y={0} stroke="#2e3250" strokeDasharray="4 4" />

            {anomaly?.change_point_date && (
              <ReferenceLine
                x={anomaly.change_point_date.replace(/-/g, '')}
                stroke="#f59e0b"
                strokeDasharray="5 3"
                label={{ value: 'CP', fill: '#f59e0b', fontSize: 9 }}
              />
            )}

            <Line
              type="monotone"
              dataKey="displacement"
              stroke="#6366f1"
              strokeWidth={1.5}
              dot={false}
              name="Displacement"
              connectNulls={false}
            />
            {trend.length > 0 && (
              <Line
                type="monotone"
                dataKey="trend"
                stroke="#f43f5e"
                strokeWidth={1.5}
                dot={false}
                strokeDasharray="5 3"
                name="Trend"
              />
            )}
            {seasonal.length > 0 && (
              <Line
                type="monotone"
                dataKey="seasonal"
                stroke="#10b981"
                strokeWidth={1}
                dot={false}
                strokeDasharray="2 4"
                name="Seasonal"
              />
            )}
            <Legend wrapperStyle={{ fontSize: 10, color: '#94a3b8' }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Residual */}
      {showDecomposition && residualData.length > 0 && (
        <div>
          <h5 className="text-xs font-semibold text-muted uppercase tracking-widest mb-2">
            Residual
          </h5>
          <ResponsiveContainer width="100%" height={80}>
            <LineChart data={residualData} margin={{ top: 0, right: 8, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2e3250" />
              <XAxis
                dataKey="date"
                tickFormatter={tickFormatter}
                tick={{ fill: '#64748b', fontSize: 9 }}
                axisLine={{ stroke: '#2e3250' }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: '#64748b', fontSize: 9 }}
                axisLine={false}
                tickLine={false}
                unit=" mm"
                width={52}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v: number) => [`${v} mm`, 'Residual']}
                labelFormatter={formatDate}
              />
              <ReferenceLine y={0} stroke="#2e3250" />
              <Line
                type="monotone"
                dataKey="residual"
                stroke="#94a3b8"
                strokeWidth={1}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
