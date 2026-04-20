'use client'

import { useState, useEffect } from 'react'
import { useToast } from '@/lib/context'
import { generateListing, type ListingResult } from '@/lib/listing'
import { Sparkles, Copy, Check, RotateCcw, Lightbulb, CalendarDays } from 'lucide-react'

const CATEGORIES = [
  { value: 'dress',   label: 'Dress' },
  { value: 'pants',   label: 'Pants / Trousers' },
  { value: 'skirt',   label: 'Skirt' },
  { value: 'shorts',  label: 'Shorts' },
  { value: 'top',     label: 'Top / Blouse' },
  { value: 'jacket',  label: 'Jacket / Coat' },
  { value: 'other',   label: 'Other' },
]

const TIPS = [
  'Use all 13 tags (max 20 chars each)',
  'Put best keywords at the START of title',
  'Include "pdf", "pattern", "digital" in tags',
  'Mention "instant download" in description',
  'Add size info (A4, US Letter, A0)',
  'Update listings every 3–4 months to stay fresh',
  'Reply to all reviews for social proof',
  'Use all 10 listing photos for max visibility',
]

interface Pattern {
  id: string
  name: string
  status: 'listed' | 'pending'
  date: string
}

export default function ListingGenerator() {
  const [name,     setName]     = useState('')
  const [category, setCategory] = useState('dress')
  const [style,    setStyle]    = useState('')
  const [listing,  setListing]  = useState<ListingResult | null>(null)
  const [copied,   setCopied]   = useState<string | null>(null)
  const [nextPattern, setNextPattern] = useState<Pattern | null>(null)
  const { showToast } = useToast()

  function cleanName(raw: string) {
    return raw.replace(/^\d+\s*[-]\s*/, '').trim()
  }

  // Auto-detect category from name while typing
  function onNameChange(v: string) {
    setName(v)
    const l = v.toLowerCase()
    for (const cat of CATEGORIES) {
      if (cat.value !== 'other' && l.includes(cat.value)) { setCategory(cat.value); break }
    }
    if (l.includes('blouse') || (l.includes('top') && !l.includes('laptop'))) setCategory('top')
    if (l.includes('coat')) setCategory('jacket')
  }

  useEffect(() => {
    fetch('/api/calendar')
      .then(res => res.json())
      .then(data => {
        if (data.patterns) {
          const next = data.patterns
            .filter((p: Pattern) => p.status === 'pending')
            .sort((a: Pattern, b: Pattern) => a.date.localeCompare(b.date))[0]
          if (next) {
            setNextPattern(next)
            // Auto-fill if name is empty
            const cleaned = cleanName(next.name)
            setName(prev => prev ? prev : cleaned)
            // If we set it, also detect category
            const l = cleaned.toLowerCase()
            for (const cat of CATEGORIES) {
              if (cat.value !== 'other' && l.includes(cat.value)) { setCategory(cat.value); break }
            }
            if (l.includes('blouse') || (l.includes('top') && !l.includes('laptop'))) setCategory('top')
            if (l.includes('coat')) setCategory('jacket')
          }
        }
      })
      .catch(() => console.error('Failed to fetch next pattern'))
  }, [])

  function generate() {
    if (!name.trim()) { showToast('Enter a pattern name', 'error'); return }
    const result = generateListing(name.trim(), category, style)
    setListing(result)
    showToast('Listing generated!', 'success')
  }

  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key); setTimeout(() => setCopied(null), 2000)
      showToast('Copied!', 'success')
    })
  }

  function copyAll() {
    if (!listing) return
    copy(
      `TITLE:\n${listing.title}\n\nTAGS:\n${listing.tags.join(', ')}\n\nDESCRIPTION:\n${listing.description}`,
      'all',
    )
  }

  return (
    <div>
      <div className="section-header">
        <h1 className="font-display text-3xl font-semibold italic text-bark-900">Listing Generator</h1>
        <p className="text-bark-400 text-sm mt-0.5">Generate Etsy-optimized title, 13 tags & description instantly — no server needed</p>
      </div>

      <div className="p-8 space-y-6">
        {nextPattern && (
          <div className="card-glass p-5 flex items-center justify-between border-brand-200/50 animate-fade-in shadow-brand-sm">
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 rounded-full bg-brand-100 flex items-center justify-center text-brand-600">
                <CalendarDays className="w-5 h-5" />
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold tracking-widest text-brand-500">Next Scheduled Pattern</p>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-semibold text-bark-900">{cleanName(nextPattern.name)}</h3>
                  <span className="text-xs text-bark-400 font-medium bg-bark-100 px-2 py-0.5 rounded-full">{nextPattern.date}</span>
                </div>
              </div>
            </div>
            <button 
              onClick={() => {
                const cleaned = cleanName(nextPattern.name)
                setName(cleaned)
                onNameChange(cleaned)
                showToast(`Loaded: ${cleaned}`)
              }} 
              className="btn-primary py-2.5 px-6 text-sm gap-2"
            >
              <Sparkles className="w-4 h-4" /> Use This Pattern
            </button>
          </div>
        )}
        <div className="grid grid-cols-2 gap-5">

          {/* Form */}
          <div className="card p-6 space-y-4">
            <h2 className="font-display text-xl font-semibold italic text-bark-900">Pattern Details</h2>

            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-bark-500 block mb-2">Pattern Name *</label>
              <input className="input" placeholder="e.g. Summer Maxi Dress"
                value={name} onChange={e => onNameChange(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && generate()} />
            </div>

            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-bark-500 block mb-2">Category</label>
              <select className="input" value={category} onChange={e => setCategory(e.target.value)}>
                {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>

            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-bark-500 block mb-2">Style Keywords</label>
              <input className="input" placeholder="e.g. boho, summer, casual, vintage"
                value={style} onChange={e => setStyle(e.target.value)} />
            </div>

            <button onClick={generate} disabled={!name.trim()} className="btn-primary w-full justify-center py-3 text-base">
              <Sparkles className="w-5 h-5" /> Generate Listing
            </button>
          </div>

          {/* Tips */}
          <div className="card p-6">
            <div className="flex items-center gap-2 mb-4">
              <Lightbulb className="w-5 h-5 text-brand-500" strokeWidth={1.5} />
              <h2 className="font-display text-xl font-semibold italic text-bark-900">Tips for Better Rankings</h2>
            </div>
            <ul className="space-y-2.5">
              {TIPS.map((tip, i) => (
                <li key={i} className="flex items-start gap-2.5 text-sm text-bark-600">
                  <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center flex-shrink-0 text-xs font-bold mt-0.5">✓</span>
                  {tip}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Output */}
        {listing && (
          <div className="animate-fade-up card p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="font-display text-xl font-semibold italic text-bark-900">Generated Listing</h2>
              <div className="flex gap-2">
                <button onClick={copyAll} className="btn-secondary text-xs gap-1.5">
                  {copied === 'all' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                  Copy Everything
                </button>
                <button onClick={() => setListing(null)} className="btn-ghost">
                  <RotateCcw className="w-3.5 h-3.5" /> Reset
                </button>
              </div>
            </div>

            {/* Title */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[10px] font-bold uppercase tracking-widest text-bark-400">Title</label>
                <span className={`text-xs font-bold ${listing.char_count > 130 ? 'text-amber-500' : 'text-emerald-500'}`}>
                  {listing.char_count}/140 chars
                </span>
              </div>
              <div className="relative bg-bark-50 border border-bark-200 rounded-xl p-4 pr-20">
                <p className="text-sm text-bark-800 leading-relaxed">{listing.title}</p>
                <button onClick={() => copy(listing.title, 'title')}
                  className="absolute top-3 right-3 btn-ghost py-1 px-2 text-xs">
                  {copied === 'title' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}
                </button>
              </div>
            </div>

            {/* Tags */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[10px] font-bold uppercase tracking-widest text-bark-400">Tags</label>
                <span className="text-xs font-bold text-brand-500">{listing.tag_count}/13 tags</span>
              </div>
              <div className="flex flex-wrap gap-2 mb-3">
                {listing.tags.map((tag, i) => <span key={i} className="tag-chip">{tag}</span>)}
              </div>
              <button onClick={() => copy(listing.tags.join(', '), 'tags')} className="btn-outline text-xs gap-1.5">
                {copied === 'tags' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                Copy All Tags
              </button>
            </div>

            {/* Description */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[10px] font-bold uppercase tracking-widest text-bark-400">Description</label>
                <button onClick={() => copy(listing.description, 'desc')} className="btn-ghost py-1 px-2 text-xs">
                  {copied === 'desc' ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />} Copy
                </button>
              </div>
              <textarea className="input font-mono text-xs leading-relaxed resize-y" rows={12}
                value={listing.description}
                onChange={e => setListing({ ...listing, description: e.target.value })} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
