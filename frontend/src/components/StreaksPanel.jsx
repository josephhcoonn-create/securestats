/**
 * StreaksPanel — toggle between hot and cold streaks, render a card
 * grid showing player, team, streak length, and avg during the streak.
 *
 *   hot  → green theme  (avg ≥ .350 over min_games)
 *   cold → red theme   (avg ≤ .150 over min_games)
 *
 * Backend exposes `type=hot|cold|both`; we always pass either 'hot' or
 * 'cold' so the panel never has to filter client-side.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const MIN_GAMES = 5

const THEME = {
  hot: {
    pillActive: 'bg-emerald-500 text-white',
    pillInactive: 'bg-slate-800 text-slate-300 hover:bg-slate-700',
    cardBorder: 'border-emerald-500/30',
    cardBg: 'bg-emerald-500/5',
    accent: 'text-emerald-300',
    label: 'Hot',
    threshold: '.350+',
    empty: 'No hot streaks right now. Try fewer minimum games or wait for more ETL runs.',
  },
  cold: {
    pillActive: 'bg-red-500 text-white',
    pillInactive: 'bg-slate-800 text-slate-300 hover:bg-slate-700',
    cardBorder: 'border-red-500/30',
    cardBg: 'bg-red-500/5',
    accent: 'text-red-300',
    label: 'Cold',
    threshold: '.150-',
    empty: 'Nobody slumping below the threshold right now.',
  },
}

export default function StreaksPanel() {
  const [kind, setKind] = useState('hot')
  const theme = THEME[kind]

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['streaks', kind],
    queryFn: async () => {
      const { data } = await api.get('/stats/streaks', {
        params: { type: kind, min_games: MIN_GAMES },
      })
      return data
    },
    staleTime: 60_000,
  })

  const streaks = data?.streaks ?? []

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Streaks</h2>
          <p className="text-sm text-slate-400">
            Rolling {MIN_GAMES}-game windows. Hot = {THEME.hot.threshold},
            Cold = {THEME.cold.threshold}.
          </p>
        </div>
        <div className="inline-flex rounded-md bg-slate-900 p-1 ring-1 ring-slate-700">
          {(['hot', 'cold']).map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={[
                'rounded px-3 py-1.5 text-sm font-medium transition-colors',
                kind === k ? THEME[k].pillActive : THEME[k].pillInactive,
              ].join(' ')}
            >
              {THEME[k].label}
            </button>
          ))}
        </div>
      </header>

      {isPending && <CardSkeleton />}

      {isError && (
        <p className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300 ring-1 ring-red-500/30">
          Couldn't load streaks. {error?.message}
        </p>
      )}

      {!isPending && !isError && streaks.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-700 bg-slate-900/40 p-8 text-center text-sm text-slate-500">
          {theme.empty}
        </p>
      )}

      {streaks.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {streaks.map((s) => (
            <article
              key={s.player_id}
              className={[
                'rounded-lg border bg-slate-900/60 p-4',
                theme.cardBorder,
                theme.cardBg,
              ].join(' ')}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium text-white">{s.full_name}</p>
                  <p className="text-xs text-slate-400">
                    {s.team} · {s.position}
                  </p>
                </div>
                <span
                  className={`text-2xl font-semibold tabular-nums ${theme.accent}`}
                >
                  {s.display_avg}
                </span>
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-xs text-slate-400">
                <Stat label="Games" value={s.games} />
                <Stat label="Hits" value={s.hits} />
                <Stat label="At-bats" value={s.at_bats} />
              </dl>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function Stat({ label, value }) {
  return (
    <div>
      <dt className="uppercase tracking-wider">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-slate-100 tabular-nums">
        {value}
      </dd>
    </div>
  )
}

function CardSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="h-28 animate-pulse rounded-lg border border-slate-800 bg-slate-900/60"
        />
      ))}
    </div>
  )
}
