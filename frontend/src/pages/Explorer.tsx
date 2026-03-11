/**
 * Explorer — full-screen map + left panel + right panel.
 * Loads AOI list on mount and selects by URL param if provided.
 */

import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useAppStore } from '@/store/useAppStore'
import { fetchAOIList } from '@/lib/r2Client'
import MapView from '@/components/MapView'
import LeftPanel from '@/components/LeftPanel'
import RightPanel from '@/components/RightPanel'

export default function Explorer() {
  const { aoiId }    = useParams<{ aoiId?: string }>()
  const setAOIs      = useAppStore((s) => s.setAOIs)
  const selectAOI    = useAppStore((s) => s.selectAOI)
  const aois         = useAppStore((s) => s.aois)

  // Load AOI list on mount
  useEffect(() => {
    if (aois.length > 0) return   // already loaded
    fetchAOIList()
      .then((list) => {
        setAOIs(list)
        if (aoiId) {
          selectAOI(aoiId)
        } else if (list.length > 0) {
          // Auto-select first featured AOI
          const featured = list.find((a) => a.featured) ?? list[0]
          selectAOI(featured.id)
        }
      })
      .catch((err) => {
        console.error('Failed to load AOI list:', err)
        // Load demo stubs so the UI is usable without a live R2 bucket
        setAOIs(DEMO_AOIS)
        selectAOI(DEMO_AOIS[0].id)
      })
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  // Respond to URL param changes after load
  useEffect(() => {
    if (aoiId && aois.length > 0) {
      selectAOI(aoiId)
    }
  }, [aoiId, aois.length])   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="h-screen flex overflow-hidden bg-surface">
      <LeftPanel />

      {/* Map takes all remaining space */}
      <div className="relative flex-1 overflow-hidden">
        <MapView className="absolute inset-0" />
      </div>

      <RightPanel />
    </div>
  )
}

// ── Demo stubs (used when R2 is not configured) ────────────────────────────

import type { AOI } from '@/types'

const DEMO_AOIS: AOI[] = [
  {
    id: 'portuguese_bend',
    name: 'Portuguese Bend Landslide, CA',
    description: 'One of the most active slow-moving landslides in the US. LOS rates exceed 100 mm/yr in the active lobe.',
    bbox: [-118.45, 33.69, -118.23, 33.80],
    center: [-118.34, 33.745],
    zoom: 12,
    featured: true,
    case_study: 'landslide-creep',
    date_range: ['20190101', '20251231'],
    layers: [
      { id: 'velocity',           name: 'LOS Velocity',       unit: 'mm/yr', vmin: -150, vmax: 10, colorscale: 'plasma' },
      { id: 'coherence',          name: 'Mean Coherence',     unit: '',      vmin: 0,    vmax: 1,  colorscale: 'Greys'  },
      { id: 'anomaly_score',      name: 'Anomaly Score',      unit: '',      vmin: 0,    vmax: 1,  colorscale: 'YlOrRd'},
      { id: 'seasonal_amplitude', name: 'Seasonal Amplitude', unit: 'mm',    vmin: 0,    vmax: 50, colorscale: 'viridis'},
    ],
  },
]
