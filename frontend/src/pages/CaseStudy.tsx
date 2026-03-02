import { useParams, Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CASE_STUDIES } from '@/content/caseStudies'

export default function CaseStudyPage() {
  const { slug } = useParams<{ slug: string }>()
  const study = CASE_STUDIES[slug ?? '']

  if (!study) {
    return (
      <div className="min-h-screen bg-surface flex flex-col items-center justify-center gap-4">
        <p className="text-slate-400">Case study not found: {slug}</p>
        <Link to="/" className="btn-ghost text-sm">← Back to home</Link>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-surface text-slate-200">
      {/* Nav */}
      <nav className="border-b border-surface-2 px-6 py-4 flex items-center gap-4">
        <Link to="/" className="text-muted hover:text-slate-300 text-sm transition-colors">
          ← Home
        </Link>
        <span className="text-muted">/</span>
        <Link to={`/explore/${study.aoiId}`} className="text-accent-light hover:text-accent text-sm transition-colors">
          Open in Explorer →
        </Link>
      </nav>

      <main className="max-w-3xl mx-auto px-6 py-12">
        {/* Header */}
        <div className="space-y-3 mb-10">
          <span className="badge bg-accent/20 text-accent-light border border-accent/30 text-xs">{study.category}</span>
          <h1 className="text-3xl font-bold text-white">{study.title}</h1>
          <p className="text-slate-400 leading-relaxed">{study.subtitle}</p>
          <div className="flex gap-4 text-xs text-muted pt-1">
            <span>AOI: {study.location}</span>
            <span>·</span>
            <span>Period: {study.period}</span>
            <span>·</span>
            <span>Platform: Sentinel-1</span>
          </div>
        </div>

        {/* Interactive map link */}
        <div className="panel p-4 flex items-center justify-between mb-10 bg-surface-2">
          <div>
            <p className="text-sm font-medium text-white">Explore this data interactively</p>
            <p className="text-xs text-muted">Click pixels to inspect time series and anomaly scores</p>
          </div>
          <Link to={`/explore/${study.aoiId}`} className="btn-primary text-sm flex-shrink-0">
            Open map →
          </Link>
        </div>

        {/* Markdown content */}
        <article className="prose prose-invert prose-sm max-w-none
          prose-headings:text-white
          prose-p:text-slate-300 prose-p:leading-relaxed
          prose-strong:text-slate-200
          prose-code:text-accent-light prose-code:bg-surface-2 prose-code:rounded prose-code:px-1
          prose-pre:bg-surface-1 prose-pre:border prose-pre:border-surface-2
          prose-blockquote:border-l-accent prose-blockquote:text-slate-400
          prose-a:text-accent-light hover:prose-a:text-accent
          prose-table:text-sm
          prose-th:text-slate-200 prose-td:text-slate-400
          prose-hr:border-surface-2">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {study.content}
          </ReactMarkdown>
        </article>

        {/* Metrics panel */}
        {study.metrics && (
          <div className="mt-10 panel p-5">
            <h3 className="text-sm font-semibold text-white mb-4">Model performance</h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {study.metrics.map(({ label, value, unit }) => (
                <div key={label} className="text-center">
                  <div className="text-2xl font-bold text-accent-light">{value}</div>
                  <div className="text-xs text-muted mt-0.5">{label}</div>
                  {unit && <div className="text-[10px] text-muted/70">{unit}</div>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Navigation between case studies */}
        <div className="mt-12 flex gap-3">
          <Link to="/" className="btn-ghost text-sm">← All case studies</Link>
          <Link to={`/explore/${study.aoiId}`} className="btn-primary text-sm ml-auto">
            Explore {study.location} →
          </Link>
        </div>
      </main>
    </div>
  )
}
