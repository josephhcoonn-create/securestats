/**
 * PlayerTable — sortable, searchable, paginated player list.
 *
 * - Fetches /players (or /players/search when a query is present) via
 *   react-query, keyed by sort/page/query.
 * - Columns sortable server-side: name, team, position, AVG, HR, RBI.
 * - Click a row to expand it and lazily fetch /players/{id}/stats
 *   (latest 5 games, sort by date desc).
 * - Search input is debounced ~300ms; while typing, react-query keeps
 *   the previous list visible (placeholderData: keepPreviousData).
 * - Skeleton rows show on the first load of any (sort, page, q) tuple.
 */
import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import api from '../api/client'

const PAGE_SIZE = 20

const COLUMNS = [
  { key: 'full_name',          label: 'Name',     align: 'left',  sortKey: 'full_name' },
  { key: 'team',               label: 'Team',     align: 'left',  sortKey: 'team' },
  { key: 'position',           label: 'Pos',      align: 'left',  sortKey: 'position' },
  { key: 'games_played',       label: 'G',        align: 'right', sortKey: 'games_played' },
  { key: 'career_batting_avg', label: 'AVG',      align: 'right', sortKey: 'career_batting_avg' },
  { key: 'career_home_runs',   label: 'HR',       align: 'right', sortKey: 'career_home_runs' },
  { key: 'career_rbis',        label: 'RBI',      align: 'right', sortKey: 'career_rbis' },
]

const fmtAvg = (v) => (v == null ? '—' : v.toFixed(3).replace(/^0/, ''))
const fmtInt = (v) => (v == null ? '—' : String(v))

function useDebounced(value, delay = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return v
}

export default function PlayerTable() {
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounced(query, 300)

  const [sortBy, setSortBy] = useState('full_name')
  const [sortOrder, setSortOrder] = useState('asc')
  const [page, setPage] = useState(0)
  const [expandedId, setExpandedId] = useState(null)

  // Reset to page 0 whenever filter/sort changes so the user doesn't
  // get stranded on a page that no longer exists. The effect is the
  // simplest expression of "when these change, also reset" — the
  // alternative (firing resets from every change handler) is noisier.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    setPage(0)
    setExpandedId(null)
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [debouncedQuery, sortBy, sortOrder])

  const offset = page * PAGE_SIZE
  const isSearching = debouncedQuery.trim().length > 0

  const listQuery = useQuery({
    queryKey: ['players', { q: debouncedQuery, sortBy, sortOrder, page }],
    queryFn: async () => {
      if (isSearching) {
        // /search doesn't accept sort_by; client-side sort happens below.
        const { data } = await api.get('/players/search', {
          params: { q: debouncedQuery, limit: PAGE_SIZE, offset },
        })
        return data
      }
      const { data } = await api.get('/players', {
        params: {
          limit: PAGE_SIZE,
          offset,
          sort_by: sortBy,
          sort_order: sortOrder,
        },
      })
      return data
    },
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })

  // When searching, sort client-side on whatever page we got.
  const items = useMemo(() => {
    const rows = listQuery.data?.items ?? []
    if (!isSearching) return rows
    const col = COLUMNS.find((c) => c.sortKey === sortBy)?.key ?? 'full_name'
    const dir = sortOrder === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = a[col]
      const bv = b[col]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'string') return av.localeCompare(bv) * dir
      return (av - bv) * dir
    })
  }, [listQuery.data, isSearching, sortBy, sortOrder])

  const total = listQuery.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const showingStart = total === 0 ? 0 : offset + 1
  const showingEnd = Math.min(offset + PAGE_SIZE, total)

  const handleSort = (col) => {
    if (!col.sortKey) return
    if (sortBy === col.sortKey) {
      setSortOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(col.sortKey)
      // Numeric columns default to desc (best first); strings to asc.
      setSortOrder(col.align === 'right' ? 'desc' : 'asc')
    }
  }

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Players</h2>
          <p className="text-sm text-slate-400">
            Career batting aggregates across loaded games.
          </p>
        </div>
        <input
          type="search"
          placeholder="Search by name…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30 sm:w-72"
        />
      </header>

      <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900/60">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-900/80">
            <tr>
              {COLUMNS.map((col) => {
                const active = sortBy === col.sortKey
                return (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col)}
                    className={[
                      'select-none px-3 py-2.5 text-xs font-semibold uppercase tracking-wider',
                      col.align === 'right' ? 'text-right' : 'text-left',
                      col.sortKey ? 'cursor-pointer hover:text-white' : '',
                      active ? 'text-white' : 'text-slate-400',
                    ].join(' ')}
                  >
                    {col.label}
                    {active && (
                      <span className="ml-1 text-slate-500">
                        {sortOrder === 'asc' ? '▲' : '▼'}
                      </span>
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-800/70">
            {listQuery.isPending && <SkeletonRows />}

            {listQuery.isError && (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-3 py-8 text-center text-sm text-red-400"
                >
                  Failed to load players. {listQuery.error?.message}
                </td>
              </tr>
            )}

            {!listQuery.isPending && !listQuery.isError && items.length === 0 && (
              <tr>
                <td
                  colSpan={COLUMNS.length}
                  className="px-3 py-8 text-center text-sm text-slate-500"
                >
                  No players match the current filters.
                </td>
              </tr>
            )}

            {items.map((p) => (
              <PlayerRow
                key={p.id}
                player={p}
                expanded={expandedId === p.id}
                onToggle={() =>
                  setExpandedId((id) => (id === p.id ? null : p.id))
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      <footer className="flex flex-col items-center justify-between gap-3 text-sm text-slate-400 sm:flex-row">
        <span>
          {total === 0
            ? 'No results'
            : `Showing ${showingStart}–${showingEnd} of ${total}`}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0 || listQuery.isPending}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1 font-medium text-slate-200 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            ← Prev
          </button>
          <span className="text-xs text-slate-500">
            Page {Math.min(page + 1, totalPages)} of {totalPages}
          </span>
          <button
            onClick={() =>
              setPage((p) => (offset + PAGE_SIZE >= total ? p : p + 1))
            }
            disabled={offset + PAGE_SIZE >= total || listQuery.isPending}
            className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1 font-medium text-slate-200 hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      </footer>
    </section>
  )
}

// ── Row ──────────────────────────────────────────────────────────────────────

function PlayerRow({ player, expanded, onToggle }) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={[
          'cursor-pointer transition-colors',
          expanded ? 'bg-slate-800/70' : 'hover:bg-slate-800/40',
        ].join(' ')}
      >
        <td className="px-3 py-2 text-slate-100">
          <span className="mr-1.5 inline-block text-xs text-slate-500">
            {expanded ? '▾' : '▸'}
          </span>
          {player.full_name}
        </td>
        <td className="px-3 py-2 text-slate-300">{player.team}</td>
        <td className="px-3 py-2 text-slate-300">{player.position}</td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-300">
          {fmtInt(player.games_played)}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-100">
          {fmtAvg(player.career_batting_avg)}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-300">
          {fmtInt(player.career_home_runs)}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-300">
          {fmtInt(player.career_rbis)}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} className="bg-slate-950/60 px-3 py-4">
            <RecentGames playerId={player.id} />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Recent games (expanded panel) ────────────────────────────────────────────

function RecentGames({ playerId }) {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['player-stats', playerId],
    queryFn: async () => {
      const { data } = await api.get(`/players/${playerId}/stats`, {
        params: { limit: 5, sort_by: 'date', sort_order: 'desc' },
      })
      return data
    },
    staleTime: 60_000,
  })

  if (isPending) {
    return (
      <div className="space-y-2">
        <div className="h-3 w-24 animate-pulse rounded bg-slate-800" />
        <div className="h-3 w-full animate-pulse rounded bg-slate-800" />
        <div className="h-3 w-5/6 animate-pulse rounded bg-slate-800" />
      </div>
    )
  }

  if (isError) {
    return (
      <p className="text-sm text-red-400">
        Couldn't load recent games. {error?.message}
      </p>
    )
  }

  const games = data?.items ?? []
  if (games.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No game log loaded for this player yet.
      </p>
    )
  }

  return (
    <div>
      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-400">
        Last {games.length} game{games.length === 1 ? '' : 's'}
      </p>
      <table className="min-w-full text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="px-2 py-1 text-left font-medium">Date</th>
            <th className="px-2 py-1 text-left font-medium">Opponent</th>
            <th className="px-2 py-1 text-right font-medium">AB</th>
            <th className="px-2 py-1 text-right font-medium">H</th>
            <th className="px-2 py-1 text-right font-medium">HR</th>
            <th className="px-2 py-1 text-right font-medium">RBI</th>
            <th className="px-2 py-1 text-right font-medium">AVG</th>
          </tr>
        </thead>
        <tbody className="text-slate-200">
          {games.map((g) => (
            <tr key={g.stat_id} className="border-t border-slate-800/60">
              <td className="px-2 py-1 text-slate-400">{g.game_date}</td>
              <td className="px-2 py-1">
                {g.home_team} vs {g.away_team}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{g.at_bats}</td>
              <td className="px-2 py-1 text-right tabular-nums">{g.hits}</td>
              <td className="px-2 py-1 text-right tabular-nums">{g.home_runs}</td>
              <td className="px-2 py-1 text-right tabular-nums">{g.rbis}</td>
              <td className="px-2 py-1 text-right tabular-nums">
                {fmtAvg(g.batting_avg)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Skeleton ─────────────────────────────────────────────────────────────────

function SkeletonRows() {
  return Array.from({ length: 8 }).map((_, i) => (
    <tr key={`sk-${i}`} className="animate-pulse">
      {COLUMNS.map((c) => (
        <td key={c.key} className="px-3 py-3">
          <div
            className={[
              'h-3 rounded bg-slate-800',
              c.align === 'right' ? 'ml-auto w-12' : 'w-32',
            ].join(' ')}
          />
        </td>
      ))}
    </tr>
  ))
}
