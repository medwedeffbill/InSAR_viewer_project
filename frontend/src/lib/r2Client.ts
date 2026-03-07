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

import proj4 from 'proj4'
import type { AOI, PixelTimeSeries } from '@/types'

const R2_BASE = import.meta.env.VITE_R2_BASE_URL ?? 'https://your-r2-public-url'

// Fallback PROJ4 strings for known EPSG codes (used when crs_proj4 not in metadata)
const EPSG_PROJ4_FALLBACKS: Record<string, string> = {
  'EPSG:32610': '+proj=utm +zone=10 +datum=WGS84 +units=m +no_defs',
  'EPSG:32611': '+proj=utm +zone=11 +datum=WGS84 +units=m +no_defs',
  'EPSG:4326': '+proj=longlat +datum=WGS84 +no_defs',
}

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

/** For geographic CRS (e.g. WGS84) where transform is in lon/lat. */
export function latLngToPixel(lat: number, lng: number, meta: RasterMeta): [number, number] {
  const [x0, dx, , y0, , dy] = meta.transform
  const col = Math.round((lng - x0) / dx)
  const row = Math.round((lat - y0) / dy)
  return [
    Math.max(0, Math.min(row, meta.shape.rows - 1)),
    Math.max(0, Math.min(col, meta.shape.cols - 1)),
  ]
}

/**
 * Ensure the native CRS is registered with proj4.
 * Uses crs_proj4 from metadata if present, otherwise fallback map for known EPSG codes.
 */
function ensureCrsRegistered(meta: { crs_native: string; crs_proj4?: string }): void {
  const { crs_native, crs_proj4 } = meta
  if (proj4.defs(crs_native)) return // already registered

  if (crs_proj4) {
    proj4.defs(crs_native, crs_proj4)
    return
  }

  const fallback = EPSG_PROJ4_FALLBACKS[crs_native]
  if (fallback) {
    proj4.defs(crs_native, fallback)
    return
  }

  throw new Error(
    `CRS "${crs_native}" is not registered. Provide crs_proj4 in aoi_metadata.json or add to EPSG_PROJ4_FALLBACKS.`,
  )
}

/**
 * Convert lat/lng to raster row/col when the raster uses a projected CRS (e.g. UTM).
 * Uses proj4 to transform from WGS84 to the native CRS before applying the affine.
 */
export function latLngToPixelNative(
  lat: number,
  lng: number,
  meta: RasterMeta & { crs_native: string; crs_proj4?: string },
): [number, number] {
  const { crs_native, crs_proj4 } = meta
  const [x0, dx, , y0, , dy] = meta.transform

  ensureCrsRegistered(meta)

  let x: number
  let y: number
  try {
    ;[x, y] = proj4('EPSG:4326', crs_native, [lng, lat])
  } catch (err) {
    console.error('[latLngToPixelNative] proj4 transform failed:', {
      crs_native,
      crs_proj4: crs_proj4 ?? '(not in metadata)',
      input: { lng, lat },
      error: err,
    })
    throw err
  }

  const col = Math.round((x - x0) / dx)
  const row = Math.round((y - y0) / dy)
  const clampedRow = Math.max(0, Math.min(row, meta.shape.rows - 1))
  const clampedCol = Math.max(0, Math.min(col, meta.shape.cols - 1))

  console.debug('[latLngToPixelNative]', {
    crs_native,
    crs_proj4: crs_proj4 ?? '(fallback)',
    input: { lng, lat },
    output: { x, y },
    row,
    col,
    clamped: { row: clampedRow, col: clampedCol },
  })

  return [clampedRow, clampedCol]
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
  const logCtx = { aoiId, row, col, tileRow, tileCol, localRow, localCol, url }

  const res = await fetch(url)
  if (!res.ok) {
    console.warn('[fetchPixelTimeSeries] HTTP error:', { ...logCtx, status: res.status, statusText: res.statusText })
    return null
  }

  const tile: TileJson = await res.json()
  const key = `${localRow}_${localCol}`
  const px = tile.pixels[key]

  if (!px) {
    const pixelKeys = Object.keys(tile.pixels ?? {}).slice(0, 5)
    console.warn('[fetchPixelTimeSeries] pixel not in tile:', {
      ...logCtx,
      key,
      pixelExists: false,
      tilePixelCount: Object.keys(tile.pixels ?? {}).length,
      sampleKeys: pixelKeys,
    })
    return null
  }

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
