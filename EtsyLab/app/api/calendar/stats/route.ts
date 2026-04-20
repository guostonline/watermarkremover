import { NextResponse } from 'next/server'
import { readFileSync, existsSync } from 'fs'
import path from 'path'

function calendarPath() {
  const candidates = [
    path.join(process.cwd(), '..', 'calendar_data.json'),
    path.join(process.cwd(), 'calendar_data.json'),
  ]
  return candidates.find(existsSync) ?? candidates[0]
}

function loadCalendar(): Record<string, Record<string, string>> {
  const p = calendarPath()
  if (!existsSync(p)) return {}
  return JSON.parse(readFileSync(p, 'utf-8'))
}

export async function GET() {
  const cal   = loadCalendar()
  const today = new Date().toISOString().split('T')[0]
  const vals  = Object.values(cal)

  const total   = vals.length
  const listed  = vals.filter(v => v.status === 'listed').length
  const pending = vals.filter(v => v.status === 'pending').length
  const todayIds = Object.entries(cal)
    .filter(([, v]) => v.date === today)
    .map(([id]) => id)

  return NextResponse.json({
    total,
    listed,
    pending,
    today: todayIds,
    revenue_est: parseFloat((listed * 4.99).toFixed(2)),
  })
}
