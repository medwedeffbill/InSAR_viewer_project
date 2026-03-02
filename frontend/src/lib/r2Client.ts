/**
 * Client for fetching data from Cloudflare R2 public bucket.
 *
 * R2 bucket structure expected:
 *   /{aoi_id}/aoi_metadata.json
 *   /{aoi_id}/tiles/{layer}/{z}/{x}/{y}.png
 *   /{aoi_id}/ts_tiles/{tile_row}_{tile_col}.json
 *   /{aoi_id}/timeseries.zarr/
 *   aois.json
 */

import type { AOI, PixelTimeSeries } from '@/types'

const R2_BASE = import.meta.env.VITE_R2_BASE_URL ?? 'https://your-r2-public-url'

// ── URL builders ─────────────────────────────────────────────────────────────

export function aoiListUrl(): string {
  return `${R2_BASE}/aois.json`
}

export function aoiMetaUrl(aoiId: string): string {
  return `${R2_BASE}/${aoiId}/aoi_metadata.json`
}

export function tileUrl(aoiId: string, layer: string, z: number, x: number, y: number): string {
  return `${R2_BASE}/${aoiId}/tiles/${layer}/${z}/${x}/${y}.png`
}

export function tsTileUrl(aoiId: string, tileRow: number, tileCol: number): string {
  return `${R2_BASE}/${aoiId}/ts_tiles/${tileRow}_${tileCol}.json`
}

export function zarrBaseUrl(aoiId: string): string {
  return `${R2_BASE}/${aoiId}/timeseries.zarr`
}

// ── Coordinate helpers ───────────────────────────────────────────────────────

interface RasterMeta {
  transform: number[]   // [x0, dx, 0, y0, 0, dy]
  shape: { T: number; rows: number; cols: number }
}

export function latLngToPixel(lat: number, lng: number, meta: RasterMeta): [number, number] {
  const [x0, dx, , y0, , dy] = meta.transform
  const col = Math.round((lng - x0) / dx)
  const row = Math.round((lat - y0) / dy)
  return [
    Math.max(0, Math.min(row, meta.shape.rows - 1)),
    Math.max(0, Math.min(col, meta.shape.cols - 1)),
  ]
}

// ── Data fetchers ────────────────────────────────────────────────────────────

export async function fetchAOIList(): Promise<AOI[]> {
  const res = await fetch(aoiListUrl())
  if (!res.ok) throw new Error(`Failed to fetch AOI list: ${res.status}`)
  return res.json()
}

export async function fetchAOIMeta(aoiId: string): Promise<AOI> {
  const res = await fetch(aoiMetaUrl(aoiId))
  if (!res.ok) throw new Error(`Failed to fetch AOI metadata for ${aoiId}: ${res.status}`)
  return res.json()
}

interface TileJsonPixel {
  d: (number | null)[]
  trend?: number[]
  seasonal?: number[]
  residual?: number[]
  anomaly?: {
    score: number
    labels: string[]
    change_point_date: string | null
  }
}

interface TileJson {
  tile_row: number
  tile_col: number
  r0: number
  c0: number
  dates: string[]
  pixels: Record<string, TileJsonPixel>
}

const TILE_SIZE = 32

/**
 * Fetch the pixel time series for a given raster (row, col).
 * Finds the correct tile JSON and extracts the pixel within it.
 */
export async function fetchPixelTimeSeries(
  aoiId: string,
  row: number,
  col: number,
  lat: number,
  lng: number,
): Promise<PixelTimeSeries | null> {
  const tileRow = Math.floor(row / TILE_SIZE)
  const tileCol = Math.floor(col / TILE_SIZE)
  const localRow = row % TILE_SIZE
  const localCol = col % TILE_SIZE

  const url = tsTileUrl(aoiId, tileRow, tileCol)
  const res = await fetch(url)
  if (!res.ok) return null

  const tile: TileJson = await res.json()
  const key = `${localRow}_${localCol}`
  const px = tile.pixels[key]
  if (!px) return null

  const displacement = px.d.map((v) => v ?? NaN)

  return {
    dates: tile.dates,
    displacement,
    trend: px.trend ?? [],
    seasonal: px.seasonal ?? [],
    residual: px.residual ?? [],
    anomaly: px.anomaly ?? null,
    lat,
    lng,
  }
}
