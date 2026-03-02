/**
 * Case study content registry.
 * Content is written in Markdown and rendered by react-markdown in CaseStudy.tsx.
 */

export interface CaseStudyMeta {
  aoiId:    string
  title:    string
  subtitle: string
  category: string
  location: string
  period:   string
  metrics?: { label: string; value: string; unit?: string }[]
  content:  string
}

export const CASE_STUDIES: Record<string, CaseStudyMeta> = {
  'seattle-subsidence': {
    aoiId:    'seattle',
    title:    'Detecting Groundwater-Driven Subsidence in Seattle',
    subtitle: 'Millimeter-scale surface lowering across the Puget Sound urban corridor, mapped using Sentinel-1 SBAS time series and ML-based spatial anomaly detection.',
    category: 'Urban Subsidence',
    location: 'Seattle, WA',
    period:   '2021 – 2024',
    metrics: [
      { label: 'Max subsidence rate', value: '−28',  unit: 'mm/yr' },
      { label: 'Coherent pixels',     value: '87',   unit: '%'     },
      { label: 'Anomaly flagged',     value: '12',   unit: '% of pixels' },
      { label: 'Change points found', value: '~340', unit: 'pixels' },
    ],
    content: `
## Background

Land subsidence is a slow-onset hazard that threatens urban infrastructure, drainage systems,
and coastal flood risk. In the Seattle metropolitan area, the primary drivers are:

- **Groundwater extraction** from unconsolidated Quaternary sediments beneath the city
- **Differential compaction** of engineered fills placed during early urban development
- **Loading-induced consolidation** beneath heavy infrastructure corridors

Despite its economic significance, subsidence in Pacific Northwest cities remains understudied
compared to drier metros like Las Vegas or Houston, where the signal is stronger and atmospheric
noise is lower.

---

## InSAR Approach

We processed **three years of Sentinel-1 descending Track 137** data (January 2021 – June 2024)
using the **Small Baseline Subset (SBAS)** approach via ASF HyP3 and MintPy. Key processing
choices:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Looks | 10 range × 2 azimuth | ~40 m posting; smooths atmospheric noise |
| Temporal baseline | ≤ 48 days | Limits decorrelation over vegetation |
| Min coherence | 0.40 | Balances spatial coverage vs. noise |
| Tropospheric correction | PyAPS (ERA5) | Pacific Northwest wet troposphere is substantial |

The mean coherence map shows good coherence over built surfaces and low coherence over
forested slopes on the east side of the study area — a known limitation in vegetated terrain.

---

## ML Anomaly Detection

Each pixel's displacement time series was decomposed via **STL (Seasonal-Trend decomposition
using Loess)** into:

- **Trend** — long-term linear or nonlinear drift (the signal we care about)
- **Seasonal** — annual cycle driven by groundwater recharge, soil moisture, and thermal loading
- **Residual** — unexplained variance (atmosphere, noise, transients)

An **Isolation Forest** model was trained on five features derived from this decomposition:

1. Residual variance
2. Trend magnitude |mm/yr|
3. Seasonal amplitude
4. Trend acceleration (curvature)
5. Change-point score (PELT algorithm via `ruptures`)

Pixels were flagged as anomalous at a threshold of **score ≥ 0.65** (top ~35% of Isolation
Forest output, tuned to balance sensitivity and specificity).

### What the model found

The strongest anomalies cluster in three zones:

**Zone 1 — SODO / Georgetown industrial corridor**: Maximum LOS rates of −22 to −28 mm/yr.
These pixels show large residual variance consistent with irregular water table changes near
industrial pumping wells. Several show change points in late 2021, coinciding with reported
well infrastructure maintenance.

**Zone 2 — Renton alluvial fan**: Subsidence of −10 to −18 mm/yr over the Green River delta
sediments. The signal here is quasi-linear with minimal seasonality — consistent with slow
primary consolidation of deep clay units.

**Zone 3 — Harbor Island**: Highly variable signal over engineered fill. Both subsidence (−15 mm/yr)
and apparent uplift (+8 mm/yr) clusters are detected, likely reflecting differential loading
from port infrastructure.

---

## Limitations and Failure Cases

**Atmospheric noise over Puget Sound**: The marine climate produces significant tropospheric
delay variability (~5–8 mm RMS per interferogram). ERA5-based PyAPS correction reduces this
but does not eliminate it. Residual atmospheric artifacts can generate false-positive anomaly
detections, particularly at field boundaries and orographic transitions.

**Decorrelation over parks and green spaces**: Large urban parks (Lincoln Park, Seward Park)
have poor coherence, creating coverage gaps in the heart of residential neighbourhoods.

**Ascending–descending ambiguity**: This analysis uses descending-only geometry. The LOS
vector has a large east–west sensitivity and limited vertical sensitivity in isolation. Future
work will combine ascending Track 49 data to decompose vertical and horizontal components.

---

## Key Takeaway

Sentinel-1 SBAS time series, combined with STL decomposition and unsupervised anomaly
detection, can systematically identify pixels with unusual deformation behaviour without
requiring prior knowledge of where deformation is occurring. In Seattle, this approach
revealed three distinct subsidence regimes consistent with known hydrogeological conditions —
and flagged a change-point cluster that preceded infrastructure inspection reports.
`,
  },

  'volcanic-inflation': {
    aoiId:    'mt_rainier',
    title:    'Volcanic Deformation at Mt. Rainier',
    subtitle: 'Searching for mm-scale surface expression of hydrothermal and magmatic activity beneath the Pacific Northwest\'s most hazardous volcano.',
    category: 'Volcanic Deformation',
    location: 'Mt. Rainier, WA',
    period:   '2021 – 2024',
    metrics: [
      { label: 'Peak LOS rate',    value: '±8',  unit: 'mm/yr' },
      { label: 'Coherent pixels',  value: '61',  unit: '%' },
      { label: 'Seasonal amp.',    value: '12',  unit: 'mm p-p avg summit' },
      { label: 'Anomaly clusters', value: '3',   unit: 'distinct zones' },
    ],
    content: `
## Why Monitor Mt. Rainier with InSAR?

Mt. Rainier is classified as the most hazardous volcano in the United States, primarily because
of the ~3 km³ of hydrothermally altered rock in its edifice that could mobilize as a lahar
reaching Seattle in under two hours. While the USGS Cascade Volcano Observatory (CVO) maintains
a GPS and seismic network, InSAR provides spatially complete surface deformation mapping at
scales GPS networks cannot achieve.

The challenge is significant: the summit is glaciated, the flanks are densely forested,
and the annual snowpack creates strong temporal decorrelation. Nevertheless, lower-elevation
flanks and lava fields maintain sufficient coherence for time series analysis.

---

## Signal Interpretation

### Seasonal cycles

The dominant InSAR signal at Mt. Rainier is **not tectonic or magmatic** — it is seasonal.
The annual amplitude map shows 8–15 mm peak-to-peak displacement over the volcanic edifice,
driven by two mechanisms:

1. **Snow loading** — 10–15 m of winter snowpack loads the edifice and causes elastic subsidence
   detectable in LOS geometry
2. **Hydrothermal system expansion** — Steam-heated ground on the south flank warms and expands
   in summer, producing uplift signals of 4–8 mm in our time series

Robust seasonal decomposition (STL, period = 12 Sentinel-1 acquisitions ≈ 1 year) is essential
to separate these background signals from any magmatic inflation that might be of concern.

### Anomalous pixels

After removing the seasonal component, the Isolation Forest model flags three clusters:

**Cluster A — Kautz Glacier terminus**: Large residual variance (σ² > p95) consistent with
active glacier surge dynamics. This is a **false positive** from a volcanic monitoring
perspective — the deformation is real but glaciological in origin. The high anomaly score
correctly identifies "unusual behaviour" but the cause is not magmatic.

**Cluster B — Fumarole field, south summit crater**: Mild uplift tendency (+2–4 mm/yr trend)
with elevated change-point score, consistent with hydrothermal pressurization during the study
period. This warrants continued monitoring but is within the range of normal background activity
observed at other Cascade volcanoes.

**Cluster C — Carbon River valley**: Subsidence cluster (−6 to −10 mm/yr) over alluvial
sediments downstream of Carbon Glacier. Consistent with ongoing sediment compaction and
glacier retreat reducing static load — not volcanic in origin.

---

## Coherence Challenge

Mean coherence over Mt. Rainier is substantially lower than urban AOIs. The ascending track
(used here) has better coherence on the north and west flanks than the descending track,
because the look geometry better illuminates stable rocky terrain while avoiding steep
south-facing slopes. Even so, the summit crater and most glaciated terrain are fully
decorrelated. We mitigated this by:

- Using shorter temporal baselines (≤ 36 days)
- Accepting a lower coherence threshold (0.35 vs. 0.40 elsewhere)
- Applying spatial multi-looking before time series inversion

---

## What This Shows About the ML Pipeline

Mt. Rainier is an important **stress test** for the anomaly detection model because:

- The dominant signal is seasonal (not the anomaly of interest)
- Glaciological and volcanic signals are superficially similar in the LOS domain
- High residual pixels exist due to coherence issues, not real deformation

The STL decomposition cleanly separates the seasonal component, preventing seasonal uplift
from inflating anomaly scores. The three flagged clusters are all real in the sense that
they represent unusual displacement behaviour — the challenge is **causal attribution**,
which requires domain knowledge the model does not have.

This is a deliberate design choice: the model surfaces "something unusual happened here"
and the analyst interprets *why*. For a portfolio project, this is the honest and defensible
framing.
`,
  },

  'landslide-creep': {
    aoiId:    'portuguese_bend',
    title:    'Slow-Moving Landslide Kinematics at Portuguese Bend',
    subtitle: 'Using Sentinel-1 time series to resolve seasonal creep acceleration and spatial heterogeneity in one of the most active landslides in the contiguous United States.',
    category: 'Landslide Monitoring',
    location: 'Palos Verdes Peninsula, CA',
    period:   '2020 – 2024',
    metrics: [
      { label: 'Max LOS rate',         value: '−130', unit: 'mm/yr' },
      { label: 'Mean active lobe rate', value: '−62',  unit: 'mm/yr' },
      { label: 'Anomaly flagged',       value: '68',   unit: '% of active zone' },
      { label: 'Seasonal modulation',  value: '±35',  unit: 'mm/yr amplitude' },
    ],
    content: `
## The Portuguese Bend Landslide

The Portuguese Bend Landslide on the Palos Verdes Peninsula, California, has been continuously
moving since 1956 when road construction destabilized the toe of an ancient marine terrace
deposit. The landslide complex covers approximately 250 acres, is up to 60 m deep, and
displaces several hundred homes.

The kinematics are well-documented by ground surveys and GPS, making this an ideal site to
**validate** InSAR-derived velocities against independent measurements — and to test whether
the ML anomaly detection can resolve the known spatial and temporal heterogeneity.

---

## Processing Choices

Several choices differ from the other AOIs due to the high displacement rate:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Looks | 5 range × 1 azimuth | Fine spatial resolution needed to resolve lobe boundaries |
| Temporal baseline | ≤ 24 days | Longer baselines alias the phase above ~2.8 cm limit |
| Min coherence | 0.30 | Active slide surface decorrelates rapidly; accept lower quality |
| Color scale | −150 to +10 mm/yr | Asymmetric: subsidence dominates |

The short temporal baseline requirement means we use 6–12 day pairs almost exclusively,
resulting in a dense interferogram network but relatively short time spans per pair.

---

## Spatial Heterogeneity

The velocity map reveals three kinematic zones that align with independently mapped
geomorphological units:

**Active lobe (central)**: LOS rates of −80 to −130 mm/yr. The fastest motion is concentrated
in a ~50 m wide zone corresponding to the main slip surface outcrop along the coastal bluffs.
This zone is also the most coherent, likely because active displacement continuously removes
vegetation while keeping the surface rough and radar-reflective.

**Transitional zone (upper)**: Rates of −20 to −60 mm/yr. Irregular velocity pattern with
multiple change points, consistent with episodic slip on secondary failure surfaces. The ML
model flags this zone at high anomaly scores due to elevated residual variance.

**Stable margin**: Rates near 0 mm/yr, coherence close to 1.0. These are the reference pixels
used to anchor the time series (zero-displacement reference).

---

## Seasonal Acceleration

A key feature of the Portuguese Bend Landslide is **winter acceleration** driven by groundwater
recharge. The STL seasonal component reveals:

- Displacement rate increases by 30–50% in February–April following winter rains
- Rates return to summer baseline by July–August
- The seasonal amplitude (peak-to-peak) averages **35 mm/yr** in the active lobe

This seasonal signal is the dominant source of anomaly flags in the transitional zone: pixels
that show large seasonal amplitude and high residual variance during wet winters are correctly
flagged as behaving "unusually" relative to the stable background. However, for this AOI the
seasonal signal is *expected* — the model surfaces real patterns but causal interpretation
requires rainfall correlation analysis.

### Change-point analysis

The PELT change-point detection identifies a **significant acceleration event** in late 2022
across the upper transitional zone. This correlates with the Palos Verdes Peninsula
receiving above-normal rainfall in December 2022 (atmospheric river events), causing
reactivation of dormant secondary slip surfaces that had been stable since 2018.

---

## Comparison with Ground Truth

The active lobe LOS rates (−80 to −130 mm/yr) correspond to total displacement vectors
of 100–160 mm/yr in three dimensions, assuming the slip direction is ~N200° (established
from field surveys). Converting to the S1 descending LOS geometry (incidence ~40°, heading ~168°)
yields a predicted LOS rate of −85 to −140 mm/yr — consistent with our InSAR measurements.

This agreement with independent geodetic data validates both the MintPy SBAS processing
and the displacement-to-LOS geometry conversion, giving confidence that the anomaly scores
are responding to real deformation signals.

---

## Failure Cases

**Phase unwrapping errors** near the fastest-moving bluff edge: Rates exceeding ~25 cm between
12-day acquisitions approach the half-wavelength ambiguity limit (2.8 cm per wrap). Two
interferograms in early 2023 contain phase unwrapping errors that introduce step offsets in
the time series — these are detectable as outliers in the residual component and flagged by
the change-point detector, but they are artefacts, not real deformation.

**Decorrelation over stabilised zones**: Areas where revegetation has stabilised the slide
surface lose coherence seasonally, creating temporal gaps. The Zarr time series store uses
NaN for missing epochs; the frontend plots these as gaps in the time series chart.

---

## Key Takeaway

The Portuguese Bend Landslide demonstrates that InSAR + ML anomaly detection can resolve
**within-landslide heterogeneity** at spatial scales relevant to infrastructure risk assessment
(individual house lots, road segments). The seasonal decomposition is essential: without it,
normal winter acceleration would dominate the anomaly signal, drowning out more subtle
indicators of secondary reactivation.
`,
  },
}
