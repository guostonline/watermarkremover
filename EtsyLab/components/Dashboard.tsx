'use client'

import { useEffect, useState } from 'react'
import { useToast, type Section } from '@/lib/context'
import {
  Package, CheckCircle2, Clock, TrendingUp,
  Zap, ArrowRight, Grid3X3, ShieldOff, FileEdit, CalendarDays,
} from 'lucide-react'

interface Stats {
  total: number
  listed: number
  pending: number
  today: string[]
  revenue_est: number
}

interface Props { onNavigate: (s: Section) => void }

export default function Dashboard({ onNavigate }: Props) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const { showToast } = useToast()

  useEffect(() => { load() }, [])

  async function load() {
    try {
      const res = await fetch('/api/calendar/stats')
      if (!res.ok) throw new Error('Failed')
      setStats(await res.json())
    } catch {
      showToast('Could not load dashboard data', 'error')
    } finally {
      setLoading(false)
    }
  }

  const pct        = stats && stats.total ? Math.round(stats.listed / stats.total * 100) : 0
  const daysLeft   = stats ? stats.total - stats.listed : 0
  const completion = (() => {
    const d = new Date()
    d.setDate(d.getDate() + daysLeft)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  })()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  })

  return (
    <div>
      {/* Header */}
      <div className="section-header">
        <h1 className="font-display text-3xl font-semibold text-bark-900 italic">Dashboard</h1>
        <p className="text-bark-400 text-sm mt-0.5">{today}</p>
      </div>

      <div className="p-8 space-y-6">

        {/* Stat Cards */}
        {loading ? (
          <div className="grid grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="card p-5 animate-pulse">
                <div className="h-10 w-10 bg-bark-100 rounded-xl mb-3" />
                <div className="h-8 w-16 bg-bark-100 rounded-lg mb-2" />
                <div className="h-3 w-24 bg-bark-100 rounded" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-4">
            <StatCard label="Total Patterns" value={stats?.total ?? 0}        icon={Package}      color="bark"    />
            <StatCard label="Listed on Etsy" value={stats?.listed ?? 0}       icon={CheckCircle2} color="green"   />
            <StatCard label="Pending"        value={stats?.pending ?? 0}      icon={Clock}        color="orange"  />
            <StatCard label="Est. Revenue"   value={`$${(stats?.revenue_est ?? 0).toFixed(0)}`} icon={TrendingUp} color="sky" />
          </div>
        )}

        {/* Progress + Today's Pattern */}
        <div className="grid grid-cols-3 gap-4">
          {/* Progress */}
          <div className="col-span-2 card p-6">
            <h2 className="font-display text-xl font-semibold text-bark-900 italic mb-5">
              Publishing Progress
            </h2>
            <div className="mb-4">
              <div className="flex justify-between text-xs text-bark-500 mb-2 font-medium">
                <span>{stats?.listed ?? 0} of {stats?.total ?? 0} listed</span>
                <span className="text-brand-500 font-bold">{pct}%</span>
              </div>
              <div className="h-2.5 bg-bark-100 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-400 transition-all duration-700"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 mt-5">
              <div className="bg-brand-50 border border-brand-100 rounded-xl p-4 text-center">
                <p className="text-[10px] text-bark-500 font-semibold uppercase tracking-wide mb-1">Days Remaining</p>
                <p className="font-display text-3xl font-bold text-brand-600">{daysLeft}</p>
              </div>
              <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-4 text-center">
                <p className="text-[10px] text-bark-500 font-semibold uppercase tracking-wide mb-1">Completion Date</p>
                <p className="font-display text-lg font-bold text-emerald-700 mt-1">{completion}</p>
              </div>
            </div>
          </div>

          {/* Today's Pattern */}
          <div className="bg-gradient-to-br from-brand-500 to-brand-700 rounded-2xl p-6 text-white flex flex-col">
            <div className="flex items-center gap-2 mb-3">
              <Zap className="w-4 h-4 opacity-80" />
              <span className="text-xs font-semibold tracking-wide opacity-80 uppercase">Today's Pattern</span>
            </div>
            {stats?.today?.length ? (
              <>
                <p className="font-display text-xl font-semibold italic leading-snug flex-1 mb-5">
                  {stats.today[0]}
                </p>
                <button
                  onClick={() => onNavigate('listing-generator')}
                  className="flex items-center gap-2 bg-white/20 hover:bg-white/30 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all self-start"
                >
                  Generate Listing <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </>
            ) : (
              <p className="text-sm opacity-60 flex-1 mt-2">
                No pattern scheduled for today — check the calendar!
              </p>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="card p-6">
          <h2 className="font-display text-xl font-semibold text-bark-900 italic mb-4">Quick Actions</h2>
          <div className="flex flex-wrap gap-3">
            {[
              { label: 'Split Grid Images',    icon: Grid3X3,    section: 'image-splitter'    as const },
              { label: 'Remove Watermark',     icon: ShieldOff,  section: 'watermark'         as const },
              { label: 'Generate Listing',     icon: FileEdit,   section: 'listing-generator' as const },
              { label: 'View Calendar',        icon: CalendarDays, section: 'calendar'        as const },
            ].map(({ label, icon: Icon, section }) => (
              <button
                key={section}
                onClick={() => onNavigate(section)}
                className="btn-secondary text-sm gap-2"
              >
                <Icon className="w-4 h-4" strokeWidth={1.5} />
                {label}
              </button>
            ))}
          </div>
        </div>

      </div>
    </div>
  )
}

function StatCard({
  label, value, icon: Icon, color,
}: {
  label: string; value: number | string; icon: React.ElementType
  color: 'bark' | 'green' | 'orange' | 'sky'
}) {
  const palettes = {
    bark:   { bg: 'bg-bark-100',    icon: 'text-bark-600',    val: 'text-bark-900' },
    green:  { bg: 'bg-emerald-50',  icon: 'text-emerald-600', val: 'text-emerald-700' },
    orange: { bg: 'bg-brand-50',    icon: 'text-brand-500',   val: 'text-brand-600' },
    sky:    { bg: 'bg-sky-50',      icon: 'text-sky-500',     val: 'text-sky-700' },
  }
  const p = palettes[color]
  return (
    <div className="card p-5 flex flex-col">
      <div className={`w-10 h-10 ${p.bg} ${p.icon} rounded-xl flex items-center justify-center mb-3`}>
        <Icon className="w-5 h-5" strokeWidth={1.5} />
      </div>
      <div className={`font-display text-3xl font-bold ${p.val}`}>{value}</div>
      <div className="text-[11px] text-bark-400 font-semibold mt-1 uppercase tracking-wide">{label}</div>
    </div>
  )
}
