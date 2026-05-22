/**
 * HitProbChart — pick a player, click Calculate, see their estimated
 * hit probability as a radial gauge with contributing-factors panel
 * and a 95% CI range bar.
 *
 * Fetches /stats/hit-probability/{player_id} on demand (not on every
 * keystroke) so the user controls when the API call fires.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
} from 'recharts'
import api from '../api/client'
import PlayerSearchInput from './PlayerSearchInput'

const CONF_BADGE = {
  high: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  medium: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  low: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
}

const fmtAvg = (v) =>
  v == null ? '—' : v.toFixed(3).replace(/^0/, '')

export default function HitProbChart() {
  const [selected, setSelected] = useState(null)
  // playerId only changes when the user clicks Calculate — the query
  // key is gated on it so it only fires on demand.
  const [playerId, setPlayerId] = useState(null)

  const { data, isFetching, isError, error } = useQuery({
    queryKey: ['hit-prob', playerId],
    queryFn: async () => {
      const { data } = await api.get(`/stats/hit-probability/${playerId}`)
      return data
    },
    enabled: playerId != null,
    staleTime: 60_000,
  })

  const onCalculate = () => {
    if (selected) setPlayerId(selected.id)
  }

  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold text-white">Hit Probability</h2>
        <p className="text-sm text-slate-400">
          Weighted blend of recent form, career average, and league average,
          with a 95% confidence interval based on sample size.
        </p>
      </header>

      <div className="flex flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4 sm:flex-row sm:items-center">
        <div className="flex-1">
          <PlayerSearchInput
            value={selected}
            onChange={setSelected}
            placeholder="Pick a player…"
          />
        </div>
        <button
          onClick={onCalculate}
          disabled={!selected || isFetching}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:cursor-not-allowed disabled:bg-blue-400"
        >
          {isFetching ? 'Calculating…' : 'Calculate'}
        </button>
      </div>

      {isError && (
        <div
          role="alert"
          className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300 ring-1 ring-red-500/30"
        >
          Failed to compute hit probability. {error?.message}
        </div>
      )}

      {data && <ResultPanel data={data} />}

      {!data && !isFetching && (
        <p className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
          Select a player and click Calculate to see their projected hit probability.
        </p>
      )}
    </section>
  )
}

function ResultPanel({ data }) {
  const pct = Math.round(data.hit_probability * 1000) / 10

  // RadialBar wants 0..100 so it scales with PolarAngleAxis domain.
  const gaugeData = [{ name: 'p', value: pct, fill: gaugeColor(pct) }]

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      {/* Gauge */}
      <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-300">
              {data.full_name}
            </p>
            <p className="text-xs text-slate-500">{data.team}</p>
          </div>
          <span
            className={[
              'rounded-full px-2.5 py-0.5 text-xs font-medium ring-1',
              CONF_BADGE[data.confidence] ?? CONF_BADGE.low,
            ].join(' ')}
          >
            {data.confidence} confidence
          </span>
        </div>

        <div className="relative mt-2 h-56">
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              innerRadius="70%"
              outerRadius="100%"
              data={gaugeData}
              startAngle={210}
              endAngle={-30}
            >
              <PolarAngleAxis
                type="number"
                domain={[0, 100]}
                angleAxisId={0}
                tick={false}
              />
              <RadialBar
                background={{ fill: '#1e293b' }}
                dataKey="value"
                cornerRadius={12}
                isAnimationActive
                animationDuration={600}
              />
            </RadialBarChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-5xl font-semibold text-white tabular-nums">
              {data.display_probability}
            </span>
            <span className="mt-1 text-xs text-slate-400">
              CI {data.display_ci}
            </span>
          </div>
        </div>

        {/* CI range bar */}
        <div className="mt-2">
          <p className="mb-1 text-xs font-medium uppercase tracking-wider text-slate-400">
            95% confidence interval
          </p>
          <div className="relative h-2 overflow-hidden rounded-full bg-slate-800">
            <div
              className="absolute top-0 h-2 rounded-full bg-blue-500/60"
              style={{
                left: `${data.ci_lower * 100}%`,
                width: `${(data.ci_upper - data.ci_lower) * 100}%`,
              }}
            />
            <div
              className="absolute top-0 h-2 w-0.5 bg-white"
              style={{ left: `${data.hit_probability * 100}%` }}
              title="Estimate"
            />
          </div>
          <div className="mt-1 flex justify-between text-xs text-slate-500 tabular-nums">
            <span>0%</span>
            <span>50%</span>
            <span>100%</span>
          </div>
        </div>
      </div>

      {/* Factors */}
      <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="mb-3 text-sm font-medium text-slate-300">
          Contributing factors
        </h3>
        <dl className="space-y-3 text-sm">
          <Factor
            label="Recent average"
            sub={`Last ${data.recent_games} games (${data.recent_at_bats} AB)`}
            weight="50%"
            value={fmtAvg(data.recent_avg)}
          />
          <Factor
            label="Career average"
            sub="All loaded games"
            weight="30%"
            value={fmtAvg(data.career_avg)}
          />
          <Factor
            label="League average"
            sub="Baseline regression"
            weight="20%"
            value={fmtAvg(data.league_avg)}
          />
        </dl>
        <p className="mt-4 border-t border-slate-800 pt-3 text-xs text-slate-500">
          Estimate = 0.5 × recent + 0.3 × career + 0.2 × league, clamped to
          [0, 1]. Confidence rises with at-bats in the recent window.
        </p>
      </div>
    </div>
  )
}

function Factor({ label, sub, weight, value }) {
  return (
    <div className="flex items-baseline justify-between gap-2 rounded-md bg-slate-950/40 px-3 py-2 ring-1 ring-slate-800/60">
      <div>
        <dt className="text-slate-200">{label}</dt>
        <dd className="text-xs text-slate-500">{sub}</dd>
      </div>
      <div className="text-right">
        <div className="font-semibold tabular-nums text-white">{value}</div>
        <div className="text-xs text-slate-500">weight {weight}</div>
      </div>
    </div>
  )
}

function gaugeColor(pct) {
  if (pct >= 35) return '#10b981' // emerald
  if (pct >= 25) return '#3b82f6' // blue
  if (pct >= 18) return '#f59e0b' // amber
  return '#ef4444' // red
}
