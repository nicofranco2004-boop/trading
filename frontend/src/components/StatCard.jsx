import { colorClass } from '../utils/format'

export default function StatCard({ label, value, sub, positive }) {
  const color = positive == null ? '' : positive ? 'text-emerald-400' : 'text-red-400'
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color || 'text-slate-100'}`}>{value}</p>
      {sub && <p className="text-slate-500 text-xs mt-1">{sub}</p>}
    </div>
  )
}
