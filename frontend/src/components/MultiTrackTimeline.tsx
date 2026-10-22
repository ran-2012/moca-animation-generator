import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { Blink, SwayConfig, Timeline } from '../types'
import { clamp } from '../lib/format'
import { swayEvents } from '../lib/sway'
import { pickTickStep, VISEME_COLORS } from '../lib/timeline'
import { drawWaveform } from '../lib/waveform'

interface Props {
  timeline: Timeline | null
  blinks: Blink[]
  peaks: number[] | null
  duration: number
  time: number
  bpm: number | null
  audioStart: number
  audioDuration: number
  sway: SwayConfig
  viewStartFrac: number
  viewSpanFrac: number
  onSeek: (time: number) => void
  onAudioStartChange: (value: number) => void
  onViewChange: (view: { start: number; span: number }) => void
}

type Density = 'compact' | 'normal' | 'expanded'
type TrackKind = 'blocks' | 'pitch' | 'events' | 'waveform'

interface TrackRow {
  id: string
  label: string
  group: 'source' | 'animation' | 'audio'
  kind: TrackKind
  items: unknown[]
}

const HEADER_W = 112
const RULER_H = 24
const GROUP_H = 25
const DENSITY_HEIGHT: Record<Density, number> = { compact: 28, normal: 40, expanded: 58 }
const GROUP_LABELS = { source: 'SVP 原始数据', animation: '生成动画', audio: '音频' }

function labelTime(value: number): string {
  const minute = Math.floor(value / 60)
  const second = Math.floor(value % 60)
  return minute > 0 ? `${minute}:${String(second).padStart(2, '0')}` : `${value.toFixed(value < 10 ? 1 : 0)}s`
}

function noteName(midi: number): string {
  const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
  return `${names[Math.round(midi) % 12]}${Math.floor(Math.round(midi) / 12) - 1}`
}

export function MultiTrackTimeline(props: Props) {
  const {
    timeline, blinks, peaks, duration, time, bpm, audioStart, audioDuration, sway,
    viewStartFrac, viewSpanFrac, onSeek, onAudioStartChange, onViewChange,
  } = props
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const rulerRef = useRef<HTMLCanvasElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const dragRef = useRef<{ kind: 'seek' | 'audio'; x: number; audioStart: number } | null>(null)
  const [width, setWidth] = useState(1)
  const [density, setDensity] = useState<Density>(() => (localStorage.getItem('mocadiff.timeline.density') as Density) || 'normal')
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem('mocadiff.timeline.collapsed') || '[]') as string[]) }
    catch { return new Set() }
  })

  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(1, Math.floor(entry.contentRect.width))))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    localStorage.setItem('mocadiff.timeline.density', density)
    localStorage.setItem('mocadiff.timeline.collapsed', JSON.stringify([...collapsed]))
  }, [collapsed, density])

  const rows = useMemo<TrackRow[]>(() => {
    const source = timeline?.sourceTracks
    const tracks = timeline?.tracks ?? {}
    return [
      { id: 'notes', label: '音符', group: 'source', kind: 'blocks', items: source?.notes ?? [] },
      { id: 'phonemes', label: '音素', group: 'source', kind: 'blocks', items: source?.phonemes ?? [] },
      { id: 'pitch', label: '音高', group: 'source', kind: 'pitch', items: source?.pitch ?? [] },
      { id: 'mouth', label: '口型', group: 'animation', kind: 'blocks', items: tracks.mouth ?? [] },
      { id: 'blink', label: '眨眼', group: 'animation', kind: 'events', items: tracks.blink ?? blinks },
      { id: 'eyes', label: '眼睛', group: 'animation', kind: 'events', items: tracks.eyes ?? [] },
      { id: 'brow', label: '眉毛', group: 'animation', kind: 'events', items: tracks.brow ?? [] },
      { id: 'cheek', label: '脸颊', group: 'animation', kind: 'events', items: tracks.cheek ?? [] },
      { id: 'sweat', label: '汗', group: 'animation', kind: 'events', items: tracks.sweat ?? [] },
      { id: 'eyeEffect', label: '眼部效果', group: 'animation', kind: 'events', items: tracks.eyeEffect ?? [] },
      { id: 'sway', label: '摇摆', group: 'animation', kind: 'events', items: swayEvents(duration, bpm, sway, audioStart) },
      { id: 'waveform', label: '波形', group: 'audio', kind: 'waveform', items: [] },
    ]
  }, [audioStart, blinks, bpm, duration, sway, timeline])

  const layout = useMemo(() => {
    const rowHeight = DENSITY_HEIGHT[density]
    const visible: Array<TrackRow & { y: number; height: number }> = []
    const groups: Array<{ id: string; y: number }> = []
    let y = 0
    for (const group of ['source', 'animation', 'audio'] as const) {
      groups.push({ id: group, y })
      y += GROUP_H
      if (collapsed.has(group)) continue
      for (const row of rows.filter((candidate) => candidate.group === group)) {
        if (row.items.length === 0 && !['mouth', 'blink', 'sway', 'waveform'].includes(row.id)) continue
        const height = row.kind === 'pitch' || row.kind === 'waveform' ? Math.round(rowHeight * 1.6) : rowHeight
        visible.push({ ...row, y, height })
        y += height
      }
    }
    return { rows: visible, groups, height: Math.max(y, 120) }
  }, [collapsed, density, rows])

  const view = useMemo(() => {
    const total = Math.max(duration, 1)
    const start = clamp(viewStartFrac, 0, 1) * total
    const span = clamp(viewSpanFrac, 0.002, 1) * total
    return { total, start, span, end: start + span, plotWidth: Math.max(1, width - HEADER_W - 8) }
  }, [duration, viewSpanFrac, viewStartFrac, width])

  const xAt = useCallback((value: number) => HEADER_W + ((value - view.start) / view.span) * view.plotWidth, [view])

  const drawRuler = useCallback(() => {
    const canvas = rulerRef.current
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = width * dpr
    canvas.height = RULER_H * dpr
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = '#252526'; ctx.fillRect(0, 0, width, RULER_H)
    ctx.fillStyle = '#999999'; ctx.font = '9px Consolas, monospace'; ctx.fillText('轨道', 10, 15)
    const step = pickTickStep(view.span)
    for (let tick = Math.ceil(view.start / step) * step; tick <= view.end; tick += step) {
      const x = xAt(tick)
      ctx.strokeStyle = '#4b4b4b'; ctx.beginPath(); ctx.moveTo(x, 16); ctx.lineTo(x, 24); ctx.stroke()
      ctx.fillStyle = '#999999'; ctx.fillText(labelTime(tick), x + 3, 4)
    }
    const playX = xAt(time)
    ctx.fillStyle = '#55a5db'; ctx.beginPath(); ctx.moveTo(playX - 5, 18); ctx.lineTo(playX + 5, 18); ctx.lineTo(playX, 24); ctx.fill()
  }, [time, view, width, xAt])

  const drawTracks = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = width * dpr
    canvas.height = layout.height * dpr
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = '#1e1e1e'; ctx.fillRect(0, 0, width, layout.height)

    for (const group of layout.groups) {
      ctx.fillStyle = '#2d2d2d'; ctx.fillRect(0, group.y, width, GROUP_H)
      ctx.fillStyle = '#cccccc'; ctx.font = '600 10px system-ui';
      ctx.fillText(`${collapsed.has(group.id) ? '▸' : '▾'} ${GROUP_LABELS[group.id as keyof typeof GROUP_LABELS]}`, 9, group.y + 17)
    }

    const pitchItems = timeline?.sourceTracks?.pitch ?? []
    const pitchValues = pitchItems.map((item) => item.midi)
    const pitchMin = Math.floor(Math.min(...pitchValues, 60) - 1)
    const pitchMax = Math.ceil(Math.max(...pitchValues, 72) + 1)

    for (const row of layout.rows) {
      ctx.fillStyle = '#252526'; ctx.fillRect(0, row.y, HEADER_W, row.height)
      ctx.fillStyle = '#bbbbbb'; ctx.font = '10px system-ui'; ctx.fillText(row.label, 18, row.y + 17)
      ctx.strokeStyle = '#303030'; ctx.strokeRect(.5, row.y + .5, width - 1, row.height - 1)
      ctx.save(); ctx.beginPath(); ctx.rect(HEADER_W, row.y, view.plotWidth, row.height); ctx.clip()

      if (bpm && bpm > 0) {
        const beat = 60 / bpm
        for (let tick = audioStart + Math.ceil((view.start - audioStart) / beat) * beat; tick < view.end; tick += beat) {
          const x = xAt(tick); ctx.strokeStyle = 'rgba(255,255,255,.06)'; ctx.beginPath(); ctx.moveTo(x, row.y); ctx.lineTo(x, row.y + row.height); ctx.stroke()
        }
      }

      if (row.kind === 'blocks') {
        row.items.forEach((raw, index) => {
          const item = raw as Record<string, unknown>
          const start = Number(item.start ?? item.t ?? 0)
          const next = row.items[index + 1] as Record<string, unknown> | undefined
          const end = Number(item.end ?? next?.t ?? start + 0.08)
          const x0 = xAt(start); const x1 = xAt(end)
          if (x1 < HEADER_W || x0 > width) return
          const viseme = String(item.viseme ?? '')
          ctx.fillStyle = VISEME_COLORS[viseme as keyof typeof VISEME_COLORS] ?? (row.id === 'phonemes' ? '#4e7a9a' : '#56667a')
          ctx.globalAlpha = .85; ctx.fillRect(x0 + 1, row.y + 5, Math.max(2, x1 - x0 - 2), row.height - 10); ctx.globalAlpha = 1
          const text = String(item.lyric ?? item.symbol ?? item.state ?? item.mouthPose ?? '')
          if (x1 - x0 > 18) { ctx.fillStyle = '#10131a'; ctx.font = '600 9px system-ui'; ctx.fillText(text, x0 + 4, row.y + row.height / 2 + 3) }
        })
      } else if (row.kind === 'events') {
        row.items.forEach((raw) => {
          const item = raw as Record<string, unknown>; const start = Number(item.t ?? 0); const durationValue = Number(item.duration ?? .12)
          const x0 = xAt(start); const x1 = xAt(start + durationValue)
          ctx.fillStyle = row.id === 'blink' ? '#d7ba7d' : '#4e7a9a'; ctx.fillRect(x0, row.y + 7, Math.max(3, x1 - x0), row.height - 14)
          const state = String(item.state ?? '')
          if (state && x1 - x0 > 20) { ctx.fillStyle = '#10131a'; ctx.fillText(state, x0 + 3, row.y + 17) }
        })
      } else if (row.kind === 'pitch') {
        ctx.strokeStyle = '#4ec9b0'; ctx.lineWidth = 2; ctx.beginPath()
        pitchItems.forEach((item, index) => {
          const y = row.y + row.height - 8 - ((item.midi - pitchMin) / (pitchMax - pitchMin)) * (row.height - 16)
          const x0 = xAt(item.start); const x1 = xAt(item.end)
          if (index === 0) ctx.moveTo(x0, y); else ctx.lineTo(x0, y)
          ctx.lineTo(x1, y)
          if (x1 - x0 > 34) { ctx.fillStyle = '#7fd8c8'; ctx.font = '9px Consolas'; ctx.fillText(noteName(item.midi), x0 + 3, y - 3) }
        }); ctx.stroke()
      } else if (row.kind === 'waveform') {
        const x0 = xAt(audioStart); const x1 = xAt(audioStart + audioDuration)
        if (peaks && audioDuration > 0) {
          ctx.save(); ctx.translate(x0, 0); drawWaveform(ctx, peaks, x1 - x0, row.y + row.height, { top: row.y + 4, bottom: row.y + row.height - 4, color: 'rgba(78,201,176,.55)' }); ctx.restore()
        } else { ctx.fillStyle = '#8a8a8a'; ctx.fillText('未导入音频', HEADER_W + 12, row.y + 20) }
      }
      ctx.restore()
    }
    const playX = xAt(time)
    ctx.strokeStyle = '#55a5db'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(playX, 0); ctx.lineTo(playX, layout.height); ctx.stroke()
  }, [audioDuration, audioStart, bpm, collapsed, layout, peaks, time, timeline, view, width, xAt])

  useEffect(() => { drawRuler(); drawTracks() }, [drawRuler, drawTracks])

  const timeAt = (clientX: number): number => {
    const rect = viewportRef.current?.getBoundingClientRect()
    const local = clamp(clientX - (rect?.left ?? 0) - HEADER_W, 0, view.plotWidth)
    return view.start + (local / view.plotWidth) * view.span
  }

  const rowAt = (clientY: number) => {
    const rect = viewportRef.current?.getBoundingClientRect()
    const y = clientY - (rect?.top ?? 0) - RULER_H + (viewportRef.current?.scrollTop ?? 0)
    return layout.rows.find((row) => y >= row.y && y < row.y + row.height)
  }

  const pointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = viewportRef.current?.getBoundingClientRect()
    const contentY = event.clientY - (rect?.top ?? 0) - RULER_H + (viewportRef.current?.scrollTop ?? 0)
    const group = layout.groups.find((item) => contentY >= item.y && contentY < item.y + GROUP_H)
    if (group && event.clientX - (rect?.left ?? 0) < HEADER_W) {
      setCollapsed((current) => { const next = new Set(current); next.has(group.id) ? next.delete(group.id) : next.add(group.id); return next })
      return
    }
    const row = rowAt(event.clientY)
    dragRef.current = { kind: row?.id === 'waveform' ? 'audio' : 'seek', x: event.clientX, audioStart }
    event.currentTarget.setPointerCapture(event.pointerId)
    if (dragRef.current.kind === 'seek') onSeek(timeAt(event.clientX))
  }

  const pointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    if (drag.kind === 'audio') onAudioStartChange(Math.round((drag.audioStart + ((event.clientX - drag.x) / view.plotWidth) * view.span) * 1000) / 1000)
    else onSeek(timeAt(event.clientX))
  }

  const pointerEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  const wheel = useCallback((event: WheelEvent) => {
    if (!(event.ctrlKey || event.shiftKey || event.altKey)) return
    event.preventDefault()
    if (event.altKey) {
      const order: Density[] = ['compact', 'normal', 'expanded']; const index = order.indexOf(density)
      setDensity(order[clamp(index + (event.deltaY > 0 ? -1 : 1), 0, order.length - 1)])
      return
    }
    const span = clamp(viewSpanFrac, .002, 1)
    if (event.shiftKey) {
      const delta = (event.deltaY || event.deltaX) / view.plotWidth * span
      onViewChange({ start: clamp(viewStartFrac + delta, 0, 1 - span), span }); return
    }
    const rect = viewportRef.current?.getBoundingClientRect(); const anchor = clamp((event.clientX - (rect?.left ?? 0) - HEADER_W) / view.plotWidth, 0, 1)
    const nextSpan = clamp(span * Math.exp(event.deltaY * .0014), .002, 1)
    onViewChange({ start: clamp(viewStartFrac + anchor * span - anchor * nextSpan, 0, 1 - nextSpan), span: nextSpan })
  }, [density, onViewChange, view.plotWidth, viewSpanFrac, viewStartFrac])

  useEffect(() => {
    const element = viewportRef.current
    if (!element) return
    element.addEventListener('wheel', wheel, { passive: false })
    return () => element.removeEventListener('wheel', wheel)
  }, [wheel])

  return (
    <div className="multi-timeline">
      <div className="multi-timeline-tools">
        <span>{timeline?.mode?.animationModeId ?? 'classic'} · {timeline?.mode?.mappingSetId ?? 'standard'}</span>
        <div className="segmented" aria-label="轨道高度">
          {(['compact', 'normal', 'expanded'] as Density[]).map((value) => (
            <button key={value} className={density === value ? 'active' : ''} onClick={() => setDensity(value)}>
              {{ compact: '紧凑', normal: '标准', expanded: '展开' }[value]}
            </button>
          ))}
        </div>
      </div>
      <canvas ref={rulerRef} className="timeline-ruler" />
      <div
        ref={viewportRef}
        className="multi-timeline-viewport"
        role="region"
        aria-label="多轨时间轴：SVP 原始数据、生成动画、音频"
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerEnd}
        onPointerCancel={pointerEnd}
      >
        <canvas ref={canvasRef} style={{ width: '100%', height: layout.height }} />
      </div>
    </div>
  )
}