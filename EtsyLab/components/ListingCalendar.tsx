'use client'

import { useEffect, useState, useMemo } from 'react'
import { useToast, type Section } from '@/lib/context'
import {
  RefreshCw, Search, CheckCircle2, Clock, CalendarDays,
  ExternalLink, Sparkles, CheckSquare, Square,
} from 'lucide-react'

interface Pattern {
  id: string; name: string; has_clean: boolean; pdf_count: number
  status: 'listed' | 'pending'; date: string; listed_date: string | null
  etsy_url: string; price: string; notes: string
}

type Filter = 'all' | 'pending' | 'listed' | 'today'

interface Props { onNavigate: (s: Section) => void }

const TODAY = new Date().toISOString().split('T')[0]

export default function ListingCalendar({ onNavigate }: Props) {
  const [patterns, setPatterns] = useState<Pattern[]>([])
  const [loading,  setLoading]  = useState(true)
  const [query,    setQuery]    = useState('')
  const [filter,   setFilter]   = useState<Filter>('all')
  const { showToast } = useToast()

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const res  = await fetch('/api/calendar')
      const data = await res.json()
      setPatterns(data.patterns || [])
    } catch { showToast('Failed to load calendar', 'error') }
    finally  { setLoading(false) }
  }

  async function update(id: string, field: string, value: string) {
    try {
      await fetch('/api/calendar/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, [field]: value }),
      })
      setPatterns(prev => prev.map(p => p.id === id ? { ...p, [field]: value } : p))
    } catch { showToast('Update failed', 'error') }
  }

  async function toggleStatus(p: Pattern) {
    const newStatus = p.status === 'listed' ? 'pending' : 'listed'
    const listed_date = newStatus === 'listed' ? TODAY : null
    await update(p.id, 'status', newStatus)
    if (listed_date !== undefined) await update(p.id, 'listed_date', listed_date || '')
    showToast(newStatus === 'listed' ? `${p.name} marked as listed!` : `${p.name} set to pending`, 'success')
  }

  const filtered = useMemo(() => patterns.filter(p => {
    const matchQ = !query || p.name.toLowerCase().includes(query.toLowerCase())
    const matchF = filter === 'all'     ? true
                 : filter === 'listed'  ? p.status === 'listed'
                 : filter === 'pending' ? p.status === 'pending'
                 :                        p.date === TODAY
    return matchQ && matchF
  }), [patterns, query, filter])

  const stats = useMemo(() => ({
    total:   patterns.length,
    listed:  patterns.filter(p => p.status === 'listed').length,
    pending: patterns.filter(p => p.status === 'pending').length,
    today:   patterns.filter(p => p.date === TODAY).length,
  }), [patterns])

  const FILTERS: { key: Filter; label: string; count: number }[] = [
    { key: 'all',     label: 'All',     count: stats.total   },
    { key: 'pending', label: 'Pending', count: stats.pending  },
    { key: 'listed',  label: 'Listed',  count: stats.listed   },
    { key: 'today',   label: 'Today',   count: stats.today    },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="section-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-3xl font-semibold italic text-bark-900">Listing Calendar</h1>
            <p className="text-bark-400 text-sm mt-0.5">Track your 1-pattern-per-day publishing schedule</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="w-4 h-4 text-bark-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                className="input pl-9 w-52 py-2 text-sm"
                placeholder="Search patterns..."
                value={query}
                onChange={e => setQuery(e.target.value)}
              />
            </div>
            <button onClick={load} disabled={loading} className="btn-secondary gap-2 py-2">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1.5 mt-4">
          {FILTERS.map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)}
              className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-all ${
                filter === f.key
                  ? 'bg-brand-500 text-white shadow-brand-sm'
                  : 'bg-bark-100 text-bark-600 hover:bg-bark-200'
              }`}>
              {f.label}
              <span className={`ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold ${filter === f.key ? 'bg-white/20 text-white' : 'bg-bark-200 text-bark-500'}`}>
                {f.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-8 py-6">
        {loading ? (
          <div className="flex items-center justify-center h-64 gap-3 text-bark-400">
            <span className="spinner" /> Loading calendar...
          </div>
        ) : (
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-bark-50 border-b border-bark-100">
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400 w-10">#</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400">Pattern Name</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400 w-32">Date</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400 w-28">Status</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400 w-20">PDF</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400 w-24">Price</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400 w-44">Etsy URL</th>
                  <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-bark-400 w-24">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((p, i) => {
                  const isListed = p.status === 'listed'
                  const isToday  = p.date === TODAY
                  return (
                    <tr key={p.id}
                      className={`border-b border-bark-50 transition-colors hover:bg-bark-50/80 ${
                        isListed ? 'bg-emerald-50/40' : isToday ? 'bg-brand-50/40' : ''
                      }`}>
                      <td className={`px-4 py-3 text-xs text-bark-400 font-medium border-l-2 ${isListed ? 'border-emerald-400' : isToday ? 'border-brand-400' : 'border-transparent'}`}>
                        {i + 1}
                      </td>
                      <td className="px-4 py-3">
                        <p className="font-medium text-bark-800 text-xs truncate max-w-[200px]" title={p.name}>{p.name}</p>
                      </td>
                      <td className="px-4 py-3">
                        <input
                          type="date"
                          defaultValue={p.date}
                          className="text-xs bg-transparent border-0 p-0 text-bark-600 focus:outline-none focus:ring-0 cursor-pointer"
                          onBlur={e => update(p.id, 'date', e.target.value)}
                        />
                      </td>
                      <td className="px-4 py-3">
                        {isListed
                          ? <span className="badge-listed"><CheckCircle2 className="w-3 h-3" />Listed</span>
                          : isToday
                          ? <span className="badge-today"><CalendarDays className="w-3 h-3" />Today</span>
                          : <span className="badge-pending"><Clock className="w-3 h-3" />Pending</span>
                        }
                      </td>
                      <td className="px-4 py-3 text-center">
                        {p.has_clean
                          ? <span className="text-xs text-emerald-600 font-semibold">✓ Clean</span>
                          : <span className="text-xs text-bark-300">—</span>
                        }
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-0.5">
                          <span className="text-xs text-bark-400">$</span>
                          <input
                            type="number" step="0.01" min="0"
                            defaultValue={p.price}
                            className="w-14 text-xs bg-transparent border-0 p-0 text-bark-700 font-medium focus:outline-none focus:ring-0"
                            onBlur={e => update(p.id, 'price', e.target.value)}
                          />
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {p.etsy_url ? (
                          <a href={p.etsy_url} target="_blank" rel="noopener noreferrer"
                            className="text-xs text-brand-500 hover:text-brand-700 flex items-center gap-1 font-medium">
                            View <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : (
                          <input
                            type="url"
                            placeholder="Paste Etsy URL"
                            className="text-xs bg-transparent border-0 p-0 text-bark-400 placeholder-bark-300 focus:outline-none w-full"
                            onBlur={e => { if (e.target.value) update(p.id, 'etsy_url', e.target.value) }}
                          />
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button onClick={() => toggleStatus(p)} title={isListed ? 'Set to pending' : 'Mark as listed'}
                            className={`p-1.5 rounded-lg transition-all ${isListed ? 'text-emerald-600 hover:bg-emerald-100' : 'text-bark-400 hover:bg-bark-100'}`}>
                            {isListed ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                          </button>
                          <button onClick={() => onNavigate('listing-generator')} title="Generate listing"
                            className="p-1.5 rounded-lg text-bark-400 hover:text-brand-500 hover:bg-brand-50 transition-all">
                            <Sparkles className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-16 text-center text-bark-400 text-sm">
                      No patterns found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
