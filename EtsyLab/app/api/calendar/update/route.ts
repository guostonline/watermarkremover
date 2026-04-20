import { NextResponse } from 'next/server'
import { readFileSync, writeFileSync, existsSync } from 'fs'
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

const ALLOWED_FIELDS = ['status', 'date', 'listed_date', 'etsy_url', 'price', 'notes']

export async function POST(request: Request) {
  const body = await request.json()
  const { id, ...fields } = body as Record<string, string>

  if (!id) return NextResponse.json({ error: 'id required' }, { status: 400 })

  const cal = loadCalendar()
  if (!cal[id]) cal[id] = {}

  for (const field of ALLOWED_FIELDS) {
    if (field in fields) cal[id][field] = fields[field]
  }

  writeFileSync(calendarPath(), JSON.stringify(cal, null, 2))
  return NextResponse.json({ success: true })
}
