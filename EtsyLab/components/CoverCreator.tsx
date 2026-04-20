'use client'

import { useEffect, useRef, useState } from 'react'
import { useToast } from '@/lib/context'
import { ImageIcon, Download, RotateCcw, Shirt } from 'lucide-react'

const CANVAS_W = 820
const CANVAS_H = 1230

export default function CoverCreator() {
  const canvasRef  = useRef<HTMLCanvasElement>(null)
  const tplRef     = useRef<HTMLInputElement>(null)
  const modelRef   = useRef<HTMLInputElement>(null)
  const tplImgRef  = useRef<HTMLImageElement | null>(null)
  const modelImgRef = useRef<HTMLImageElement | null>(null)

  const [title,    setTitle]    = useState('Slip Dress')
  const [tplName,  setTplName]  = useState('')
  const [modelName, setModelName] = useState('')
  const [tplDrag,  setTplDrag]  = useState(false)
  const [modelDrag, setModelDrag] = useState(false)
  const [offsetX,  setOffsetX]  = useState(0)
  const [offsetY,  setOffsetY]  = useState(0)
  const [zoom,     setZoom]     = useState(100)
  const { showToast } = useToast()

  // Load template from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('etsylab_template')
    if (saved) loadImageFromDataURL(saved, tplImgRef, () => setTplName('Saved template'))
  }, [])

  // Re-render whenever state changes
  useEffect(() => { render() }, [title, offsetX, offsetY, zoom])

  function loadImageFromDataURL(dataURL: string, ref: React.MutableRefObject<HTMLImageElement | null>, onLoad?: () => void) {
    const img = new Image()
    img.onload = () => { ref.current = img; render(); onLoad?.() }
    img.src = dataURL
  }

  function loadFile(file: File, ref: React.MutableRefObject<HTMLImageElement | null>, type: 'template' | 'model') {
    const reader = new FileReader()
    reader.onload = e => {
      const dataURL = e.target?.result as string
      if (type === 'template') {
        localStorage.setItem('etsylab_template', dataURL)
        setTplName(file.name)
      } else {
        setModelName(file.name)
      }
      loadImageFromDataURL(dataURL, ref)
    }
    reader.readAsDataURL(file)
  }

  function render() {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H)
    ctx.fillStyle = '#F8F6F0'
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H)

    const tpl = tplImgRef.current
    const mdl = modelImgRef.current

    if (!tpl) {
      ctx.fillStyle = '#EDE3D0'
      ctx.fillRect(0, 0, CANVAS_W, CANVAS_H)
      ctx.fillStyle = '#B09878'
      ctx.font = '20px system-ui'
      ctx.textAlign = 'center'
      ctx.fillText('Upload base template to preview', CANVAS_W / 2, CANVAS_H / 2)
      return
    }

    // Green area bounds (matching original: left:2.7%, top:22.2%, width:60.5%, height:75%)
    const GX = CANVAS_W * 0.027
    const GY = CANVAS_H * 0.222
    const GW = CANVAS_W * 0.605
    const GH = CANVAS_H * 0.75

    // Draw model photo into green area with clip
    if (mdl) {
      ctx.save()
      ctx.beginPath()
      ctx.rect(GX, GY, GW, GH)
      ctx.clip()

      const scale  = (zoom / 100)
      const imgW   = GW * scale
      const imgH   = (mdl.naturalHeight / mdl.naturalWidth) * imgW
      const drawX  = GX + (GW - imgW) / 2 + offsetX
      const drawY  = GY + offsetY
      ctx.drawImage(mdl, drawX, drawY, imgW, imgH)
      ctx.restore()
    }

    // Draw template on top
    ctx.drawImage(tpl, 0, 0, CANVAS_W, CANVAS_H)

    // Draw title text
    if (title.trim()) {
      const name = title.trim().toUpperCase()
      let   fontSize = 52
      ctx.font = `700 ${fontSize}px 'Cormorant Garamond', Georgia, serif`
      while (ctx.measureText(name).width > CANVAS_W * 0.55 && fontSize > 24) {
        fontSize -= 2
        ctx.font = `700 ${fontSize}px 'Cormorant Garamond', Georgia, serif`
      }
      ctx.fillStyle = '#1C1510'
      ctx.textAlign = 'left'
      ctx.fillText(name, CANVAS_W * 0.67, CANVAS_H * 0.18)
    }
  }

  function download() {
    const canvas = canvasRef.current
    if (!canvas) return
    const link    = document.createElement('a')
    link.download = `${title.trim() || 'cover'}.png`
    link.href     = canvas.toDataURL('image/png')
    link.click()
    showToast('Cover downloaded!', 'success')
  }

  function reset() {
    setOffsetX(0); setOffsetY(0); setZoom(100)
  }

  return (
    <div>
      <div className="section-header">
        <h1 className="font-display text-3xl font-semibold italic text-bark-900">Cover Creator</h1>
        <p className="text-bark-400 text-sm mt-0.5">Upload your template once — swap model photo & title per pattern</p>
      </div>

      <div className="p-8">
        <div className="grid gap-5" style={{ gridTemplateColumns: '280px 1fr' }}>

          {/* Left Panel */}
          <div className="space-y-4">

            {/* Template upload */}
            <div className="card p-5 space-y-3">
              <div>
                <p className="text-xs font-bold uppercase tracking-widest text-brand-500 mb-0.5">Base Template</p>
                <p className="text-[10px] text-bark-400">Upload once — saved automatically</p>
              </div>
              <div
                className={`drop-zone py-5 ${tplDrag ? 'active' : ''} ${tplName ? 'filled' : ''}`}
                onClick={() => tplRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setTplDrag(true) }}
                onDragLeave={() => setTplDrag(false)}
                onDrop={e => {
                  e.preventDefault(); setTplDrag(false)
                  const f = e.dataTransfer.files[0]
                  if (f?.type.startsWith('image/')) loadFile(f, tplImgRef, 'template')
                }}
              >
                {tplName ? (
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 bg-emerald-100 rounded-lg flex items-center justify-center">
                      <ImageIcon className="w-4 h-4 text-emerald-600" strokeWidth={1.5} />
                    </div>
                    <div className="text-left">
                      <p className="text-xs font-semibold text-bark-700 truncate max-w-[160px]">{tplName}</p>
                      <p className="text-[10px] text-brand-400 mt-0.5">Click to change</p>
                    </div>
                  </div>
                ) : (
                  <>
                    <ImageIcon className="w-7 h-7 text-bark-300 mx-auto mb-2" strokeWidth={1} />
                    <p className="text-xs text-bark-500 text-center">Drop template image here</p>
                  </>
                )}
              </div>
              <input ref={tplRef} type="file" accept="image/*" className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) loadFile(f, tplImgRef, 'template') }} />
            </div>

            {/* Title input */}
            <div className="card p-5">
              <label className="text-[10px] font-bold uppercase tracking-widest text-brand-500 block mb-3">① Dress Name</label>
              <input
                className="input text-lg font-bold font-display"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="e.g. Summer Dress"
              />
            </div>

            {/* Model photo */}
            <div className="card p-5 space-y-3">
              <label className="text-[10px] font-bold uppercase tracking-widest text-brand-500 block">② Model Photo</label>
              <div
                className={`drop-zone py-5 ${modelDrag ? 'active' : ''} ${modelName ? 'filled' : ''}`}
                onClick={() => modelRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setModelDrag(true) }}
                onDragLeave={() => setModelDrag(false)}
                onDrop={e => {
                  e.preventDefault(); setModelDrag(false)
                  const f = e.dataTransfer.files[0]
                  if (f?.type.startsWith('image/')) loadFile(f, modelImgRef, 'model')
                }}
              >
                {modelName ? (
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 bg-brand-100 rounded-lg flex items-center justify-center">
                      <Shirt className="w-4 h-4 text-brand-600" strokeWidth={1.5} />
                    </div>
                    <div className="text-left">
                      <p className="text-xs font-semibold text-bark-700 truncate max-w-[160px]">{modelName}</p>
                      <p className="text-[10px] text-brand-400 mt-0.5">Click to change</p>
                    </div>
                  </div>
                ) : (
                  <>
                    <Shirt className="w-7 h-7 text-bark-300 mx-auto mb-2" strokeWidth={1} />
                    <p className="text-xs text-bark-500 text-center">Drop model photo here</p>
                  </>
                )}
              </div>
              <input ref={modelRef} type="file" accept="image/*" className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) loadFile(f, modelImgRef, 'model') }} />
            </div>

            {/* Download */}
            <button onClick={download} className="btn-primary w-full justify-center py-3.5 text-base">
              <Download className="w-5 h-5" /> Download Cover PNG
            </button>

            {/* Position controls */}
            <details className="card p-4">
              <summary className="cursor-pointer text-xs font-semibold text-bark-500 list-none flex items-center justify-between">
                Adjust model position
                <span className="text-bark-300">▾</span>
              </summary>
              <div className="mt-4 space-y-3">
                {[
                  { label: 'X Offset', value: offsetX, onChange: setOffsetX, min: -200, max: 200 },
                  { label: 'Y Offset', value: offsetY, onChange: setOffsetY, min: -300, max: 300 },
                  { label: 'Zoom %',   value: zoom,    onChange: setZoom,    min: 60,   max: 200 },
                ].map(({ label, value, onChange, min, max }) => (
                  <div key={label}>
                    <div className="flex justify-between text-[10px] text-bark-400 font-medium mb-1">
                      <span>{label}</span>
                      <span className="text-bark-600 font-bold">{value}{label.includes('Zoom') ? '%' : ''}</span>
                    </div>
                    <input type="range" min={min} max={max} value={value}
                      onChange={e => onChange(Number(e.target.value))}
                      className="w-full accent-brand-500" />
                  </div>
                ))}
                <button onClick={reset} className="btn-ghost w-full justify-center text-xs">
                  <RotateCcw className="w-3.5 h-3.5" /> Reset position
                </button>
              </div>
            </details>
          </div>

          {/* Canvas */}
          <div className="card p-5 sticky top-6 self-start">
            <p className="text-[10px] font-bold uppercase tracking-widest text-bark-400 text-center mb-3">
              Live Preview — 820 × 1230 px
            </p>
            <div
              className={`relative rounded-xl overflow-hidden shadow-warm-lg border-2 transition-all ${modelDrag ? 'border-brand-400 border-dashed' : 'border-bark-100'}`}
              onDragOver={e => { e.preventDefault(); setModelDrag(true) }}
              onDragLeave={() => setModelDrag(false)}
              onDrop={e => {
                e.preventDefault(); setModelDrag(false)
                const f = e.dataTransfer.files[0]
                if (f?.type.startsWith('image/')) loadFile(f, modelImgRef, 'model')
              }}
            >
              <canvas
                ref={canvasRef}
                width={CANVAS_W}
                height={CANVAS_H}
                className="w-full block"
              />
              {modelDrag && (
                <div className="absolute inset-0 bg-brand-500/10 flex items-center justify-center">
                  <p className="text-brand-700 font-bold text-lg">Drop model photo here</p>
                </div>
              )}
            </div>
            <p className="text-[10px] text-bark-400 text-center mt-3">
              You can also drag the model photo directly onto the canvas
            </p>
          </div>

        </div>
      </div>
    </div>
  )
}
