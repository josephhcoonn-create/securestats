/**
 * PicksHistory — retrospective view of past picks + accuracy trend.
 *
 * Pulls /picks/history?days=N which returns per-day accuracy. We
 * compute a 7-day rolling accuracy line in the chart and list the
 * raw per-day rows in a table below. The total at the top shows the
 * 30-day snapshot-based accuracy (from /picks/accuracy).
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import api from '../api/client'

const DAY_OPTIONS = [7, 14, 30, 60]

export default function PicksHistory() {
  const [days, setDays] = useState(30)

  const historyQuery = useQuery({
    queryKey: ['picks-history', days],
    queryFn: async () => {
      const { data } = await api.get(`/picks/history?days=${days}`)
      return data
    },
    staleTime: 60_000,
  })

  const accuracyQuery = useQuery({
    queryKey: ['picks-accuracy', days],
    queryFn: async () => {
      const { data } = await api.get(`/picks/accuracy?days=${days}`)
      return data
    },
    staleTime: 60_000,
  })

  const chartData = useMemo(() => {
    const days_ = historyQuery.data?.by_date ?? []
    // by_date comes newest-first; reverse so the chart reads left-to-right
    const chrono = [...days_].reverse()
    // 7-day rolling accuracy: sum(hits) / sum(picks) in the trailing window
    return chrono.map((d, i) => {
      const window = chrono.slice(Math.max(0, i - 6), i + 1)
      const totalPicks = window.reduce((s, w) => s + (w.pick_count ?? 0), 0)
      const totalHits = window.reduce((s, w) => s + (w.hits ?? 0), 0)
      const rolling = totalPicks > 0 ? +(100 * totalHits / totalPicks).toFixed(1) : null
      return {
        date: d.target_date,
        per_day: d.accuracy_pct ?? null,
        rolling7: rolling,
        pick_count: d.pick_count,
      }
    })
  }, [historyQuery.data])

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Picks History</h2>
          <p className="text-sm text-slate-400">
            Past predictions vs actual results — measures how the model performs in the wild.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-400">Window:</span>
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={[
                'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                days === d
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700',
              ].join(' ')}
            >
              {d}d
            </button>
          ))}
        </div>
      </header>

      <SummaryStrip historyData={historyQuery.data} accuracyData={accuracyQuery.data} />

      {/* Trend chart */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-400">
          Accuracy trend (per-day + 7-day rolling)
        </p>
        {historyQuery.isPending ? (
          <div className="h-64 animate-pulse rounded bg-slate-800/40" />
        ) : chartData.length === 0 ? (
          <p className="py-12 text-center text-sm text-slate-500">
            No graded picks in the selected window yet.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
              <YAxis stroke="#94a3b8" domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: 6,
                  color: '#e2e8f0',
                  fontSize: 12,
                }}
                formatter={(v, n) => [v == null ? 'no picks' : `${v}%`, n]}
              />
              <Line
                type="monotone"
                dataKey="per_day"
                name="Per-day"
                stroke="#64748b"
                strokeWidth={1.5}
                dot={{ r: 2, fill: '#64748b' }}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="rolling7"
                name="7-day rolling"
                stroke="#3b82f6"
                strokeWidth={2.5}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Per-day breakdown table */}
      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-900/80 text-xs uppercase tracking-wider text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Date</th>
              <th className="px-3 py-2 text-right font-medium">Picks</th>
              <th className="px-3 py-2 text-right font-medium">Hits</th>
              <th className="px-3 py-2 text-right font-medium">AB</th>
              <th className="px-3 py-2 text-right font-medium">Accuracy</th>
              <th className="px-3 py-2 text-right font-medium">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 text-slate-200">
            {historyQuery.isPending && (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500">Loading…</td></tr>
            )}
            {historyQuery.data?.by_date?.length === 0 && !historyQuery.isPending && (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-500">No picks in this window yet.</td></tr>
            )}
            {historyQuery.data?.by_date?.map((d) => {
              const status =
                d.pick_count === 0 ? 'pending'
                : (d.accuracy_pct ?? 0) >= 50 ? 'win'
                : 'loss'
              return (
                <tr key={d.target_date}>
                  <td className="px-3 py-2 text-slate-300">{d.target_date}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{d.pick_count}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{d.hits}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{d.plate_appearances}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {d.accuracy_pct == null ? '—' : `${d.accuracy_pct}%`}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <ResultIcon status={status} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function SummaryStrip({ historyData, accuracyData }) {
  const total = accuracyData?.total_picks ?? historyData?.total_picks ?? 0
  const correct = accuracyData?.correct_predictions ?? historyData?.total_hits ?? 0
  const pct = accuracyData?.accuracy_pct ?? historyData?.overall_accuracy_pct
  const pending = accuracyData?.pending_picks

  return (
    <div className="grid gap-3 sm:grid-cols-4">
      <StatTile label="Total picks (graded)" value={total} />
      <StatTile label="Correct" value={correct} accent="emerald" />
      <StatTile
        label="Accuracy"
        value={pct == null ? '—' : `${pct.toFixed(1)}%`}
        accent={pct == null ? null : pct >= 70 ? 'emerald' : pct >= 55 ? 'blue' : 'amber'}
      />
      <StatTile label="Pending" value={pending ?? '—'} accent="slate" />
    </div>
  )
}

function StatTile({ label, value, accent }) {
  const tone = {
    emerald: 'text-emerald-300',
    blue: 'text-blue-300',
    amber: 'text-amber-300',
    slate: 'text-slate-300',
  }[accent] || 'text-white'
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-3">
      <p className="text-xs uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}

function ResultIcon({ status }) {
  if (status === 'win') {
    return <span className="inline-block text-emerald-400" title="Day positive">✓</span>
  }
  if (status === 'loss') {
    return <span className="inline-block text-red-400" title="Day negative">✗</span>
  }
  return <span className="inline-block text-amber-400" title="Pending / no picks">⏱</span>
}
