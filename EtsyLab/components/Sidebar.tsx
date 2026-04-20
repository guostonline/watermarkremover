'use client'

import { type Section } from '@/lib/context'
import {
  LayoutDashboard, Scissors, Grid3X3, ShieldOff,
  FileEdit, CalendarDays, Palette, TrendingUp,
} from 'lucide-react'

interface NavItem {
  id: Section
  label: string
  icon: React.ElementType
  group: 'overview' | 'tools' | 'planning'
}

const NAV: NavItem[] = [
  { id: 'dashboard',         label: 'Dashboard',         icon: LayoutDashboard, group: 'overview'  },
  { id: 'analytics',         label: 'Growth Analytics',  icon: TrendingUp,      group: 'overview'  },
  { id: 'image-splitter',    label: 'Image Splitter',    icon: Grid3X3,         group: 'tools'     },
  { id: 'watermark',         label: 'Watermark Remover', icon: ShieldOff,       group: 'tools'     },
  { id: 'listing-generator', label: 'Listing Generator', icon: FileEdit,        group: 'tools'     },
  { id: 'calendar',          label: 'Listing Calendar',  icon: CalendarDays,    group: 'planning'  },
  { id: 'cover-creator',     label: 'Cover Creator',     icon: Palette,         group: 'planning'  },
]

interface Props {
  active: Section
  onNavigate: (s: Section) => void
}

export default function Sidebar({ active, onNavigate }: Props) {
  return (
    <aside className="w-[256px] min-h-screen flex-shrink-0 bg-bark-950 sidebar-texture flex flex-col border-r border-white/5">

      {/* Brand */}
      <div className="px-6 py-5 border-b border-white/8">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-brand-500 shadow-brand-sm flex items-center justify-center">
            <Scissors className="w-[18px] h-[18px] text-white" strokeWidth={1.75} />
          </div>
          <div>
            <div className="font-display text-[1.25rem] font-semibold text-white leading-none tracking-tight">
              EtsyLab
            </div>
            <div className="text-[10px] text-bark-500 font-sans mt-0.5 tracking-wide">
              PatternsLabCo
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
        <NavGroup
          label="Overview"
          items={NAV.filter(n => n.group === 'overview')}
          active={active}
          onNavigate={onNavigate}
        />
        <NavGroup
          label="Tools"
          items={NAV.filter(n => n.group === 'tools')}
          active={active}
          onNavigate={onNavigate}
        />
        <NavGroup
          label="Planning"
          items={NAV.filter(n => n.group === 'planning')}
          active={active}
          onNavigate={onNavigate}
        />
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-white/8">
        <p className="text-[10px] text-bark-600 text-center tracking-wider">
          v2.0 &nbsp;·&nbsp; EtsyLab Manager
        </p>
      </div>
    </aside>
  )
}

function NavGroup({
  label, items, active, onNavigate,
}: {
  label: string
  items: NavItem[]
  active: Section
  onNavigate: (s: Section) => void
}) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-bark-600 px-3 mb-1.5">
        {label}
      </p>
      {items.map(item => {
        const Icon    = item.icon
        const isActive = active === item.id
        return (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl mb-0.5 text-left text-sm font-medium transition-all duration-150 ${
              isActive
                ? 'bg-brand-500/15 text-brand-300 border-l-2 border-brand-400 pl-[10px]'
                : 'text-bark-400 hover:text-bark-100 hover:bg-white/6'
            }`}
          >
            <Icon className="w-4 h-4 flex-shrink-0" strokeWidth={isActive ? 2 : 1.5} />
            <span>{item.label}</span>
          </button>
        )
      })}
    </div>
  )
}
