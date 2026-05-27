/**
 * OddsBoard — today's MLB games as cards, each with a mini odds table
 * spanning every sportsbook that's priced the game.
 *
 * - Auto-refreshes every 5 minutes via react-query refetchInterval.
 * - "Best" cell per column is highlighted emerald (best for the bettor:
 *   moneyline → highest numeric value; total/spread shown as-is).
 * - Falls back to a clean empty state when the API key is unset or
 *   no book has priced today's slate yet.
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const REFRESH_INTERVAL = 5 * 60 * 1000 // 5 min

const fmtMoneyline = (v) => {
  if (v == null) return '—'
  return v > 0 ? `+${v}` : String(v)
}
const fmtPoint = (v) => (v == null ? '—' : v > 0 ? `+${v}` : String(v))

function bestIndex(values, mode = 'moneyline') {
  // For moneylines: highest numeric value is best for the bettor.
  // For spreads/totals: not really "best" per se — leave un-highlighted.
  if (mode !== 'moneyline') return -1
  let best = -Infinity
  let bestIdx = -1
  values.forEach((v, i) => {
    if (v == null) return
    if (v > best) {
      best = v
      bestIdx = i
    }
  })
  return bestIdx
}

export default function OddsBoard() {
  const { data, isPending, isError, error, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ['odds-today'],
    queryFn: async () => {
      const { data } = await api.get('/odds/today')
      return data
    },
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
  })

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Live Odds</h2>
          <p className="text-sm text-slate-400">
            Pre-game lines from US sportsbooks via The Odds API. Best
            moneyline per row highlighted in emerald.
          </p>
        </div>
        <div className="text-xs text-slate-500">
          {data?.quota_remaining != null && (
            <span className="mr-3">
              Quota remaining: <span className="font-medium text-slate-300">{data.quota_remaining}</span>
            </span>
          )}
          {isFetching && <span className="text-blue-300">updating…</span>}
          {!isFetching && dataUpdatedAt > 0 && (
            <span>updated {new Date(dataUpdatedAt).toLocaleTimeString()}</span>
          )}
        </div>
      </header>

      {isPending && <CardSkeletons />}

      {isError && (
        <ErrorPanel
          title="Couldn't load odds"
          message={error?.response?.data?.detail || error.message}
        />
      )}

      {!isPending && !isError && data?.games?.length === 0 && (
        <EmptyPanel
          title="No games priced yet"
          subtitle={`${data.games_without_odds} games scheduled today, none with active lines from any book.`}
        />
      )}

      {data?.games?.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.games.map((g) => (
            <GameCard key={g.game_id} game={g} />
          ))}
        </div>
      )}

      {data && data.games_without_odds > 0 && data.games.length > 0 && (
        <p className="text-xs text-slate-500">
          {data.games_without_odds} additional game{data.games_without_odds === 1 ? '' : 's'} scheduled today without odds yet.
        </p>
      )}
    </section>
  )
}

// ── Sub-components ──────────────────────────────────────────────────────────

function GameCard({ game }) {
  const books = useMemo(() => Object.values(game.bookmakers || {}), [game])

  const bestHomeML = useMemo(
    () => bestIndex(books.map((b) => b.home_moneyline), 'moneyline'),
    [books],
  )
  const bestAwayML = useMemo(
    () => bestIndex(books.map((b) => b.away_moneyline), 'moneyline'),
    [books],
  )

  return (
    <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm">
      <header className="mb-3 flex items-baseline justify-between">
        <div>
          <p className="text-sm font-semibold text-white">
            {game.away_team}{' '}
            <span className="text-slate-500">@</span>{' '}
            {game.home_team}
          </p>
          <p className="text-xs text-slate-500">
            {game.date} · {game.status}
          </p>
        </div>
        <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
          {books.length} book{books.length === 1 ? '' : 's'}
        </span>
      </header>

      {books.length === 0 ? (
        <p className="rounded-md bg-slate-800/40 px-3 py-2 text-xs text-slate-500">
          No book has priced this game yet.
        </p>
      ) : (
        <div className="overflow-hidden rounded-md border border-slate-800">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-900/80 text-slate-400">
              <tr>
                <th className="px-2 py-1.5 text-left font-medium">Book</th>
                <th className="px-2 py-1.5 text-right font-medium">Home ML</th>
                <th className="px-2 py-1.5 text-right font-medium">Away ML</th>
                <th className="px-2 py-1.5 text-right font-medium">Spread</th>
                <th className="px-2 py-1.5 text-right font-medium">O/U</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-200">
              {books.map((b, i) => (
                <tr key={b.sportsbook}>
                  <td className="px-2 py-1.5 font-medium text-slate-300">
                    {b.sportsbook}
                  </td>
                  <td
                    className={[
                      'px-2 py-1.5 text-right tabular-nums',
                      i === bestHomeML && 'bg-emerald-500/10 font-semibold text-emerald-300',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {fmtMoneyline(b.home_moneyline)}
                  </td>
                  <td
                    className={[
                      'px-2 py-1.5 text-right tabular-nums',
                      i === bestAwayML && 'bg-emerald-500/10 font-semibold text-emerald-300',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {fmtMoneyline(b.away_moneyline)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                    {fmtPoint(b.spread_home)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-slate-300">
                    {b.over_under ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  )
}

function CardSkeletons() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <div
          key={i}
          className="h-40 animate-pulse rounded-xl border border-slate-800 bg-slate-900/60"
        />
      ))}
    </div>
  )
}

function EmptyPanel({ title, subtitle }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-10 text-center">
      <h3 className="text-base font-medium text-white">{title}</h3>
      <p className="mt-2 text-sm text-slate-400">{subtitle}</p>
    </div>
  )
}

function ErrorPanel({ title, message }) {
  return (
    <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6">
      <h3 className="text-base font-medium text-red-200">{title}</h3>
      <p className="mt-1 text-sm text-red-300/80">{message}</p>
    </div>
  )
}
