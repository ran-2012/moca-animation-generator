import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { BakeManifest, DefaultState, StageState } from '../types'
import { VISEME_COLORS, VISEME_LABELS } from '../lib/timeline'
import { formatTimecode } from '../lib/format'
import { IconFit, IconImage, IconSpinner, IconZoomIn, IconZoomOut } from './Icons'

interface StageProps {
  manifest: BakeManifest | null
  defaultState: DefaultState
  state: StageState
  time: number
  duration: number
  fps: number
  loading: boolean
  loadingLabel: string
  onImportPsd: () => void
}

interface Size {
  width: number
  height: number
}

const CHECKER_LIGHT = '#1b202b'
const CHECKER_DARK = '#141821'

function pickPatchUrl(manifest: BakeManifest, channel: string, value: string): string | null {
  const exact = manifest.patches[`${channel}.${value}`]
  if (exact) return exact.url
  return null
}

export function Stage({ manifest, defaultState, state, time, duration, fps, loading, loadingLabel, onImportPsd }: StageProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const imagesRef = useRef<Map<string, HTMLImageElement>>(new Map())
  const checkerPatternRef = useRef<CanvasPattern | null>(null)
  const [size, setSize] = useState<Size>({ width: 0, height: 0 })
  const [imagesVersion, setImagesVersion] = useState(0)
  const [imagesReady, setImagesReady] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [checker, setChecker] = useState(true)

  // keep the canvas backing store in sync with the layout box
  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (!rect) return
      setSize({ width: Math.max(1, Math.floor(rect.width)), height: Math.max(1, Math.floor(rect.height)) })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // preload base + patch images whenever a new manifest arrives
  useEffect(() => {
    imagesRef.current = new Map()
    setImagesReady(false)
    setImagesVersion(0)
    if (!manifest) return
    const entries: Array<[string, string]> = [['__base__', manifest.base.url]]
    for (const [key, patch] of Object.entries(manifest.patches)) entries.push([key, patch.url])
    const map = new Map<string, HTMLImageElement>()
    let pending = entries.length
    let cancelled = false
    const settle = (): void => {
      pending -= 1
      if (pending > 0 || cancelled) return
      imagesRef.current = map
      setImagesReady(true)
      setImagesVersion((version) => version + 1)
    }
    for (const [key, url] of entries) {
      if (!url) {
        settle()
        continue
      }
      const image = new Image()
      image.decoding = 'async'
      image.onload = settle
      image.onerror = settle
      image.src = url
      map.set(key, image)
    }
    return () => {
      cancelled = true
    }
  }, [manifest])

  const zoomTo = useCallback((next: number) => {
    setZoom(Math.min(4, Math.max(0.15, Math.round(next * 100) / 100)))
  }, [])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || size.width === 0) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const width = size.width
    const height = size.height
    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)

    // backdrop
    if (checker) {
      if (!checkerPatternRef.current) {
        const tile = document.createElement('canvas')
        tile.width = 32
        tile.height = 32
        const tileCtx = tile.getContext('2d')
        if (tileCtx) {
          tileCtx.fillStyle = CHECKER_DARK
          tileCtx.fillRect(0, 0, 32, 32)
          tileCtx.fillStyle = CHECKER_LIGHT
          tileCtx.fillRect(0, 0, 16, 16)
          tileCtx.fillRect(16, 16, 16, 16)
          checkerPatternRef.current = ctx.createPattern(tile, 'repeat')
        }
      }
      if (checkerPatternRef.current) {
        ctx.fillStyle = checkerPatternRef.current
        ctx.fillRect(0, 0, width, height)
      }
    } else {
      ctx.fillStyle = '#0e1118'
      ctx.fillRect(0, 0, width, height)
    }

    if (!manifest || !imagesReady) return
    const base = imagesRef.current.get('__base__')
    if (!base || base.naturalWidth === 0) return

    const fitScale = Math.min((width - 64) / manifest.width, (height - 64) / manifest.height)
    const scale = Math.max(0.02, fitScale * zoom)
    const offsetX = (width - manifest.width * scale) / 2
    const offsetY = (height - manifest.height * scale) / 2

    // subtle drop shadow so the cut-out reads against the checkerboard
    ctx.save()
    ctx.shadowColor = 'rgba(0, 0, 0, 0.55)'
    ctx.shadowBlur = 32
    ctx.shadowOffsetY = 12
    ctx.drawImage(base, offsetX, offsetY, manifest.width * scale, manifest.height * scale)
    ctx.restore()

    const channelValue: Record<string, string> = {
      mouth: state.viseme,
      eyes: state.blink ? 'blink' : 'open',
      brow: state.brow,
      cheek: state.cheek,
    }
    const fallback: Record<string, string> = {
      mouth: defaultState.mouth,
      eyes: defaultState.eyes,
      brow: defaultState.brow,
      cheek: defaultState.cheek,
    }

    const order = manifest.zorder.length > 0 ? manifest.zorder : ['cheek', 'mouth', 'eyes', 'brow']
    for (const channel of order) {
      const value = channelValue[channel] ?? fallback[channel] ?? 'normal'
      let patchKey = `${channel}.${value}`
      let patch = manifest.patches[patchKey]
      if (!patch) {
        patchKey = `${channel}.${fallback[channel] ?? ''}`
        patch = manifest.patches[patchKey]
      }
      if (!patch) continue
      const image = imagesRef.current.get(patchKey)
      if (!image || image.naturalWidth === 0) continue
      const patchWidth = patch.width || image.naturalWidth
      const patchHeight = patch.height || image.naturalHeight
      ctx.drawImage(
        image,
        offsetX + patch.offset[0] * scale,
        offsetY + patch.offset[1] * scale,
        patchWidth * scale,
        patchHeight * scale,
      )
    }

    // frame corners for a "studio monitor" feel
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)'
    ctx.lineWidth = 1
    const inset = 14
    const corner = 18
    for (const [cx, cy, dx, dy] of [
      [inset, inset, 1, 1],
      [width - inset, inset, -1, 1],
      [inset, height - inset, 1, -1],
      [width - inset, height - inset, -1, -1],
    ] as Array<[number, number, number, number]>) {
      ctx.beginPath()
      ctx.moveTo(cx + dx * corner, cy)
      ctx.lineTo(cx, cy)
      ctx.lineTo(cx, cy + dy * corner)
      ctx.stroke()
    }
  }, [checker, defaultState, imagesReady, manifest, size, state, zoom])

  useEffect(() => {
    draw()
  }, [draw, imagesVersion, time])

  const patchCount = manifest ? Object.keys(manifest.patches).length : 0
  const hasCanvas = Boolean(manifest)

  const stageStateChips = useMemo(
    () => [
      { key: 'VIS', label: VISEME_LABELS[state.viseme] ?? state.viseme, color: VISEME_COLORS[state.viseme] },
      { key: 'BLINK', label: state.blink ? '闭眼' : '睁眼', color: state.blink ? '#f59e0b' : '#4b5568' },
      { key: 'BROW', label: state.brow, color: '#7c8ba8' },
      { key: 'CHEEK', label: state.cheek, color: '#c084fc' },
    ],
    [state],
  )

  return (
    <div className="stage" ref={containerRef}>
      <canvas ref={canvasRef} className="stage-canvas" style={{ width: '100%', height: '100%' }} />

      <div className="stage-toolbar">
        <button className="icon-btn" title="适配窗口" onClick={() => zoomTo(1)}>
          <IconFit />
        </button>
        <button className="icon-btn" title="缩小" onClick={() => zoomTo(zoom - 0.1)}>
          <IconZoomOut />
        </button>
        <span className="zoom-label">{Math.round(zoom * 100)}%</span>
        <button className="icon-btn" title="放大" onClick={() => zoomTo(zoom + 0.1)}>
          <IconZoomIn />
        </button>
        <span className="toolbar-sep" />
        <button
          className={`chip-toggle ${checker ? 'active' : ''}`}
          title="棋盘格透明背景"
          onClick={() => setChecker((value) => !value)}
        >
          棋盘格
        </button>
      </div>

      {!hasCanvas && !loading ? (
        <div className="stage-empty">
          <div className="stage-empty-inner">
            <div className="stage-empty-icon">
              <IconImage size={30} />
            </div>
            <h2>舞台等待素材</h2>
            <p>导入 PSD 后自动识别语义图层，烘焙一次即可在这里实时预览口型与眨眼。</p>
            <button className="btn primary" onClick={onImportPsd}>
              导入 PSD
            </button>
            <ol className="stage-steps">
              <li>导入 moca.psd</li>
              <li>自动识别 → 检查映射槽位 → 保存</li>
              <li>烘焙（10–30s，仅首次）→ 舞台出现立绘</li>
            </ol>
          </div>
        </div>
      ) : null}

      {manifest && !imagesReady && !loading ? (
        <div className="stage-loading small">
          <IconSpinner size={18} />
          <span>加载烘焙贴图…</span>
        </div>
      ) : null}

      {loading ? (
        <div className="stage-loading">
          <div className="stage-loading-card">
            <IconSpinner size={26} />
            <div>
              <strong>{loadingLabel}</strong>
              <p>正在合成 base + patch 贴图，首次约 10–30 秒…</p>
            </div>
          </div>
        </div>
      ) : null}

      {manifest ? (
        <div className="stage-hud">
          <div className="stage-hud-left">
            <span className="timecode">{formatTimecode(time, true, fps)}</span>
            <span className="hud-muted">/ {formatTimecode(duration, false)}</span>
          </div>
          <div className="stage-hud-right">
            {stageStateChips.map((chip) => (
              <span key={chip.key} className="state-chip" title={chip.key}>
                <i style={{ background: chip.color }} />
                {chip.key} {chip.label}
              </span>
            ))}
            <span className="hud-muted">
              {manifest.width}×{manifest.height} · {patchCount} patches
            </span>
          </div>
        </div>
      ) : null}
    </div>
  )
}
