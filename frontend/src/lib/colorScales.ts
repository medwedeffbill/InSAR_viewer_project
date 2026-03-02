/**
 * Colour scale legend data for the map layer legend strip.
 * Each entry maps to a CSS linear-gradient string and tick labels.
 */

export interface ColorScaleDef {
  gradient: string
  ticks: { value: number; label: string }[]
  unit: string
}

export const COLOR_SCALES: Record<string, ColorScaleDef> = {
  velocity_mm_yr: {
    gradient: 'linear-gradient(to right, #053061, #2166ac, #4393c3, #92c5de, #d1e5f0, #f7f7f7, #fddbc7, #f4a582, #d6604d, #b2182b, #67001f)',
    ticks: [
      { value: 0, label: '-30' },
      { value: 25, label: '-15' },
      { value: 50, label: '0' },
      { value: 75, label: '+15' },
      { value: 100, label: '+30' },
    ],
    unit: 'mm/yr',
  },
  coherence: {
    gradient: 'linear-gradient(to right, #1a1d2e, #4a5568, #a0aec0, #e2e8f0, #ffffff)',
    ticks: [
      { value: 0, label: '0' },
      { value: 50, label: '0.5' },
      { value: 100, label: '1.0' },
    ],
    unit: '',
  },
  anomaly_score: {
    gradient: 'linear-gradient(to right, #ffffd4, #fed976, #feb24c, #fd8d3c, #f03b20, #bd0026)',
    ticks: [
      { value: 0, label: '0' },
      { value: 50, label: '0.5' },
      { value: 100, label: '1.0' },
    ],
    unit: '',
  },
  seasonal_amplitude: {
    gradient: 'linear-gradient(to right, #440154, #3b528b, #21918c, #5ec962, #fde725)',
    ticks: [
      { value: 0, label: '0' },
      { value: 50, label: '10' },
      { value: 100, label: '20' },
    ],
    unit: 'mm',
  },
}

export function getColorScale(layerId: string): ColorScaleDef | null {
  return COLOR_SCALES[layerId] ?? null
}
