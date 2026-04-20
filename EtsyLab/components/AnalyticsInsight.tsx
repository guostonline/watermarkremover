'use client'

import { useState, useEffect } from 'react'
import { 
  TrendingUp, 
  BarChart3, 
  Target, 
  DollarSign, 
  ArrowUpRight, 
  ShoppingBag,
  Layers,
  Sparkles
} from 'lucide-react'

interface CategoryPerf {
  name: string
  sales: number
  conversion: number
  trend: 'up' | 'down' | 'steady'
}

export default function AnalyticsInsight() {
  const [targetMs, setTargetMs] = useState(6) // Months to reach target
  const [currentRev, setCurrentRev] = useState(1250)
  const targetRev = 5000
  
  const gap = targetRev - currentRev
  const monthlyIncrNeeded = Math.round(gap / targetMs)

  const categories: CategoryPerf[] = [
    { name: 'Dresses', sales: 450, conversion: 3.2, trend: 'up' },
    { name: 'Pants', sales: 320, conversion: 2.8, trend: 'up' },
    { name: 'Tops', sales: 280, conversion: 3.5, trend: 'steady' },
    { name: 'Jackets', sales: 120, conversion: 1.5, trend: 'down' },
    { name: 'Shorts', sales: 90, conversion: 2.2, trend: 'up' },
    { name: 'Skirts', sales: 60, conversion: 1.8, trend: 'steady' },
  ]

  return (
    <div>
      <div className="section-header">
        <h1 className="font-display text-3xl font-semibold text-bark-900 italic">Growth Analytics</h1>
        <p className="text-bark-400 text-sm mt-0.5">Strategy & projections for PatternsLabCo</p>
      </div>

      <div className="p-8 space-y-6">
        {/* Revenue Forecaster */}
        <div className="grid grid-cols-3 gap-6">
          <div className="col-span-2 card p-6 bg-gradient-to-br from-white to-bark-50">
            <div className="flex justify-between items-start mb-6">
              <div>
                <h3 className="text-lg font-bold text-bark-800 flex items-center gap-2">
                  <Target className="w-5 h-5 text-brand-500" />
                  Revenue Forecaster
                </h3>
                <p className="text-xs text-bark-400 mt-1">Projection to $5,000/month goal</p>
              </div>
              <div className="flex items-center gap-2 bg-brand-50 rounded-lg p-1 px-2 border border-brand-100">
                <span className="text-[10px] font-bold text-brand-600 uppercase tracking-tight">Window</span>
                <select 
                  value={targetMs} 
                  onChange={(e) => setTargetMs(Number(e.target.value))}
                  className="bg-transparent text-xs font-bold text-brand-700 outline-none cursor-pointer"
                >
                  <option value={3}>3 Months</option>
                  <option value={6}>6 Months</option>
                  <option value={12}>12 Months</option>
                </select>
              </div>
            </div>

            <div className="space-y-6">
              <div className="flex items-end gap-1">
                <span className="text-4xl font-display font-black text-bark-900">${currentRev}</span>
                <span className="text-bark-400 font-medium mb-1.5">/ mo currently</span>
                <div className="ml-auto text-right">
                  <span className="block text-[10px] font-black uppercase text-emerald-500 tracking-widest">Growth Needed</span>
                  <span className="text-xl font-display font-bold text-emerald-600">+${monthlyIncrNeeded}/mo</span>
                </div>
              </div>

              <div className="h-4 bg-bark-100 rounded-full overflow-hidden relative">
                <div 
                  className="h-full bg-brand-500 rounded-full transition-all duration-1000"
                  style={{ width: `${(currentRev / targetRev) * 100}%` }}
                />
                <div 
                  className="absolute top-0 right-0 h-full border-l-2 border-dashed border-bark-400 transition-all duration-500 flex items-center pr-2"
                  style={{ left: '100%' }}
                >
                  <span className="text-[8px] font-black text-bark-400 uppercase bg-bark-50 px-1 ml-1 whitespace-nowrap">Target $5k</span>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4 pt-2">
                <div className="bg-bark-50/50 p-3 rounded-xl border border-bark-100">
                  <p className="text-[10px] font-bold text-bark-400 uppercase tracking-wide mb-1">AOV Goal</p>
                  <p className="text-lg font-bold text-bark-800">$12.50 <span className="text-[10px] text-emerald-500">+25%</span></p>
                </div>
                <div className="bg-bark-50/50 p-3 rounded-xl border border-bark-100">
                  <p className="text-[10px] font-bold text-bark-400 uppercase tracking-wide mb-1">Listings Req.</p>
                  <p className="text-lg font-bold text-bark-800">180 <span className="text-[10px] text-bark-400">Total</span></p>
                </div>
                <div className="bg-bark-50/50 p-3 rounded-xl border border-bark-100">
                  <p className="text-[10px] font-bold text-bark-400 uppercase tracking-wide mb-1">Conv. Rate</p>
                  <p className="text-lg font-bold text-bark-800">3.1% <span className="text-[10px] text-brand-500">Target</span></p>
                </div>
              </div>
            </div>
          </div>

          {/* Strategy Tip */}
          <div className="bg-emerald-600 rounded-2xl p-6 text-white flex flex-col justify-between overflow-hidden relative">
             <div className="absolute -top-6 -right-6 w-24 h-24 bg-white/10 rounded-full blur-2xl" />
             <div className="absolute -bottom-10 -left-10 w-32 h-32 bg-white/5 rounded-full blur-3xl" />
             
             <div>
               <div className="flex items-center gap-2 mb-3">
                 <Sparkles className="w-4 h-4 text-emerald-200" />
                 <span className="text-[10px] font-black tracking-widest text-emerald-200 uppercase">Growth Hack</span>
               </div>
               <h4 className="text-xl font-display font-black italic leading-tight mb-2">The "Bundle" Multiplier</h4>
               <p className="text-xs text-emerald-50 leading-relaxed opacity-90">
                 You have 497 patterns. By creating themed bundles (e.g., "5 Summer Dresses"), you can increase your Average Order Value (AOV) from $4.99 to $19.99 overnight.
               </p>
             </div>
             
             <div className="mt-4 pt-4 border-t border-white/20">
               <div className="flex justify-between items-center text-[10px] font-black uppercase tracking-widest text-emerald-200">
                 <span>Projected Lift</span>
                 <span>+40% Revenue</span>
               </div>
             </div>
          </div>
        </div>

        {/* Category Performance */}
        <div className="grid grid-cols-2 gap-6">
          <div className="card p-6">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-lg font-bold text-bark-800 flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-brand-500" />
                Category Performance
              </h3>
              <span className="text-[10px] font-bold text-bark-400 uppercase tracking-widest">30 Day Sales</span>
            </div>

            <div className="space-y-4">
              {categories.map((cat) => (
                <div key={cat.name} className="flex items-center gap-4">
                  <div className="w-20 text-xs font-bold text-bark-600">{cat.name}</div>
                  <div className="flex-1 h-2.5 bg-bark-100 rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-brand-500 rounded-full"
                      style={{ width: `${(cat.sales / 500) * 100}%` }}
                    />
                  </div>
                  <div className="w-16 text-right">
                    <span className="text-xs font-black text-bark-800">{cat.sales}</span>
                    <span className={`ml-1.5 text-[10px] font-bold ${
                      cat.trend === 'up' ? 'text-emerald-500' : 
                      cat.trend === 'down' ? 'text-red-500' : 'text-bark-400'
                    }`}>
                      {cat.trend === 'up' ? '↑' : cat.trend === 'down' ? '↓' : '→'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
            
            <div className="mt-8 p-4 bg-bark-50 rounded-xl border border-dashed border-bark-200 text-center">
               <p className="text-xs text-bark-500 italic">"Focus on **Dresses** and **Pants**. They represent 62% of your revenue with higher-than-average conversion."</p>
            </div>
          </div>

          <div className="card p-6 flex flex-col">
             <h3 className="text-lg font-bold text-bark-800 mb-6 flex items-center gap-2">
                <Layers className="w-5 h-5 text-brand-500" />
                Inventory Distribution
             </h3>
             <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
                {/* Visual representation of the inventory */}
                <div className="relative w-40 h-40 flex items-center justify-center">
                  <div className="absolute inset-0 border-8 border-bark-100 rounded-full" />
                  <div 
                    className="absolute inset-0 border-8 border-brand-500 rounded-full"
                    style={{ clipPath: 'polygon(50% 50%, 50% 0, 100% 0, 100% 100%, 0 100%, 0 0, 50% 0)' }}
                  />
                  <div className="text-center">
                    <p className="text-4xl font-display font-black text-bark-900">497</p>
                    <p className="text-[10px] font-black text-bark-400 uppercase tracking-widest mt-0.5">Patterns</p>
                  </div>
                </div>
                
                <div className="grid grid-cols-2 gap-x-8 gap-y-3 mt-8 w-full">
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-brand-500" />
                    <span className="text-xs text-bark-600 font-medium">Listed (142)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-bark-200" />
                    <span className="text-xs text-bark-600 font-medium">Pending (355)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-brand-300" />
                    <span className="text-xs text-bark-600 font-medium">Hot Items (24)</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-amber-400" />
                    <span className="text-xs text-bark-600 font-medium">Low Stock (8)</span>
                  </div>
                </div>
             </div>
          </div>
        </div>
      </div>
    </div>
  )
}
