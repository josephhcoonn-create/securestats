/**
 * Daily Picks page — a tab strip that toggles between "Today's Picks"
 * and the "History" view without needing nested router routes.
 */
import { useState } from 'react'
import DailyPicks from '../components/DailyPicks'
import PicksHistory from '../components/PicksHistory'

const TABS = [
  { key: 'today', label: "Today's Picks" },
  { key: 'history', label: 'History' },
]

export default function DailyPicksPage() {
  const [tab, setTab] = useState('today')

  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-md bg-slate-900 p-1 ring-1 ring-slate-700">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={[
              'rounded px-3 py-1.5 text-sm font-medium transition-colors',
              tab === t.key
                ? 'bg-blue-600 text-white'
                : 'text-slate-300 hover:bg-slate-800',
            ].join(' ')}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'today' ? <DailyPicks /> : <PicksHistory />}
    </div>
  )
}
