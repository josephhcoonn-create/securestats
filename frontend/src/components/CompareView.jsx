/**
 * CompareView — pick up to 3 players, see them on a radar chart and in
 * a side-by-side stat table.
 *
 * Radar metrics (all on the same 0..1 scale via min-max normalization
 * within the compared set, with a sane baseline so a single-player
 * comparison still has shape):
 *   AVG, OBP, SLG, OPS, HR rate (HR/AB)
 *
 * (K rate isn't in the BattingStats schema yet, so it's intentionally
 *  omitted — see app/models/batting_stats.py.)
 *
 * Backend: POST /stats/compare { player_ids: [...] }  → players[],
 * leaders { stat: player_id }. We auto-refetch whenever the selection
 * settles at 2-3 valid players.
 */
import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import api from '../api/client'
import PlayerSearchInput from './PlayerSearchInput'

const MAX_PLAYERS = 3
const SERIES_COLORS = ['#3b82f6', '#10b981', '#f59e0b']

const fmtAvg = (v) => (v == null ? '—' : v.toFixed(3).replace(/^0/, ''))
const fmtInt = (v) => (v == null ? '—' : String(v))

const RADAR_AXES = [
  { key: 'batting_avg', label: 'AVG' },
  { key: 'on_base_pct', label: 'OBP' },
  { key: 'slugging_pct', label: 'SLG' },
  { key: 'ops', label: 'OPS' },
  { key: 'hr_rate', label: 'HR rate' },
]

const TABLE_ROWS = [
  { key: 'games_played', label: 'Games',  fmt: fmtInt },
  { key: 'at_bats',      label: 'AB',     fmt: fmtInt },
  { key: 'hits',         label: 'H',      fmt: fmtInt },
  { key: 'home_runs',    label: 'HR',     fmt: fmtInt },
  { key: 'rbis',         label: 'RBI',    fmt: fmtInt },
  { key: 'batting_avg',  label: 'AVG',    fmt: fmtAvg },
  { key: 'on_base_pct',  label: 'OBP',    fmt: fmtAvg },
  { key: 'slugging_pct', label: 'SLG',    fmt: fmtAvg },
  { key: 'ops',          label: 'OPS',    fmt: fmtAvg },
  { key: 'recent_avg',   label: 'L10 AVG', fmt: fmtAvg },
]

export default function CompareView() {
  // slots is a fixed-length array; each slot is a PlayerSummary or null.
  const [slots, setSlots] = useState([null, null, null])

  const setSlot = (i, value) =>
    setSlots((prev) => {
      const next = [...prev]
      next[i] = value
      return next
    })

  // Dedupe + filter selected players; only run the mutation when 2-3.
  const playerIds = useMemo(() => {
    const seen = new Set()
    const ids = []
    for (const s of slots) {
      if (s && !seen.has(s.id)) {
        seen.add(s.id)
        ids.push(s.id)
      }
    }
    return ids
  }, [slots])

  const mutation = useMutation({
    mutationFn: async (ids) => {
      const { data } = await api.post('/stats/compare', { player_ids: ids })
      return data
    },
  })

  const onCompare = () => {
    if (playerIds.length < 2) return
    mutation.mutate(playerIds)
  }

  const result = mutation.data

  // Build radar data: one record per axis, with one numeric key per
  // player. Each value is normalized 0..1 within the compared set so
  // the polygons are visually comparable across stats of different units.
  const radarData = useMemo(() => {
    if (!result?.players?.length) return []
    const enriched = result.players.map((p) => ({
      ...p,
      hr_rate: p.at_bats > 0 ? p.home_runs / p.at_bats : 0,
    }))

    return RADAR_AXES.map(({ key, label }) => {
      const values = enriched.map((p) => p[key] ?? 0)
      const max = Math.max(...values, key === 'hr_rate' ? 0.05 : 0.4)
      const min = 0
      const span = max - min || 1
      const row = { axis: label }
      enriched.forEach((p, i) => {
        row[`p${i}`] = ((p[key] ?? 0) - min) / span
      })
      return row
    })
  }, [result])

  const players = result?.players ?? []
  const leaders = result?.leaders ?? {}

  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold text-white">Player Comparison</h2>
        <p className="text-sm text-slate-400">
          Choose 2–{MAX_PLAYERS} players to see their career and recent-form
          profile side by side.
        </p>
      </header>

      <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        <div className="grid gap-3 sm:grid-cols-3">
          {slots.map((slot, i) => (
            <div key={i} className="space-y-1">
              <label className="text-xs font-medium uppercase tracking-wider text-slate-400">
                Player {i + 1}
                {i > 1 && (
                  <span className="ml-1 normal-case text-slate-500">(optional)</span>
                )}
              </label>
              <PlayerSearchInput value={slot} onChange={(v) => setSlot(i, v)} />
            </div>
          ))}
        </div>
        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            {playerIds.length < 2
              ? `Select at least ${2 - playerIds.length} more player${playerIds.length === 1 ? '' : 's'}.`
              : `${playerIds.length} player${playerIds.length === 1 ? '' : 's'} selected.`}
          </p>
          <button
            onClick={onCompare}
            disabled={playerIds.length < 2 || mutation.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-300 disabled:cursor-not-allowed disabled:bg-blue-400"
          >
            {mutation.isPending ? 'Comparing…' : 'Compare'}
          </button>
        </div>
      </div>

      {mutation.isError && (
        <p className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300 ring-1 ring-red-500/30">
          Failed to compare. {mutation.error?.message}
        </p>
      )}

      {players.length > 0 && (
        <>
          {/* Radar */}
          <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-400">
              Profile (normalized within selection)
            </p>
            <ResponsiveContainer width="100%" height={340}>
              <RadarChart data={radarData} outerRadius="75%">
                <PolarGrid stroke="#334155" />
                <PolarAngleAxis
                  dataKey="axis"
                  tick={{ fill: '#cbd5e1', fontSize: 12 }}
                />
                <PolarRadiusAxis
                  domain={[0, 1]}
                  tick={false}
                  axisLine={false}
                />
                {players.map((p, i) => (
                  <Radar
                    key={p.player_id}
                    name={p.full_name}
                    dataKey={`p${i}`}
                    stroke={SERIES_COLORS[i]}
                    fill={SERIES_COLORS[i]}
                    fillOpacity={0.18}
                    isAnimationActive
                    animationDuration={500}
                  />
                ))}
                <Tooltip
                  contentStyle={{
                    background: '#0f172a',
                    border: '1px solid #334155',
                    borderRadius: 6,
                    color: '#e2e8f0',
                    fontSize: 13,
                  }}
                  formatter={(v) => (typeof v === 'number' ? v.toFixed(2) : v)}
                />
              </RadarChart>
            </ResponsiveContainer>
            <Legend players={players} />
          </div>

          {/* Stat table */}
          <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/60">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-900/80">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Stat
                  </th>
                  {players.map((p, i) => (
                    <th
                      key={p.player_id}
                      className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider"
                      style={{ color: SERIES_COLORS[i] }}
                    >
                      {p.full_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {TABLE_ROWS.map((row) => (
                  <tr key={row.key}>
                    <td className="px-3 py-2 text-slate-400">{row.label}</td>
                    {players.map((p) => {
                      const isLeader = leaders[row.key] === p.player_id
                      return (
                        <td
                          key={p.player_id}
                          className={[
                            'px-3 py-2 text-right tabular-nums',
                            isLeader ? 'font-semibold text-emerald-300' : 'text-slate-200',
                          ].join(' ')}
                        >
                          {row.fmt(p[row.key])}
                          {isLeader && <span className="ml-1 text-xs">★</span>}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-500">
            ★ marks the leader in each stat among the selected players.
          </p>
        </>
      )}
    </section>
  )
}

function Legend({ players }) {
  return (
    <div className="mt-2 flex flex-wrap gap-4">
      {players.map((p, i) => (
        <div key={p.player_id} className="flex items-center gap-2 text-sm">
          <span
            className="h-3 w-3 rounded-full"
            style={{ background: SERIES_COLORS[i] }}
          />
          <span className="text-slate-200">{p.full_name}</span>
          <span className="text-xs text-slate-500">{p.team}</span>
        </div>
      ))}
    </div>
  )
}
