'use client'

import { useState, useCallback } from 'react'
import { ToastContext, type Section } from '@/lib/context'
import Sidebar from '@/components/Sidebar'
import Dashboard from '@/components/Dashboard'
import ImageSplitter from '@/components/ImageSplitter'

import ListingGenerator from '@/components/ListingGenerator'
import ListingCalendar from '@/components/ListingCalendar'
import CoverCreator from '@/components/CoverCreator'
import AnalyticsInsight from '@/components/AnalyticsInsight'
import Toast, { type ToastItem } from '@/components/Toast'

export default function Home() {
  const [section, setSection] = useState<Section>('dashboard')
  const [toasts, setToasts]   = useState<ToastItem[]>([])

  const showToast = useCallback((msg: string, type: ToastItem['type'] = 'success') => {
    const id = Date.now()
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3600)
  }, [])

  const sections: Record<Section, React.ReactNode> = {
    'dashboard':         <Dashboard onNavigate={setSection} />,
    'image-splitter':    <ImageSplitter />,
   
    'listing-generator': <ListingGenerator />,
    'calendar':          <ListingCalendar onNavigate={setSection} />,
    'cover-creator':     <CoverCreator />,
    'analytics':         <AnalyticsInsight />,
  }

  return (
    <ToastContext.Provider value={{ showToast }}>
      <div className="flex h-screen overflow-hidden">
        <Sidebar active={section} onNavigate={setSection} />
        <main className="flex-1 overflow-y-auto bg-bark-50">
          <div key={section} className="animate-fade-up min-h-full">
            {sections[section]}
          </div>
        </main>
      </div>
      <Toast toasts={toasts} />
    </ToastContext.Provider>
  )
}
