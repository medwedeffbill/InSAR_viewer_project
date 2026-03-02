import { create } from 'zustand'
import type { AOI, ActiveLayer, LayerId, PixelTimeSeries, MapViewport } from '@/types'

interface AppState {
  // ── AOIs ──────────────────────────────────────────────────────────────────
  aois: AOI[]
  selectedAOI: AOI | null
  setAOIs: (aois: AOI[]) => void
  selectAOI: (id: string) => void

  // ── Layers ────────────────────────────────────────────────────────────────
  activeLayers: ActiveLayer[]
  setLayerVisible: (id: LayerId, visible: boolean) => void
  setLayerOpacity: (id: LayerId, opacity: number) => void

  // ── Selected pixel ────────────────────────────────────────────────────────
  selectedPixel: PixelTimeSeries | null
  isLoadingPixel: boolean
  setSelectedPixel: (data: PixelTimeSeries | null) => void
  setLoadingPixel: (loading: boolean) => void

  // ── Map viewport ──────────────────────────────────────────────────────────
  viewport: MapViewport
  setViewport: (v: Partial<MapViewport>) => void
}

const DEFAULT_LAYERS: ActiveLayer[] = [
  { id: 'velocity',           opacity: 0.8, visible: true  },
  { id: 'coherence',          opacity: 0.6, visible: false },
  { id: 'anomaly_score',      opacity: 0.8, visible: false },
  { id: 'seasonal_amplitude', opacity: 0.7, visible: false },
]

export const useAppStore = create<AppState>((set, get) => ({
  // ── AOIs ──────────────────────────────────────────────────────────────────
  aois: [],
  selectedAOI: null,
  setAOIs: (aois) => set({ aois }),
  selectAOI: (id) => {
    const aoi = get().aois.find((a) => a.id === id) ?? null
    set({ selectedAOI: aoi, selectedPixel: null })
  },

  // ── Layers ────────────────────────────────────────────────────────────────
  activeLayers: DEFAULT_LAYERS,
  setLayerVisible: (id, visible) =>
    set((s) => ({
      activeLayers: s.activeLayers.map((l) => (l.id === id ? { ...l, visible } : l)),
    })),
  setLayerOpacity: (id, opacity) =>
    set((s) => ({
      activeLayers: s.activeLayers.map((l) => (l.id === id ? { ...l, opacity } : l)),
    })),

  // ── Selected pixel ────────────────────────────────────────────────────────
  selectedPixel: null,
  isLoadingPixel: false,
  setSelectedPixel: (data) => set({ selectedPixel: data, isLoadingPixel: false }),
  setLoadingPixel: (loading) => set({ isLoadingPixel: loading }),

  // ── Map viewport ──────────────────────────────────────────────────────────
  viewport: { longitude: -122.25, latitude: 47.55, zoom: 5 },
  setViewport: (v) => set((s) => ({ viewport: { ...s.viewport, ...v } })),
}))
