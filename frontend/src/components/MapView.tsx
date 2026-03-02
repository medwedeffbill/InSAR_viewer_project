/**
 * MapView — MapLibre GL JS map with dynamic raster tile layers.
 *
 * Tile layers are served from Cloudflare R2 as pre-rendered PNGs:
 *   {R2_BASE}/{aoi_id}/tiles/{layer}/{z}/{x}/{y}.png
 *
 * Click handler converts map coordinates → raster pixel → fetches time series.
 */

import { useEffect, useRef, useCallback } from 'react'
import maplibregl, { Map, MapMouseEvent } from 'maplibre-gl'
import { useAppStore } from '@/store/useAppStore'
import { tileUrl, fetchPixelTimeSeries, latLngToPixel } from '@/lib/r2Client'
import type { LayerId } from '@/types'

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
      attributionControl: true,
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

        const cleanUrl = `${import.meta.env.VITE_R2_BASE_URL ?? ''}/${activeAOI.id}/tiles/${dir}/{z}/{x}/{y}.png`
        ;(m.getSource(srcId) as maplibregl.RasterTileSource).setTiles([cleanUrl])
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

      // Bounds check
      const [west, south, east, north] = activeAOI.bbox
      if (lng < west || lng > east || lat < south || lat > north) return

      setLoadingPixel(true)
      setSelectedPixel(null)

      try {
        // Derive raster pixel from lat/lng using the velocity COG geotransform
        // We store the geotransform in aoi_metadata.json; for now approximate from bbox + shape
        const shapeApprox = { T: 100, rows: 400, cols: 400 }  // will be overwritten by real meta
        const transform = [
          west,
          (east - west) / shapeApprox.cols,
          0,
          north,
          0,
          -(north - south) / shapeApprox.rows,
        ]
        const [row, col] = latLngToPixel(lat, lng, { transform, shape: shapeApprox })
        const ts = await fetchPixelTimeSeries(activeAOI.id, row, col, lat, lng)
        setSelectedPixel(ts)
      } catch (err) {
        console.error('Pixel fetch failed:', err)
        setSelectedPixel(null)
      }
    },
    [activeAOI, setLoadingPixel, setSelectedPixel],
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
