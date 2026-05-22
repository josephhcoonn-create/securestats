/**
 * Tiny placeholder for routes that haven't been built out yet
 * (Leaders, Streaks, Compare) — filled in by Task 5.3 / 5.4.
 */
export default function PlaceholderPage({ title, subtitle }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/50 p-10 text-center">
      <h2 className="text-xl font-semibold text-white">{title}</h2>
      <p className="mt-2 text-sm text-slate-400">{subtitle}</p>
    </div>
  )
}
