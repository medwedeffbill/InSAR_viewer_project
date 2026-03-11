import { Link } from 'react-router-dom'
import type { AOI } from '@/types'

const FEATURED_AOIS: Pick<AOI, 'id' | 'name' | 'description' | 'case_study'>[] = [
  {
    id: 'portuguese_bend',
    name: 'Portuguese Bend Landslide, CA',
    description: 'One of the most active slow-moving landslides in the US, with LOS rates exceeding 100 mm/yr in the active lobe.',
    case_study: 'landslide-creep',
  },
]

function InSARExplainer() {
  return (
    <section className="grid md:grid-cols-3 gap-6 mt-16">
      {[
        {
          icon: '📡',
          title: 'What InSAR measures',
          body: "Interferometric Synthetic Aperture Radar (InSAR) uses phase differences between repeat satellite radar acquisitions to measure surface displacement along the satellite's line-of-sight (LOS) direction. Sentinel-1 revisits every 6–12 days at 5.6 cm wavelength, resolving motion at millimeter precision.",
        },
        {
          icon: '🤖',
          title: 'What "anomaly" means',
          body: "Each pixel's displacement time series is decomposed into trend, seasonal, and residual components (STL). An Isolation Forest model scores pixels by how unusual their feature vector is — high residual variance, large trend magnitude, accelerating rates, or change points all elevate the score.",
        },
        {
          icon: '⚠️',
          title: 'Limitations to know',
          body: 'InSAR measures LOS displacement, not vertical or horizontal independently. Low coherence (vegetation, snow, water) masks data. Atmospheric delay (troposphere, ionosphere) can mimic or mask deformation signals. Unwrapping errors alias phase by ±2.8 cm.',
        },
      ].map(({ icon, title, body }) => (
        <div key={title} className="panel p-5 space-y-2">
          <div className="text-2xl">{icon}</div>
          <h3 className="font-semibold text-white">{title}</h3>
          <p className="text-sm text-slate-400 leading-relaxed">{body}</p>
        </div>
      ))}
    </section>
  )
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-surface text-slate-200">
      {/* Nav */}
      <nav className="border-b border-surface-2 px-6 py-4 flex items-center justify-between">
        <span className="text-lg font-bold text-white">InSAR Deformation Explorer</span>
        <div className="flex gap-4 text-sm">
          <Link to="/explore" className="text-accent-light hover:text-accent transition-colors">
            Open Explorer
          </Link>
          <a
            href="https://github.com"
            target="_blank"
            rel="noreferrer"
            className="text-muted hover:text-slate-300 transition-colors"
          >
            GitHub
          </a>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-6 py-16">
        {/* Hero */}
        <div className="text-center space-y-5">
          <span className="badge bg-accent/20 text-accent-light border border-accent/30 text-xs px-3 py-1">
            Sentinel-1 · InSAR · ML Anomaly Detection
          </span>
          <h1 className="text-4xl md:text-5xl font-bold text-white leading-tight">
            Detecting slow moving landslides with{' '}
            <span className="text-accent-light">radar imaging</span>
          </h1>
          <p className="text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
            I built this web app to visualize ground displacement histories from InSAR data,
            and showcase my work applying ML-powered anomaly detection to InSAR time histories.
          </p>
          <div className="flex gap-3 justify-center flex-wrap">
            <Link to="/explore" className="btn-primary text-base px-6 py-2.5">
              Open Explorer →
            </Link>
            <a
              href="#featured"
              className="btn-ghost text-base px-6 py-2.5"
            >
              See featured sites
            </a>
          </div>
        </div>

        {/* Featured AOI cards */}
        <section id="featured" className="mt-20">
          <h2 className="text-2xl font-bold text-white mb-6">Featured sites</h2>
          <div className="grid md:grid-cols-1 max-w-md gap-5">
            {FEATURED_AOIS.map((aoi) => (
              <div key={aoi.id} className="panel p-5 flex flex-col gap-3 hover:border-accent/40 transition-colors group">
                <div className="space-y-1">
                  <h3 className="font-semibold text-white group-hover:text-accent-light transition-colors">
                    {aoi.name}
                  </h3>
                  <p className="text-sm text-slate-400 leading-relaxed">{aoi.description}</p>
                </div>
                <div className="flex gap-2 mt-auto pt-2 border-t border-surface-2">
                  <Link
                    to={`/explore/${aoi.id}`}
                    className="btn-primary text-xs flex-1 justify-center"
                  >
                    Explore
                  </Link>
                  {aoi.case_study && (
                    <Link
                      to={`/cases/${aoi.case_study}`}
                      className="btn-ghost text-xs flex-1 justify-center"
                    >
                      Case study
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Explainer */}
        <InSARExplainer />

        {/* Tech stack */}
        <section className="mt-20 panel p-6">
          <h2 className="text-lg font-bold text-white mb-4">How it's built</h2>
          <div className="grid sm:grid-cols-2 gap-x-8 gap-y-3 text-sm text-slate-400">
            {[
              ['Data source',     'ESA Sentinel-1 C-band SAR (6-day repeat)'],
              ['Processing',      'ASF HyP3 → MintPy SBAS time series'],
              ['ML pipeline',     'STL decomposition · Isolation Forest · ruptures change-point'],
              ['Storage',         'Cloud Optimized GeoTIFFs + Zarr on Cloudflare R2'],
              ['Map tiles',       'Pre-rendered PNG tiles via rio-tiler'],
              ['Frontend',        'React 18 · MapLibre GL JS · Recharts · Tailwind'],
              ['Hosting',         'Vercel (frontend) · Cloudflare R2 (data)'],
            ].map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <span className="text-slate-500 min-w-28">{k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-surface-2 px-6 py-6 text-center text-xs text-muted">
        Data: Copernicus Sentinel-1 (ESA), processed via ASF HyP3 and MintPy.
        Contains modified Copernicus Sentinel data.
      </footer>
    </div>
  )
}
