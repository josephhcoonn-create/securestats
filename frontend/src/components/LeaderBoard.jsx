/**
 * LeaderBoard — top-10 horizontal bar chart with stat + time-range
 * dropdowns and animated transitions.
 *
 * Stats:
 *   batting_avg → ".302"   (formatted display value used as tooltip)
 *   home_runs   → "23"
 *   rbis        → "42"
 *   ops         → "0.812"
 *
 * Time range:
 *   7   → days=7   (rolling 7-day window)
 *   30  → days=30  (rolling 30-day window)
 *   ''  → omit `days` → all-season aggregate
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import api from '../api/client'

const STAT_OPTIONS = [
  { value: 'batting_avg', label: 'Batting Avg', kind: 'rate' },
  { value: 'home_runs', label: 'Home Runs', kind: 'count' },
  { value: 'rbis', label: 'RBI', kind: 'count' },
  { value: 'ops', label: 'OPS', kind: 'rate' },
]

const RANGE_OPTIONS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '', label: 'Season' },
]

// Tailwind blue ramp — top rank is brightest
const BAR_COLORS = [
  '#3b82f6', '#3b82f6', '#3b82f6',
  '#60a5fa', '#60a5fa', '#60a5fa',
  '#93c5fd', '#93c5fd', '#93c5fd', '#bfdbfe',
]

export default function LeaderBoard() {
  const [stat, setStat] = useState('batting_avg')
  const [range, setRange] = useState('')

  const statMeta = STAT_OPTIONS.find((s) => s.value === stat)

  const { data, isPending, isError, error, isFetching } = useQuery({
    queryKey: ['leaders', { stat, range }],
    queryFn: async () => {
      const params = { stat, limit: 10 }
      if (range) params.days = Number(range)
      const { data } = await api.get('/stats/leaders', { params })
      return data
    },
    staleTime: 60_000,
  })

  // Bars sorted by value desc so the longest bar sits at the top.
  // Recharts renders YAxis category top-down, so we reverse to put
  // rank 1 at the top of the chart.
  const chartData = useMemo(() => {
    const rows = data?.leaders ?? []
    return [...rows]
      .map((l) => ({
        ...l,
        label: `${l.rank}. ${l.full_name}`,
      }))
      .reverse()
  }, [data])

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Batting Leaders</h2>
          <p className="text-sm text-slate-400">
            Top 10 across the selected window. Players with too few at-bats are excluded.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            value={stat}
            onChange={(e) => setStat(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
          >
            {STAT_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            value={range}
            onChange={(e) => setRange(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
          >
            {RANGE_OPTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
      </header>

      <div className="relative rounded-lg border border-slate-800 bg-slate-900/60 p-4">
        {isFetching && !isPending && (
          <span className="absolute right-4 top-3 text-xs text-slate-500">
            updating…
          </span>
        )}

        {isPending ? (
          <Skeleton />
        ) : isError ? (
          <p className="py-12 text-center text-sm text-red-400">
            Couldn't load leaders. {error?.message}
          </p>
        ) : chartData.length === 0 ? (
          <p className="py-12 text-center text-sm text-slate-500">
            No qualified leaders for this window yet — try Season or wait for more ETL runs.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={420}>
            <BarChart
              layout="vertical"
              data={chartData}
              margin={{ top: 8, right: 32, left: 16, bottom: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1f293780" horizontal={false} />
              <XAxis
                type="number"
                stroke="#94a3b8"
                tick={{ fill: '#94a3b8', fontSize: 12 }}
                tickFormatter={(v) =>
                  statMeta?.kind === 'rate'
                    ? v.toFixed(3).replace(/^0/, '')
                    : String(v)
                }
              />
              <YAxis
                type="category"
                dataKey="label"
                stroke="#94a3b8"
                tick={{ fill: '#cbd5e1', fontSize: 12 }}
                width={170}
                interval={0}
              />
              <Tooltip
                cursor={{ fill: '#1e293b80' }}
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: 6,
                  color: '#e2e8f0',
                  fontSize: 13,
                }}
                formatter={(_v, _n, entry) => [
                  entry.payload.display_value,
                  statMeta?.label ?? stat,
                ]}
                labelFormatter={(_l, payload) => {
                  const p = payload?.[0]?.payload
                  return p ? `${p.full_name} — ${p.team}` : ''
                }}
              />
              <Bar
                dataKey="value"
                radius={[0, 4, 4, 0]}
                isAnimationActive
                animationDuration={500}
              >
                {chartData.map((entry, i) => (
                  <Cell
                    key={entry.player_id}
                    fill={BAR_COLORS[chartData.length - 1 - i] ?? '#3b82f6'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  )
}

function Skeleton() {
  return (
    <div className="space-y-2 py-2">
      {Array.from({ length: 10 }).map((_, i) => (
        <div
          key={i}
          className="h-7 animate-pulse rounded bg-slate-800"
          style={{ width: `${100 - i * 7}%` }}
        />
      ))}
    </div>
  )
}
