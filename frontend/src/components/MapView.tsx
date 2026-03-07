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
import { tileUrl, fetchPixelTimeSeries, fetchAOIMeta, latLngToPixelNative } from '@/lib/r2Client'
import type { AOI, LayerId } from '@/types'

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

    map.current.on('load', () => {
      if (!map.current) return
      // Add empty raster sources for each layer (URLs filled when AOI changes)
      LAYER_ORDER.forEach((layerId) => {
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
    })

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
    fetchAOIMeta(activeAOI.id)
      .then(setAoiMeta)
      .catch((err) => {
        console.error('Failed to fetch AOI metadata:', err)
        setAoiMeta(null)
      })
  }, [activeAOI?.id])

  // ── Update tile sources when AOI changes ───────────────────────────────────
  useEffect(() => {
    const m = map.current
    if (!m || !m.isStyleLoaded()) return

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
  }, [activeAOI])

  // ── Sync layer visibility / opacity ────────────────────────────────────────
  useEffect(() => {
    const m = map.current
    if (!m || !m.isStyleLoaded()) return

    activeLayers.forEach(({ id, visible, opacity }) => {
      const lyrId = `lyr-${id}`
      if (!m.getLayer(lyrId)) return
      m.setPaintProperty(lyrId, 'raster-opacity', visible ? opacity : 0)
    })
  }, [activeLayers])

  // ── Click handler → pixel lookup ───────────────────────────────────────────
  const handleClick = useCallback(
    async (e: MapMouseEvent) => {
      if (!activeAOI) return

      const { lng, lat } = e.lngLat

      console.debug('[MapView] map clicked', {
        lng,
        lat,
        aoiMetaLoaded: !!aoiMeta,
        hasShape: !!aoiMeta?.shape,
        hasTransform: !!aoiMeta?.transform,
        hasCrsNative: !!aoiMeta?.crs_native,
      })

      // Bounds check
      const [west, south, east, north] = activeAOI.bbox
      if (lng < west || lng > east || lat < south || lat > north) return

      // Need full metadata with shape, transform, crs_native for pixel lookup
      if (!aoiMeta?.shape || !aoiMeta?.transform || !aoiMeta?.crs_native) {
        console.warn('AOI metadata missing shape/transform/crs_native — pixel lookup unavailable')
        setSelectedPixel(null)
        return
      }

      setLoadingPixel(true)
      setSelectedPixel(null)

      try {
        const [row, col] = latLngToPixelNative(lat, lng, {
          transform: aoiMeta.transform,
          shape: aoiMeta.shape,
          crs_native: aoiMeta.crs_native,
          crs_proj4: aoiMeta.crs_proj4,
        })
        const ts = await fetchPixelTimeSeries(activeAOI.id, row, col, lat, lng)
        if (ts === null) {
          console.warn('[MapView] pixel lookup returned null — no time series for this pixel')
        }
        setSelectedPixel(ts)
      } catch (err) {
        console.error('[MapView] pixel fetch failed:', err)
        setSelectedPixel(null)
      } finally {
        setLoadingPixel(false)
      }
    },
    [activeAOI, aoiMeta, setLoadingPixel, setSelectedPixel],
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
    <div
      ref={mapContainer}
      className={`w-full h-full ${className}`}
      aria-label="InSAR deformation map"
    />
  )
}
