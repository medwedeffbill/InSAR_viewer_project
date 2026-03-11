/**
 * MapView — MapLibre GL JS map with dynamic raster tile layers.
 *
 * Tile layers are served from Cloudflare R2 as pre-rendered PNGs:
 *   {R2_BASE}/{aoi_id}/tiles/{layer}/{z}/{x}/{y}.png
 *
 * Click handler converts map coordinates → raster pixel → fetches time series.
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import maplibregl, { Map, MapMouseEvent } from 'maplibre-gl'
import { useAppStore } from '@/store/useAppStore'
import { tileUrl, tsTileUrl, fetchPixelTimeSeries, fetchAOIMeta, latLngToPixelNative } from '@/lib/r2Client'
import type { AOI, LayerId } from '@/types'

const TILE_SIZE = 32

const BASEMAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

const LAYER_ORDER: LayerId[] = ['velocity', 'coherence', 'anomaly_score', 'seasonal_amplitude']

// Map our layer ids to R2 directory names
const LAYER_DIR: Record<LayerId, string> = {
  velocity:           'velocity_mm_yr',
  coherence:          'coherence_mean',
  anomaly_score:      'anomaly_score',
  seasonal_amplitude: 'seasonal_amplitude',
}

interface Props {
  className?: string
}

export default function MapView({ className = '' }: Props) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const map          = useRef<Map | null>(null)
  const activeAOI    = useAppStore((s) => s.selectedAOI)
  const [aoiMeta, setAoiMeta] = useState<AOI | null>(null)
  const activeLayers = useAppStore((s) => s.activeLayers)
  const viewport     = useAppStore((s) => s.viewport)
  const setViewport  = useAppStore((s) => s.setViewport)
  const setLoadingPixel   = useAppStore((s) => s.setLoadingPixel)
  const setSelectedPixel  = useAppStore((s) => s.setSelectedPixel)
  const setPixelStatus    = useAppStore((s) => s.setPixelStatus)

  // Map load sequencing: re-run tile/layer effects after style loads
  const [mapReady, setMapReady] = useState(false)

  // Debug badge state
  const [debug, setDebug] = useState({
    clickCount: 0,
    lastRow: null as number | null,
    lastCol: null as number | null,
    lastTileUrl: null as string | null,
    lastFetchResult: null as 'success' | 'no-data' | 'error' | null,
  })

  // ── Initialise map ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapContainer.current || map.current) return

    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style:     BASEMAP_STYLE,
      center:    [viewport.longitude, viewport.latitude],
      zoom:      viewport.zoom,
      attributionControl: {},
    })

    map.current.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.current.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')

    map.current.on('moveend', () => {
      if (!map.current) return
      const center = map.current.getCenter()
      setViewport({ longitude: center.lng, latitude: center.lat, zoom: map.current.getZoom() })
    })

    const applyStyleOnLoad = () => {
      if (!map.current) return
      // Add empty raster sources for each layer (URLs filled when AOI changes)
      LAYER_ORDER.forEach((layerId) => {
        if (map.current!.getSource(`src-${layerId}`)) return
        map.current!.addSource(`src-${layerId}`, {
          type:    'raster',
          tiles:   [],
          tileSize: 256,
        })
        map.current!.addLayer({
          id:     `lyr-${layerId}`,
          type:   'raster',
          source: `src-${layerId}`,
          paint:  { 'raster-opacity': 0 },
        })
      })
      setMapReady(true)
    }
    map.current.on('load', applyStyleOnLoad)

    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  // ── Fetch full AOI metadata when AOI changes (needed for pixel lookup) ─────
  useEffect(() => {
    if (!activeAOI) {
      setAoiMeta(null)
      return
    }
    import('@/lib/r2Client').then(({ aoiMetaUrl }) => {
      const url = aoiMetaUrl(activeAOI.id)
      console.log('[MapView] fetching AOI meta from:', url)
      console.log('[MapView] R2_BASE from env:', import.meta.env.VITE_R2_BASE_URL)
    })
    fetchAOIMeta(activeAOI.id)
      .then((meta) => {
        console.log('[MapView] fetched aoiMeta:', JSON.stringify(meta, null, 2))
        setAoiMeta(meta)
      })
      .catch((err) => {
        console.error('Failed to fetch AOI metadata:', err)
        setAoiMeta(null)
      })
  }, [activeAOI?.id])

  // ── Update tile sources when AOI changes (or map becomes ready) ─────────────
  useEffect(() => {
    const m = map.current
    if (!m || !mapReady || !m.isStyleLoaded()) return

    LAYER_ORDER.forEach((layerId) => {
      const srcId = `src-${layerId}`
      if (!m.getSource(srcId)) return

      if (activeAOI) {
        const dir = LAYER_DIR[layerId]
        const tileTemplate = tileUrl(activeAOI.id, dir, '{z}' as unknown as number, '{x}' as unknown as number, '{y}' as unknown as number)
          .replace('%7Bz%7D', '{z}')
          .replace('%7Bx%7D', '{x}')
          .replace('%7By%7D', '{y}')
          // Build a clean template string
          .replace(/\/\d+\/\d+\/\d+\.png$/, '/{z}/{x}/{y}.png')

        ;(m.getSource(srcId) as maplibregl.RasterTileSource).setTiles([tileTemplate])
      } else {
        ;(m.getSource(srcId) as maplibregl.RasterTileSource).setTiles([])
      }
    })

    if (activeAOI) {
      const [west, south, east, north] = activeAOI.bbox
      m.fitBounds([west, south, east, north], { padding: 60, duration: 1200 })
    }
  }, [activeAOI, mapReady])

  // ── Sync layer visibility / opacity (after map style loads) ──────────────────
  useEffect(() => {
    const m = map.current
    if (!m || !mapReady || !m.isStyleLoaded()) return

    activeLayers.forEach(({ id, visible, opacity }) => {
      const lyrId = `lyr-${id}`
      if (!m.getLayer(lyrId)) return
      m.setPaintProperty(lyrId, 'raster-opacity', visible ? opacity : 0)
    })
  }, [activeLayers, mapReady])

  // ── Click handler → pixel lookup ───────────────────────────────────────────
  const handleClick = useCallback(
    async (e: MapMouseEvent) => {
      console.log('[MapView] handleClick fired')
      if (!activeAOI) return

      const { lng, lat } = e.lngLat
      setDebug((d) => ({ ...d, clickCount: d.clickCount + 1 }))

      console.log('[MapView] aoiMeta at click time:', aoiMeta
        ? { shape: aoiMeta.shape, transform: aoiMeta.transform, crs_native: aoiMeta.crs_native, crs_proj4: aoiMeta.crs_proj4 }
        : null
      )

      // Bounds check — use aoiMeta.bbox (from aoi_metadata.json on R2) if available,
      // falling back to activeAOI.bbox (from aois.json or DEMO stub).
      const bboxSource = aoiMeta?.bbox ?? activeAOI.bbox
      const [west, south, east, north] = bboxSource
      console.log('[MapView] bounds check', { lng, lat, west, south, east, north, source: aoiMeta?.bbox ? 'aoiMeta' : 'activeAOI' })
      if (lng < west || lng > east || lat < south || lat > north) {
        console.log('[MapView] click outside AOI bounds, skipping')
        return
      }

      // Need full metadata with shape, transform, crs_native for pixel lookup
      if (!aoiMeta?.shape || !aoiMeta?.transform || !aoiMeta?.crs_native) {
        console.warn('[MapView] early return: AOI metadata missing', {
          hasShape: !!aoiMeta?.shape,
          hasTransform: !!aoiMeta?.transform,
          hasCrsNative: !!aoiMeta?.crs_native,
        })
        setPixelStatus('error', 'AOI metadata not loaded yet')
        setSelectedPixel(null)
        return
      }

      setLoadingPixel(true)
      setSelectedPixel(null)
      setPixelStatus('loading')

      try {
        const [row, col] = latLngToPixelNative(lat, lng, {
          transform: aoiMeta.transform,
          shape: aoiMeta.shape,
          crs_native: aoiMeta.crs_native,
          crs_proj4: aoiMeta.crs_proj4,
        })
        const tileRow = Math.floor(row / TILE_SIZE)
        const tileCol = Math.floor(col / TILE_SIZE)
        const tileUrlStr = tsTileUrl(activeAOI.id, tileRow, tileCol)
        setDebug((d) => ({ ...d, lastRow: row, lastCol: col, lastTileUrl: tileUrlStr }))

        const result = await fetchPixelTimeSeries(activeAOI.id, row, col, lat, lng)

        if (result.ok) {
          setSelectedPixel(result.data)
          setPixelStatus('success')
          setDebug((d) => ({ ...d, lastFetchResult: 'success' }))
        } else {
          setSelectedPixel(null)
          if (result.kind === 'http-error') {
            setPixelStatus('error', `HTTP ${result.status}: ${tileUrlStr}`)
            setDebug((d) => ({ ...d, lastFetchResult: 'error' }))
          } else {
            setPixelStatus('no-data', `Pixel ${result.key} not in tile ${result.tileRow}_${result.tileCol}`)
            setDebug((d) => ({ ...d, lastFetchResult: 'no-data' }))
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error('[MapView] pixel fetch failed:', err)
        setSelectedPixel(null)
        setPixelStatus('error', msg)
        setDebug((d) => ({ ...d, lastFetchResult: 'error' }))
      } finally {
        setLoadingPixel(false)
      }
    },
    [activeAOI, aoiMeta, setLoadingPixel, setSelectedPixel, setPixelStatus],
  )

  useEffect(() => {
    const m = map.current
    if (!m) return
    m.on('click', handleClick)
    return () => { m.off('click', handleClick) }
  }, [handleClick])

  // ── Cursor style on map hover ───────────────────────────────────────────────
  useEffect(() => {
    const m = map.current
    if (!m) return
    const setCrosshair = () => { m.getCanvas().style.cursor = activeAOI ? 'crosshair' : 'grab' }
    m.on('load', setCrosshair)
    setCrosshair()
  }, [activeAOI])

  return (
    <div className={`relative w-full h-full ${className}`}>
      <div
        ref={mapContainer}
        className="absolute inset-0"
        aria-label="InSAR deformation map"
      />
      {/* Temporary debug badge */}
      <div className="absolute bottom-4 left-4 z-10 bg-black/80 text-[10px] font-mono text-green-400 px-2 py-1.5 rounded border border-green-800/50 max-w-[300px] space-y-0.5">
        <div>clicks: {debug.clickCount}</div>
        <div>aoiMeta: {aoiMeta ? 'yes' : 'no'}</div>
        <div>hasShape: {aoiMeta?.shape ? 'yes' : 'NO'}</div>
        <div>hasTransform: {aoiMeta?.transform ? 'yes' : 'NO'}</div>
        <div>hasCrsNative: {aoiMeta?.crs_native ? 'yes' : 'NO'}</div>
        <div className="truncate" title={aoiMeta?.crs_native ?? ''}>
          crsNative: {aoiMeta?.crs_native ?? '-'}
        </div>
        <div>row/col: {debug.lastRow ?? '-'} / {debug.lastCol ?? '-'}</div>
        <div className="truncate" title={debug.lastTileUrl ?? ''}>
          tile: {debug.lastTileUrl ? debug.lastTileUrl.split('/').pop() : '-'}
        </div>
        <div>result: {debug.lastFetchResult ?? '-'}</div>
      </div>
    </div>
  )
}
