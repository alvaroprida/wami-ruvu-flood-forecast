import { formatPct } from '../format'
import type { Forecast } from '../types'
import { AlertBadge } from './AlertBadge'

const STEPS = [
  ['Warm state', 'Every day Wflow is advanced on observed rainfall (CHIRPS; ECMWF day-1 forecasts for the last days CHIRPS has not published yet) with an ERA5-based temperature and evaporation climatology, and the model state is saved.'],
  ['Ensemble forecast', 'Each day the model restarts from that state and is driven by the 50 perturbed ECMWF ENS members, 15 days ahead.'],
  ['Thresholds', 'Return-period flows come from a 25-year simulation of the same model (CHIRPS + ERA5, 2001–2025, maxima of 2002–2025), so systematic model bias largely cancels out.'],
  ['Alerts', 'A reach is flagged when enough members exceed a return-period flow at any lead time.'],
  ['Limitations', 'The model is not yet calibrated against observed discharge: absolute flows (especially in the semi-arid upper Wami) are too high. Alert levels are less affected, because forecasts and thresholds come from the same model.'],
]

export function About({ forecast }: { forecast: Forecast }) {
  return (
    <section className="grid gap-6 rounded-xl border border-line bg-surface p-5 text-sm md:grid-cols-3">
      <div>
        <h2 className="mb-2 text-base font-semibold text-ink">How it works</h2>
        <ol className="space-y-2 text-ink-2">
          {STEPS.map(([title, text], i) => (
            <li key={title}>
              <span className="font-medium text-ink">{i + 1}. {title}.</span> {text}
            </li>
          ))}
        </ol>
      </div>
      <div>
        <h2 className="mb-2 text-base font-semibold text-ink">Alert rule</h2>
        <ul className="space-y-2">
          {forecast.alert_rule.map((r) => (
            <li key={r.level} className="flex flex-wrap items-center gap-2 text-ink-2">
              <AlertBadge level={r.level} />
              <span>
                ≥ {formatPct(r.min_probability)} of members above the {r.return_period}-year flow
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-ink-3">
          Outputs follow the Delft-FEWS Published Interface conventions (CF-NetCDF time series per location), so
          the model can be run inside an operational FEWS without changes.
        </p>
      </div>
      <div>
        <h2 className="mb-2 text-base font-semibold text-ink">Data &amp; credits</h2>
        <ul className="space-y-1 text-ink-2">
          <li>Hydrological model: Wflow.jl (Deltares), built with HydroMT-Wflow</li>
          <li>Forecast rainfall: ECMWF open data, CC BY 4.0</li>
          <li>Observed rainfall: CHIRPS v2.0 (Climate Hazards Center, UCSB)</li>
          <li>Elevation: FABDEM (Univ. of Bristol), flow network derived with pyflwdir</li>
          <li>Rivers &amp; basemap: © OpenStreetMap contributors, OpenFreeMap</li>
        </ul>
        <p className="mt-3 text-ink-3">
          Research prototype. Not an official warning service — official flood and weather warnings for Tanzania are
          issued by the Tanzania Meteorological Authority.
        </p>
      </div>
    </section>
  )
}
