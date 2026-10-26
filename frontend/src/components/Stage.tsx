import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { BakeManifest, DefaultState, StageState } from '../types'
import { VISEME_COLORS, VISEME_LABELS } from '../lib/timeline'
import { formatTimecode } from '../lib/format'
import { swaySafetyScale, swayTransform } from '../lib/sway'
import {
  IconChevronRight,
  IconFit,
  IconImage,
  IconPause,
  IconPlay,
  IconSpinner,
  IconZoomIn,
  IconZoomOut,
} from './Icons'

interface StageProps {
  manifest: BakeManifest | null
  defaultState: DefaultState
  state: StageState
  time: number
  duration: number
  fps: number
  bpm: number | null
  sway: import('../types').SwayConfig
  audioStart: number
  playing: boolean
  canPlay: boolean
  onTogglePlay: () => void
  onSeek: (time: number) => void
  stale: boolean
  hiddenLayers: Set<string>
  loading: boolean
  loadingLabel: string
  onImportPsd: () => void
}

interface Size {
  width: number
  height: number
}

interface Point {
  x: number
  y: number
}

interface Drawable {
  key: string
  image: HTMLImageElement
  x: number
  y: number
  width: number
  height: number
  z: number
}

const CHECKER_LIGHT = '#292929'
const CHECKER_DARK = '#242424'

function pickPatchUrl(manifest: BakeManifest, channel: string, value: string): string | null {
  const exact = manifest.patches[`${channel}.${value}`]
  if (exact) return exact.url
  return null
}

export function Stage({
  manifest,
  defaultState,
  state,
  time,
  duration,
  fps,
  bpm,
  sway,
  audioStart,
  playing,
  canPlay,
  onTogglePlay,
  onSeek,
  stale,
  hiddenLayers,
  loading,
  loadingLabel,
  onImportPsd,
}: StageProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const imagesRef = useRef<Map<string, HTMLImageElement>>(new Map())
  const checkerPatternRef = useRef<CanvasPattern | null>(null)
  const [size, setSize] = useState<Size>({ width: 0, height: 0 })
  const [imagesVersion, setImagesVersion] = useState(0)
  const [imagesReady, setImagesReady] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 })
  const [panning, setPanning] = useState(false)
  const panDragRef = useRef<{ x: number; y: number; pan: Point } | null>(null)
  const [checker, setChecker] = useState(true)
  // Last painted visual state, so a paused/unchanged frame is not repainted.
  const lastDrawRef = useRef('')
  // base + drop shadow pre-rendered once per size, instead of blurring every frame.
  const spriteRef = useRef<{ key: string; canvas: HTMLCanvasElement; pad: number } | null>(null)

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
    for (const [id, layer] of Object.entries(manifest.layers ?? {})) entries.push([`layer:${id}`, layer.url])
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

  const clampPan = useCallback((next: Point, nextZoom = zoom): Point => {
    if (!manifest || size.width <= 0 || size.height <= 0) return { x: 0, y: 0 }
    const fitScale = Math.min((size.width - 64) / manifest.width, (size.height - 64) / manifest.height)
    const scale = Math.max(0.02, fitScale * nextZoom * swaySafetyScale(sway))
    const imageWidth = manifest.width * scale
    const imageHeight = manifest.height * scale
    const margin = 32
    return {
      x: Math.min(size.width - margin - (size.width - imageWidth) / 2, Math.max(margin - (size.width + imageWidth) / 2, next.x)),
      y: Math.min(size.height - margin - (size.height - imageHeight) / 2, Math.max(margin - (size.height + imageHeight) / 2, next.y)),
    }
  }, [manifest, size, sway, zoom])

  const zoomTo = useCallback((next: number, anchor?: Point) => {
    const value = Math.min(4, Math.max(0.15, Math.round(next * 100) / 100))
    setPan((current) => {
      if (!anchor || zoom <= 0) return clampPan(current, value)
      const center = { x: size.width / 2, y: size.height / 2 }
      const ratio = value / zoom
      return clampPan({
        x: anchor.x - center.x - (anchor.x - center.x - current.x) * ratio,
        y: anchor.y - center.y - (anchor.y - center.y - current.y) * ratio,
      }, value)
    })
    setZoom(value)
  }, [clampPan, size, zoom])

  const resetView = useCallback(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [])

  const wheel = useCallback((event: WheelEvent) => {
    if (!manifest) return
    event.preventDefault()
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const factor = Math.exp(-event.deltaY * 0.0015)
    zoomTo(zoom * factor, { x: event.clientX - rect.left, y: event.clientY - rect.top })
  }, [manifest, zoom, zoomTo])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('wheel', wheel, { passive: false })
    return () => canvas.removeEventListener('wheel', wheel)
  }, [wheel])

  const pointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!manifest || event.button !== 0) return
    panDragRef.current = { x: event.clientX, y: event.clientY, pan }
    setPanning(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const pointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const drag = panDragRef.current
    if (!drag) return
    setPan(clampPan({ x: drag.pan.x + event.clientX - drag.x, y: drag.pan.y + event.clientY - drag.y }))
  }

  const pointerEnd = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    panDragRef.current = null
    setPanning(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  // Everything that gets drawn on top of the base image: semantic patches plus
  // the static (non-semantic) layers, already merged and z-sorted. Rebuilding
  // this list on every animation frame was pure garbage churn.
  const drawables = useMemo<Drawable[]>(() => {
    if (!manifest || !imagesReady) return []
    const images = imagesRef.current
    const channelValue: Record<string, string> = {
      ...state.channels,
      eyes: state.blink ? 'blink' : state.channels.eyes,
      brow: state.brow,
      cheek: state.cheek,
    }
    const fallback: Record<string, string | undefined> = {
      ...(manifest.defaultState ?? {}),
      // Live profile defaults win for the core channels, so the preview keeps
      // following the mapping panel while optional channels (sweat / eyeEffect)
      // use the baked default (usually "off"), exactly like the exporter.
      mouth: defaultState.mouth,
      eyes: defaultState.eyes,
      brow: defaultState.brow,
      cheek: defaultState.cheek,
    }

    const order = manifest.zorder.length > 0 ? manifest.zorder : ['cheek', 'mouth', 'eyes', 'brow']
    const items: Drawable[] = []
    order.forEach((channel, index) => {
      const wanted = channel === 'mouth' ? [state.mouthPose, state.viseme] : [channelValue[channel]]
      if (wanted[0] === 'off') return
      const values = [...wanted, fallback[channel]].filter((value): value is string => Boolean(value))
      const patchKey = values.map((value) => `${channel}.${value}`).find((key) => manifest.patches[key])
      if (!patchKey) return
      const patch = manifest.patches[patchKey]
      const image = images.get(patchKey)
      if (!patch || !image || image.naturalWidth === 0) return
      items.push({
        key: patchKey,
        image,
        x: patch.offset[0],
        y: patch.offset[1],
        width: patch.width || image.naturalWidth,
        height: patch.height || image.naturalHeight,
        z: patch.z ?? 1_000_000 + index,
      })
    })

    for (const [id, layer] of Object.entries(manifest.layers ?? {})) {
      if (hiddenLayers.has(id)) continue
      const image = images.get(`layer:${id}`)
      if (!image || image.naturalWidth === 0) continue
      items.push({
        key: `layer:${id}`,
        image,
        x: layer.offset[0],
        y: layer.offset[1],
        width: layer.width || image.naturalWidth,
        height: layer.height || image.naturalHeight,
        z: layer.z,
      })
    }
    items.sort((a, b) => a.z - b.z)
    return items
  }, [defaultState, hiddenLayers, imagesReady, manifest, state])

  const hiddenKey = useMemo(() => Array.from(hiddenLayers).sort().join(','), [hiddenLayers])
  const channelsKey = useMemo(() => JSON.stringify(state.channels), [state.channels])

  // base + drop shadow pre-rendered once per size; a 32px shadow blur on every
  // frame was the most expensive single call in the preview path.
  const baseSprite = useCallback(
    (base: HTMLImageElement, width: number, height: number, dpr: number) => {
      const key = `${manifest?.bakedAt ?? ''}|${width.toFixed(1)}|${height.toFixed(1)}|${dpr}`
      const cached = spriteRef.current
      if (cached && cached.key === key) return cached
      const pad = 40
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.ceil((width + pad * 2) * dpr))
      canvas.height = Math.max(1, Math.ceil((height + pad * 2) * dpr))
      const spriteCtx = canvas.getContext('2d')
      if (!spriteCtx) return null
      spriteCtx.scale(dpr, dpr)
      spriteCtx.shadowColor = 'rgba(0, 0, 0, 0.55)'
      spriteCtx.shadowBlur = 32
      spriteCtx.shadowOffsetY = 12
      spriteCtx.drawImage(base, pad, pad, width, height)
      spriteRef.current = { key, canvas, pad }
      return spriteRef.current
    },
    [manifest?.bakedAt],
  )

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || size.width === 0) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const width = size.width
    const height = size.height
    const motion = swayTransform(time, bpm, sway, audioStart)

    // Nothing visible changed (paused, sway off, ...): skip the repaint.
    const signature = [
      manifest?.bakedAt ?? '',
      imagesVersion,
      zoom,
      Math.round(pan.x * 4) / 4,
      Math.round(pan.y * 4) / 4,
      width,
      height,
      checker ? 1 : 0,
      state.viseme,
      state.mouthPose ?? '',
      state.blink ? 1 : 0,
      state.brow,
      state.cheek,
      channelsKey,
      hiddenKey,
      motion.angle.toFixed(6),
      motion.scaleY.toFixed(6),
    ].join('|')
    if (signature === lastDrawRef.current) return
    lastDrawRef.current = signature

    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)

    // backdrop
    ctx.fillStyle = '#181818'
    ctx.fillRect(0, 0, width, height)

    if (!manifest || !imagesReady) return
    const base = imagesRef.current.get('__base__')
    if (!base || base.naturalWidth === 0) return

    const fitScale = Math.min((width - 64) / manifest.width, (height - 64) / manifest.height)
    const scale = Math.max(0.02, fitScale * zoom * swaySafetyScale(sway))
    const offsetX = (width - manifest.width * scale) / 2 + pan.x
    const offsetY = (height - manifest.height * scale) / 2 + pan.y
    const imageWidth = manifest.width * scale
    const imageHeight = manifest.height * scale

    // checkerboard only behind the artboard
    if (checker) {
      if (!checkerPatternRef.current) {
        const tile = document.createElement('canvas')
        tile.width = 20
        tile.height = 20
        const tileCtx = tile.getContext('2d')
        if (tileCtx) {
          tileCtx.fillStyle = CHECKER_DARK
          tileCtx.fillRect(0, 0, 20, 20)
          tileCtx.fillStyle = CHECKER_LIGHT
          tileCtx.fillRect(0, 0, 10, 10)
          tileCtx.fillRect(10, 10, 10, 10)
          checkerPatternRef.current = ctx.createPattern(tile, 'repeat')
        }
      }
      if (checkerPatternRef.current) {
        ctx.fillStyle = checkerPatternRef.current
        ctx.fillRect(offsetX, offsetY, imageWidth, imageHeight)
      }
    } else {
      ctx.fillStyle = '#242424'
      ctx.fillRect(offsetX, offsetY, imageWidth, imageHeight)
    }
    ctx.strokeStyle = '#3d3d3d'
    ctx.lineWidth = 1
    ctx.strokeRect(offsetX + 0.5, offsetY + 0.5, imageWidth - 1, imageHeight - 1)

    const pivotX = offsetX + imageWidth / 2
    const pivotY = offsetY + imageHeight

    ctx.save()
    ctx.translate(pivotX, pivotY)
    ctx.rotate(motion.angle)
    ctx.scale(1, motion.scaleY)
    ctx.translate(-pivotX, -pivotY)

    // subtle drop shadow so the cut-out reads against the checkerboard —
    // blurred once into an offscreen sprite instead of 60×/s.
    const sprite = baseSprite(base, imageWidth, imageHeight, dpr)
    if (sprite) {
      ctx.drawImage(
        sprite.canvas,
        offsetX - sprite.pad,
        offsetY - sprite.pad,
        sprite.canvas.width / dpr,
        sprite.canvas.height / dpr,
      )
    } else {
      ctx.drawImage(base, offsetX, offsetY, imageWidth, imageHeight)
    }

    for (const item of drawables) {
      ctx.drawImage(
        item.image,
        offsetX + item.x * scale,
        offsetY + item.y * scale,
        item.width * scale,
        item.height * scale,
      )
    }
    ctx.restore()

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
  }, [audioStart, baseSprite, bpm, channelsKey, checker, drawables, hiddenKey, imagesVersion, manifest, pan, size, state, sway, time, zoom])

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
    <div className="stage">
      <div className="stage-head">
        <span className="stage-title">预览</span>
        {stale ? (
          <span className="stage-stale" title="图层可见性或映射已修改，重新烘焙后预览才会更新">
            贴图待更新
          </span>
        ) : null}
        <div className="stage-toolbar">
          <button className="icon-btn" title="缩小" onClick={() => zoomTo(zoom - 0.1)}>
            <IconZoomOut />
          </button>
          <span className="zoom-label">{Math.round(zoom * 100)}%</span>
          <button className="icon-btn" title="放大" onClick={() => zoomTo(zoom + 0.1)}>
            <IconZoomIn />
          </button>
          <button className="icon-btn" title="适配窗口并复位平移" onClick={resetView}>
            <IconFit />
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
      </div>

      <div className="stage-view" ref={containerRef}>
        <canvas
          ref={canvasRef}
          className={`stage-canvas ${panning ? 'panning' : ''}`}
          style={{ width: '100%', height: '100%' }}
          aria-label="预览舞台：拖拽平移，滚轮缩放，双击复位"
          data-pan-x={Math.round(pan.x)}
          data-pan-y={Math.round(pan.y)}
          onPointerDown={pointerDown}
          onPointerMove={pointerMove}
          onPointerUp={pointerEnd}
          onPointerCancel={pointerEnd}
          onDoubleClick={resetView}
        />

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

      <div className="stage-foot">
        <button className="icon-btn" title="上一帧" onClick={() => onSeek(Math.max(0, time - 1 / fps))}>
          <IconChevronRight className="flip-x" />
        </button>
        <button
          className="play-btn"
          onClick={onTogglePlay}
          disabled={!canPlay}
          title={playing ? '暂停（空格）' : '播放（空格）'}
        >
          {playing ? <IconPause size={15} /> : <IconPlay size={15} />}
        </button>
        <button
          className="icon-btn"
          title="下一帧"
          onClick={() => onSeek(Math.min(duration, time + 1 / fps))}
        >
          <IconChevronRight />
        </button>
        <span className="stage-time">
          <span className="transport-tc">{formatTimecode(time, true, fps)}</span>
          <span className="transport-duration">/ {formatTimecode(duration, false)}</span>
        </span>
      </div>
    </div>
  )
}
