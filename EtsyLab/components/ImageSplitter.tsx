'use client'

import { useRef, useState } from 'react'
import { useToast } from '@/lib/context'
import { Scissors, Download, Archive, Image as ImageIcon } from 'lucide-react'

interface SplitImage {
  index: number
  filename: string
  dataUrl: string
  width: number
  height: number
}

// ── Canvas-based image splitting (no server) ──────────────────────────────

function loadImg(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload  = () => { resolve(img) }
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not load image')) }
    img.src = url
  })
}

async function splitImages(
  frontFile: File, backFile: File, cols: number, rows: number,
): Promise<SplitImage[]> {
  const [fi, bi] = await Promise.all([loadImg(frontFile), loadImg(backFile)])

  const cellFW = fi.naturalWidth  / cols
  const cellFH = fi.naturalHeight / rows
  const cellBW = bi.naturalWidth  / cols
  const cellBH = bi.naturalHeight / rows
  const gap    = 8
  const results: SplitImage[] = []

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const tH      = Math.round(cellFH)
      const ratio   = tH / cellBH
      const scaledBW = Math.round(cellBW * ratio)
      const tW      = Math.round(cellFW) + gap + scaledBW

      const canvas  = document.createElement('canvas')
      canvas.width  = tW
      canvas.height = tH
      const ctx     = canvas.getContext('2d')!

      ctx.fillStyle = '#F8F6F0'
      ctx.fillRect(0, 0, tW, tH)
      ctx.drawImage(fi, c * cellFW, r * cellFH, cellFW, cellFH, 0, 0, Math.round(cellFW), tH)
      ctx.drawImage(bi, c * cellBW, r * cellBH, cellBW, cellBH, Math.round(cellFW) + gap, 0, scaledBW, tH)

      const idx = r * cols + c + 1
      results.push({
        index:   idx,
        filename: `model_${String(idx).padStart(2, '0')}_combined.jpg`,
        dataUrl:  canvas.toDataURL('image/jpeg', 0.92),
        width:   tW,
        height:  tH,
      })
    }
  }

  URL.revokeObjectURL(fi.src)
  URL.revokeObjectURL(bi.src)
  return results
}

function downloadOne(img: SplitImage) {
  const a = document.createElement('a')
  a.href = img.dataUrl
  a.download = img.filename
  a.click()
}

async function downloadAll(images: SplitImage[]) {
  for (let i = 0; i < images.length; i++) {
    await new Promise<void>(res => setTimeout(() => { downloadOne(images[i]); res() }, i * 200))
  }
}

// ── Component ─────────────────────────────────────────────────────────────

export default function ImageSplitter() {
  const [frontFile, setFrontFile] = useState<File | null>(null)
  const [backFile,  setBackFile]  = useState<File | null>(null)
  const [frontPrev, setFrontPrev] = useState('')
  const [backPrev,  setBackPrev]  = useState('')
  const [cols,    setCols]    = useState(3)
  const [rows,    setRows]    = useState(2)
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<SplitImage[]>([])
  const [frontDrag, setFrontDrag] = useState(false)
  const [backDrag,  setBackDrag]  = useState(false)
  const frontRef = useRef<HTMLInputElement>(null)
  const backRef  = useRef<HTMLInputElement>(null)
  const { showToast } = useToast()

  function setFront(f: File) {
    setFrontFile(f)
    const r = new FileReader(); r.onload = e => setFrontPrev(e.target?.result as string); r.readAsDataURL(f)
  }
  function setBack(f: File) {
    setBackFile(f)
    const r = new FileReader(); r.onload = e => setBackPrev(e.target?.result as string); r.readAsDataURL(f)
  }

  async function split() {
    if (!frontFile || !backFile) { showToast('Upload both front and back images first', 'error'); return }
    setLoading(true); setResults([])
    try {
      const imgs = await splitImages(frontFile, backFile, cols, rows)
      setResults(imgs)
      showToast(`${imgs.length} images created!`, 'success')
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : 'Split failed', 'error')
    } finally { setLoading(false) }
  }

  return (
    <div>
      <div className="section-header">
        <h1 className="font-display text-3xl font-semibold italic text-bark-900">Image Grid Splitter</h1>
        <p className="text-bark-400 text-sm mt-0.5">Upload front & back collages — get each model paired side by side</p>
      </div>

      <div className="p-8 space-y-6">
        <div className="grid grid-cols-2 gap-5">

          {/* Upload card */}
          <div className="card p-6 space-y-5">
            <h2 className="font-display text-xl font-semibold italic text-bark-900">Upload Images</h2>

            {[
              { label: 'Front View Grid', hint: 'JPG or PNG', file: frontFile, prev: frontPrev,
                drag: frontDrag, ref: frontRef, onFile: setFront,
                onDragIn: () => setFrontDrag(true), onDragOut: () => setFrontDrag(false) },
              { label: 'Back View Grid',  hint: 'Same layout as front', file: backFile, prev: backPrev,
                drag: backDrag,  ref: backRef,  onFile: setBack,
                onDragIn: () => setBackDrag(true),  onDragOut: () => setBackDrag(false) },
            ].map(({ label, hint, file, prev, drag, ref, onFile, onDragIn, onDragOut }) => (
              <div key={label}>
                <label className="text-xs font-semibold uppercase tracking-wide text-bark-500 block mb-2">{label}</label>
                <div
                  className={`drop-zone ${drag ? 'active' : ''} ${file ? 'filled' : ''}`}
                  onClick={() => ref.current?.click()}
                  onDragOver={e => { e.preventDefault(); onDragIn() }}
                  onDragLeave={onDragOut}
                  onDrop={e => { e.preventDefault(); onDragOut(); const f = e.dataTransfer.files[0]; if (f?.type.startsWith('image/')) onFile(f) }}
                >
                  {prev ? (
                    <div className="flex items-center gap-3">
                      <img src={prev} className="w-14 h-14 rounded-lg object-cover flex-shrink-0" alt="" />
                      <div className="text-left">
                        <p className="text-sm font-semibold text-bark-700 truncate max-w-[180px]">{file?.name}</p>
                        <p className="text-xs text-brand-500 mt-0.5">Click to change</p>
                      </div>
                    </div>
                  ) : (
                    <>
                      <ImageIcon className="w-8 h-8 text-bark-300 mx-auto mb-2" strokeWidth={1} />
                      <p className="text-sm text-bark-500"><strong className="text-bark-700">Click to upload</strong> or drag & drop</p>
                      <p className="text-xs text-bark-400 mt-1">{label} · {hint}</p>
                    </>
                  )}
                </div>
                <input ref={ref} type="file" accept="image/*" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f) }} />
              </div>
            ))}
          </div>

          {/* Settings card */}
          <div className="card p-6 space-y-5">
            <h2 className="font-display text-xl font-semibold italic text-bark-900">Grid Settings</h2>

            <div className="space-y-4">
              {[
                { label: 'Columns', options: [2,3,4], value: cols, set: setCols },
                { label: 'Rows',    options: [1,2,3,4], value: rows, set: setRows },
              ].map(({ label, options, value, set }) => (
                <div key={label}>
                  <label className="text-xs font-semibold uppercase tracking-wide text-bark-500 block mb-2">{label}</label>
                  <div className="flex gap-2">
                    {options.map(n => (
                      <button key={n} onClick={() => set(n)}
                        className={`flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-all ${value === n ? 'border-brand-400 bg-brand-50 text-brand-600' : 'border-bark-200 text-bark-500 hover:border-bark-300'}`}>
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              ))}

              <div className="bg-bark-50 rounded-xl p-4 border border-bark-100">
                <p className="text-xs text-bark-500 font-medium">
                  Output: <span className="text-bark-800 font-bold">{cols * rows} images</span> — front | back side by side
                </p>
              </div>
            </div>

            <button onClick={split} disabled={loading || !frontFile || !backFile} className="btn-primary w-full justify-center py-3 text-base">
              {loading
                ? <><span className="spinner spinner-white" /> Processing…</>
                : <><Scissors className="w-5 h-5" /> Split & Combine</>}
            </button>
          </div>
        </div>

        {/* Results */}
        {results.length > 0 && (
          <div className="animate-fade-up">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-display text-xl font-semibold italic text-bark-900">{results.length} images created</h2>
              <button onClick={() => downloadAll(results)} className="btn-outline gap-2">
                <Archive className="w-4 h-4" /> Download All
              </button>
            </div>
            <div className="grid grid-cols-3 gap-4">
              {results.map(img => (
                <div key={img.index} className="card overflow-hidden group">
                  <img src={img.dataUrl} alt={img.filename} className="w-full object-cover block" />
                  <div className="p-3 flex items-center justify-between">
                    <span className="text-xs text-bark-500 font-medium truncate">{img.filename}</span>
                    <button onClick={() => downloadOne(img)}
                      className="btn-ghost py-1 px-2 text-xs opacity-0 group-hover:opacity-100 transition-opacity">
                      <Download className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
