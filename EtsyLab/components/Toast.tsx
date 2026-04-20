'use client'

import { CheckCircle2, XCircle, Info } from 'lucide-react'

export interface ToastItem {
  id: number
  msg: string
  type: 'success' | 'error' | 'info'
}

const icons = {
  success: <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />,
  error:   <XCircle      className="w-4 h-4 text-red-500 flex-shrink-0" />,
  info:    <Info         className="w-4 h-4 text-sky-500 flex-shrink-0" />,
}

const styles = {
  success: 'border-emerald-100 bg-white',
  error:   'border-red-100 bg-white',
  info:    'border-sky-100 bg-white',
}

export default function Toast({ toasts }: { toasts: ToastItem[] }) {
  return (
    <div className="fixed bottom-6 right-6 flex flex-col gap-2 z-50 pointer-events-none">
      {toasts.map(t => (
        <div
          key={t.id}
          className={`animate-toast-in flex items-center gap-3 px-4 py-3 rounded-xl border shadow-warm-lg text-sm text-bark-800 font-medium max-w-sm ${styles[t.type]}`}
        >
          {icons[t.type]}
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  )
}
