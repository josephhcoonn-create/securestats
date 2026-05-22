/**
 * Typeahead player picker (Headless UI Combobox).
 *
 * Calls /players/search?q=… with 300ms debounce. The caller controls
 * the selected value via { value, onChange } where value is a
 * PlayerSummary (or null) and onChange receives a PlayerSummary or null.
 *
 *   <PlayerSearchInput
 *     value={selected}
 *     onChange={setSelected}
 *     placeholder="Find a player…"
 *   />
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Combobox,
  ComboboxButton,
  ComboboxInput,
  ComboboxOption,
  ComboboxOptions,
} from '@headlessui/react'
import api from '../api/client'

function useDebounced(value, delay = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return v
}

export default function PlayerSearchInput({
  value,
  onChange,
  placeholder = 'Search players…',
  disabled = false,
  className = '',
}) {
  const [query, setQuery] = useState('')
  const debounced = useDebounced(query, 300)

  const { data, isFetching } = useQuery({
    queryKey: ['player-search', debounced],
    queryFn: async () => {
      if (!debounced.trim()) return { items: [] }
      const { data } = await api.get('/players/search', {
        params: { q: debounced, limit: 10 },
      })
      return data
    },
    enabled: debounced.trim().length > 0,
    staleTime: 30_000,
  })

  const options = data?.items ?? []

  return (
    <Combobox value={value} onChange={onChange} disabled={disabled}>
      <div className={`relative ${className}`}>
        <ComboboxInput
          className="w-full rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30 disabled:opacity-50"
          placeholder={placeholder}
          displayValue={(p) => p?.full_name ?? ''}
          onChange={(e) => setQuery(e.target.value)}
        />
        <ComboboxButton className="absolute inset-y-0 right-0 flex items-center px-2 text-slate-400">
          ▾
        </ComboboxButton>

        {(options.length > 0 || isFetching) && (
          <ComboboxOptions className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-700 bg-slate-900 py-1 text-sm shadow-lg ring-1 ring-black/40 focus:outline-none">
            {isFetching && options.length === 0 && (
              <div className="px-3 py-2 text-slate-500">Searching…</div>
            )}
            {options.map((p) => (
              <ComboboxOption
                key={p.id}
                value={p}
                className={({ focus }) =>
                  [
                    'cursor-pointer px-3 py-2',
                    focus ? 'bg-blue-600 text-white' : 'text-slate-200',
                  ].join(' ')
                }
              >
                <div className="flex items-center justify-between gap-3">
                  <span>{p.full_name}</span>
                  <span className="text-xs text-slate-400">
                    {p.team} · {p.position}
                  </span>
                </div>
              </ComboboxOption>
            ))}
          </ComboboxOptions>
        )}
      </div>
    </Combobox>
  )
}
