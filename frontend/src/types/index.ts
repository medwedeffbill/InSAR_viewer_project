// ─── AOI / Layer types ───────────────────────────────────────────────────────

export interface LayerInfo {
  id: string
  name: string
  unit: string
  vmin: number
  vmax: number
  colorscale: string
}

export interface AOI {
  id: string
  name: string
  description: string
  bbox: [number, number, number, number]  // [west, south, east, north]
  center: [number, number]                // [lng, lat]
  zoom: number
  featured: boolean
  case_study: string | null
  date_range: [string, string]
  layers: LayerInfo[]
  /** Raster shape for pixel lookup (from aoi_metadata.json) */
  shape?: { T: number; rows: number; cols: number }
  /** Affine transform [x0, dx, 0, y0, 0, dy] in native CRS */
  transform?: number[]
  /** Native CRS e.g. EPSG:32610 (UTM) */
  crs_native?: string
  /** Tile size for ts_tiles (default 32) */
  tile_size?: number
}

// ─── Active layer state ──────────────────────────────────────────────────────

export type LayerId = 'velocity' | 'coherence' | 'anomaly_score' | 'seasonal_amplitude'

export interface ActiveLayer {
  id: LayerId
  opacity: number
  visible: boolean
}

// ─── Pixel time series ───────────────────────────────────────────────────────

export interface AnomalyInfo {
  score: number
  labels: string[]
  change_point_date: string | null
}

export interface PixelTimeSeries {
  dates: string[]
  displacement: number[]
  trend: number[]
  seasonal: number[]
  residual: number[]
  anomaly: AnomalyInfo | null
  lat: number
  lng: number
}

// ─── Map state ───────────────────────────────────────────────────────────────

export interface MapViewport {
  longitude: number
  latitude: number
  zoom: number
}
