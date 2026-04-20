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
  const cal = loadCalendar()
  const patterns = Object.entries(cal).map(([id, data]) => ({
    id,
    name: id,
    has_clean: false,
    pdf_count: 0,
    ...data,
  }))
  return NextResponse.json({ patterns, total: patterns.length })
}
