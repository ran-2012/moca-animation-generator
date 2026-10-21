import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { Blink, Timeline } from '../types'
import { VISEME_COLORS, VISEME_LABELS, buildVisemeBlocks, pickTickStep } from '../lib/timeline'
import { clamp } from '../lib/format'
import { drawWaveform } from '../lib/waveform'

interface TimelineProps {
  timeline: Timeline | null
  blinks: Blink[]
  peaks: number[] | null
  duration: number
  time: number
  bpm: number | null
  audioStart: number
  audioDuration: number
  viewStartFrac: number
  viewSpanFrac: number
  onSeek: (time: number) => void
  onAudioStartChange: (value: number) => void
  onViewChange: (view: { start: number; span: number }) => void
}

interface Size {
  width: number
  height: number
}

const PAD = 8
const RULER_H = 22
const BLOCK_Y = 34
const BLOCK_H = 56
const BLINK_Y = BLOCK_Y + BLOCK_H + 4
const BLINK_H = 12
const WAVE_TOP = BLINK_Y + BLINK_H + 4

function rulerLabel(time: number, duration: number): string {
  if (duration >= 60) {
    const mm = Math.floor(time / 60)
    const ss = Math.floor(time % 60)
    return `${mm}:${String(ss).padStart(2, '0')}`
  }
  return `${time < 10 ? time.toFixed(1) : Math.round(time)}s`
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number): void {
  const r = Math.max(0, Math.min(radius, Math.min(width, height) / 2))
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + width, y, x + width, y + height, r)
  ctx.arcTo(x + width, y + height, x, y + height, r)
  ctx.arcTo(x, y + height, x, y, r)
  ctx.arcTo(x, y, x + width, y, r)
  ctx.closePath()
}

export function Timeline({
  timeline,
  blinks,
  peaks,
  duration,
  time,
  bpm,
  audioStart,
  audioDuration,
  viewStartFrac,
  viewSpanFrac,
  onSeek,
  onAudioStartChange,
  onViewChange,
}: TimelineProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const draggingRef = useRef(false)
  const audioDragRef = useRef<{ startX: number; startAudioStart: number; moved: boolean } | null>(null)
  const [size, setSize] = useState<Size>({ width: 0, height: 0 })
  const [hoverTime, setHoverTime] = useState<number | null>(null)
  const [hoverAudio, setHoverAudio] = useState(false)
  const [draggingAudio, setDraggingAudio] = useState(false)

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

  const blocks = useMemo(
    () => (timeline ? buildVisemeBlocks(timeline.frames, duration) : []),
    [timeline, duration],
  )

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || size.width < 4 || size.height < 4) return
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
    ctx.fillStyle = '#0b0e15'
    ctx.fillRect(0, 0, width, height)

    const plotW = Math.max(1, width - PAD * 2)
    const totalDuration = duration > 0 ? duration : 1
    const viewStart = clamp(viewStartFrac, 0, 1) * totalDuration
    const viewSpan = Math.max(1e-6, clamp(viewSpanFrac, 0.002, 1) * totalDuration)
    const viewEnd = Math.min(totalDuration, viewStart + viewSpan)
    // xFor() clamps (playhead / hover / ruler); xRaw() lets off-screen clips
    // be drawn and clipped by the canvas.
    const xFor = (t: number) => PAD + ((clamp(t, viewStart, viewEnd) - viewStart) / viewSpan) * plotW
    const xRaw = (t: number) => PAD + ((t - viewStart) / viewSpan) * plotW

    // ruler
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(PAD, RULER_H + 0.5)
    ctx.lineTo(width - PAD, RULER_H + 0.5)
    ctx.stroke()

    const waveTop = WAVE_TOP
    const waveBottom = Math.max(waveTop + 8, height - 6)

    if (duration > 0) {
      const step = pickTickStep(viewSpan)
      const minor = step / 2
      ctx.font = '10px "Cascadia Mono", Consolas, monospace'
      ctx.textBaseline = 'top'
      const firstTick = Math.floor(viewStart / minor) * minor
      for (let t = firstTick; t <= viewEnd + 1e-6; t += minor) {
        if (t < viewStart - 1e-6) continue
        const x = Math.round(xFor(t)) + 0.5
        const major = Math.abs(t / step - Math.round(t / step)) < 1e-6
        ctx.strokeStyle = major ? 'rgba(255, 255, 255, 0.16)' : 'rgba(255, 255, 255, 0.07)'
        ctx.beginPath()
        ctx.moveTo(x, RULER_H - (major ? 7 : 3))
        ctx.lineTo(x, RULER_H)
        ctx.stroke()
        if (major) {
          ctx.fillStyle = 'rgba(180, 190, 210, 0.55)'
          const label = rulerLabel(t, viewSpan)
          const textWidth = ctx.measureText(label).width
          const labelX = clamp(x - textWidth / 2, 2, width - textWidth - 2)
          ctx.fillText(label, labelX, 4)
        }
      }

      // beat grid: aligned to the audio clip when one is imported
      if (bpm && bpm > 0) {
        const beat = 60 / bpm
        const beatPx = (beat / viewSpan) * plotW
        if (beatPx >= 8) {
          ctx.strokeStyle = 'rgba(124, 92, 255, 0.10)'
          const gridStart = audioDuration > 0 ? audioStart : 0
          const gridEnd = audioDuration > 0 ? audioStart + audioDuration : duration
          const from = Math.max(viewStart, gridStart)
          const to = Math.min(viewEnd, gridEnd)
          const firstBeat = gridStart + Math.ceil(Math.max(0, from - gridStart) / beat) * beat
          for (let t = firstBeat; t <= to; t += beat) {
            if (t < from) continue
            const x = Math.round(xFor(t)) + 0.5
            ctx.beginPath()
            ctx.moveTo(x, RULER_H)
            ctx.lineTo(x, height - 4)
            ctx.stroke()
          }
        }
      }
    }

    // audio clip background (drag it to move the audio position)
    if (audioDuration > 0 && duration > 0) {
      const clipX0 = xRaw(audioStart)
      const clipX1 = xRaw(audioStart + audioDuration)
      const visibleStart = Math.max(PAD, clipX0)
      const visibleEnd = Math.min(width - PAD, clipX1)
      if (visibleEnd > visibleStart) {
        ctx.fillStyle = 'rgba(56, 214, 196, 0.045)'
        ctx.fillRect(visibleStart, waveTop, visibleEnd - visibleStart, waveBottom - waveTop)
        ctx.strokeStyle = 'rgba(56, 214, 196, 0.18)'
        ctx.lineWidth = 1
        ctx.strokeRect(visibleStart + 0.5, waveTop + 0.5, visibleEnd - visibleStart - 1, waveBottom - waveTop - 1)
        if (visibleEnd - visibleStart > 74) {
          ctx.fillStyle = 'rgba(56, 214, 196, 0.55)'
          ctx.font = '9px system-ui, sans-serif'
          ctx.textAlign = 'left'
          ctx.fillText('音频 · 拖动调整位置', visibleStart + 6, waveTop + 11)
        }
      }
    }

    // waveform: draw it at its real timeline position (audioStart can be negative)
    if (peaks && peaks.length > 0 && audioDuration > 0 && duration > 0) {
      const audioX0 = xRaw(audioStart)
      const audioX1 = xRaw(audioStart + audioDuration)
      const visibleStart = Math.max(PAD, audioX0)
      const visibleEnd = Math.min(width - PAD, audioX1)
      if (visibleEnd > visibleStart) {
        ctx.save()
        ctx.beginPath()
        ctx.rect(PAD, waveTop, plotW, waveBottom - waveTop)
        ctx.clip()
        ctx.translate(audioX0, 0)
        drawWaveform(ctx, peaks, audioX1 - audioX0, height, {
          top: waveTop,
          bottom: waveBottom,
          color: 'rgba(72, 189, 214, 0.42)',
        })
        ctx.restore()
      }
    } else {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.16)'
      ctx.font = '10px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('未导入音频', width / 2, (waveTop + waveBottom) / 2 - 5)
      ctx.textAlign = 'left'
    }

    // audio start marker (useful when the clip is delayed or starts before 0)
    if (audioDuration > 0 && Math.abs(audioStart) > 0.001) {
      const label = `音频起点 ${audioStart >= 0 ? '+' : ''}${audioStart.toFixed(2)}s`
      ctx.save()
      ctx.setLineDash([4, 4])
      ctx.strokeStyle = 'rgba(56, 214, 196, 0.55)'
      ctx.lineWidth = 1
      const markerX = clamp(xRaw(audioStart), PAD, width - PAD)
      ctx.beginPath()
      ctx.moveTo(markerX, RULER_H)
      ctx.lineTo(markerX, height - 4)
      ctx.stroke()
      ctx.restore()
      ctx.font = '9px "Cascadia Mono", Consolas, monospace'
      ctx.fillStyle = 'rgba(56, 214, 196, 0.85)'
      const textWidth = ctx.measureText(label).width
      const labelX = clamp(markerX + 4, PAD, width - textWidth - PAD)
      ctx.fillText(label, labelX, RULER_H + 3)
    }

    // viseme blocks
    if (blocks.length === 0) {
      ctx.save()
      ctx.setLineDash([5, 5])
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)'
      ctx.lineWidth = 1
      roundRect(ctx, PAD, BLOCK_Y, plotW, BLOCK_H, 8)
      ctx.stroke()
      ctx.restore()
      ctx.fillStyle = 'rgba(190, 198, 214, 0.5)'
      ctx.font = '11px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText(
        duration > 0 ? '音频已就绪 · 等待 SVP 时间轴' : '导入 SVP → 选择人声轨 → 生成时间轴',
        width / 2,
        BLOCK_Y + BLOCK_H / 2 - 4,
      )
      ctx.textAlign = 'left'
    } else {
      let activeIndex = -1
      for (let index = 0; index < blocks.length; index += 1) {
        const block = blocks[index]
        if (time >= block.start && time < block.end) {
          activeIndex = index
          break
        }
      }
      blocks.forEach((block, index) => {
        const x0 = xRaw(block.start)
        const x1 = xRaw(block.end)
        if (x1 < PAD || x0 > width - PAD) return
        const blockWidth = x1 - x0
        if (blockWidth < 0.5) return
        const color = VISEME_COLORS[block.viseme]
        ctx.save()
        ctx.beginPath()
        ctx.rect(PAD, BLOCK_Y, plotW, BLOCK_H)
        ctx.clip()
        ctx.beginPath()
        roundRect(ctx, x0 + 0.5, BLOCK_Y, Math.max(1, blockWidth - 1), BLOCK_H, 3)
        ctx.fillStyle = color
        ctx.globalAlpha = index === activeIndex ? 0.98 : 0.8
        ctx.fill()
        ctx.globalAlpha = 1
        if (index === activeIndex) {
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.75)'
          ctx.lineWidth = 1.5
          ctx.stroke()
        }
        if (blockWidth > 22) {
          ctx.fillStyle = 'rgba(10, 12, 18, 0.82)'
          ctx.font = '600 10px system-ui, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(VISEME_LABELS[block.viseme], x0 + blockWidth / 2, BLOCK_Y + BLOCK_H / 2 + 1)
          ctx.textAlign = 'left'
          ctx.textBaseline = 'top'
        }
        ctx.restore()
      })
    }

    // blink markers
    for (const blink of blinks) {
      const x = xRaw(blink.t)
      if (x < PAD - 4 || x > width - PAD + 4) continue
      ctx.fillStyle = 'rgba(245, 158, 11, 0.9)'
      ctx.beginPath()
      ctx.moveTo(x - 3, BLINK_Y + BLINK_H)
      ctx.lineTo(x + 3, BLINK_Y + BLINK_H)
      ctx.lineTo(x, BLINK_Y + 2)
      ctx.closePath()
      ctx.fill()
    }

    // hover indicator
    if (hoverTime != null && duration > 0) {
      const x = xFor(hoverTime)
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.28)'
      ctx.setLineDash([3, 4])
      ctx.beginPath()
      ctx.moveTo(x, RULER_H)
      ctx.lineTo(x, height - 4)
      ctx.stroke()
      ctx.setLineDash([])
      const label = `${hoverTime.toFixed(2)}s`
      ctx.font = '10px "Cascadia Mono", Consolas, monospace'
      const labelWidth = ctx.measureText(label).width + 10
      const labelX = clamp(x - labelWidth / 2, PAD, width - labelWidth - PAD)
      ctx.fillStyle = 'rgba(20, 24, 33, 0.95)'
      roundRect(ctx, labelX, height - 18, labelWidth, 15, 3)
      ctx.fill()
      ctx.fillStyle = 'rgba(230, 234, 245, 0.8)'
      ctx.fillText(label, labelX + 5, height - 15)
    }

    // playhead
    if (duration > 0) {
      const x = xFor(time)
      ctx.strokeStyle = '#ff6b8a'
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(x, RULER_H)
      ctx.lineTo(x, height - 4)
      ctx.stroke()
      ctx.fillStyle = '#ff6b8a'
      ctx.beginPath()
      ctx.moveTo(x - 4.5, RULER_H - 6)
      ctx.lineTo(x + 4.5, RULER_H - 6)
      ctx.lineTo(x, RULER_H + 1)
      ctx.closePath()
      ctx.fill()
    }

  }, [audioDuration, audioStart, blocks, blinks, bpm, duration, hoverTime, peaks, size, time, viewSpanFrac, viewStartFrac])

  useEffect(() => {
    draw()
  }, [draw])

  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const onWheel = (event: WheelEvent): void => {
      if (duration <= 0) return
      event.preventDefault()
      const rect = element.getBoundingClientRect()
      const plotW = Math.max(1, rect.width - PAD * 2)
      const localX = clamp(event.clientX - rect.left - PAD, 0, plotW)
      const anchor = localX / plotW
      const span = clamp(viewSpanFrac, 0.002, 1)
      if (event.shiftKey) {
        const delta = ((event.deltaY || event.deltaX) / plotW) * span
        onViewChange({ start: clamp(viewStartFrac + delta, 0, 1 - span), span })
        return
      }
      const factor = Math.exp(event.deltaY * 0.0014)
      const nextSpan = clamp(span * factor, 0.002, 1)
      const anchorTime = (clamp(viewStartFrac, 0, 1) + anchor * span) * duration
      let start = (anchorTime - anchor * nextSpan * duration) / duration
      start = clamp(start, 0, 1 - nextSpan)
      onViewChange({ start, span: nextSpan })
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [duration, onViewChange, viewSpanFrac, viewStartFrac])

  const timeFromEvent = (event: ReactPointerEvent<HTMLDivElement>): number => {
    const rect = event.currentTarget.getBoundingClientRect()
    const plotW = Math.max(1, rect.width - PAD * 2)
    const x = clamp(event.clientX - rect.left - PAD, 0, plotW)
    if (duration <= 0) return 0
    const viewStart = clamp(viewStartFrac, 0, 1) * duration
    const viewSpan = Math.max(1e-6, clamp(viewSpanFrac, 0.002, 1) * duration)
    return viewStart + (x / plotW) * viewSpan
  }

  const audioClipHit = (event: ReactPointerEvent<HTMLDivElement>): boolean => {
    if (audioDuration <= 0 || duration <= 0) return false
    const rect = event.currentTarget.getBoundingClientRect()
    const localY = event.clientY - rect.top
    if (localY < WAVE_TOP || localY > rect.height - 4) return false
    const plotW = Math.max(1, rect.width - PAD * 2)
    const localX = event.clientX - rect.left
    const viewStart = clamp(viewStartFrac, 0, 1) * duration
    const viewSpan = Math.max(1e-6, clamp(viewSpanFrac, 0.002, 1) * duration)
    const clipX0 = PAD + ((audioStart - viewStart) / viewSpan) * plotW
    const clipX1 = PAD + ((audioStart + audioDuration - viewStart) / viewSpan) * plotW
    return localX >= Math.min(clipX0, clipX1) - 6 && localX <= Math.max(clipX0, clipX1) + 6
  }

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (duration <= 0) return
    if (audioClipHit(event)) {
      event.preventDefault()
      event.currentTarget.setPointerCapture(event.pointerId)
      audioDragRef.current = {
        startX: event.clientX,
        startAudioStart: audioStart,
        moved: false,
      }
      setDraggingAudio(true)
      return
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    draggingRef.current = true
    const t = timeFromEvent(event)
    setHoverTime(t)
    onSeek(t)
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (duration <= 0) return
    if (audioDragRef.current) {
      const drag = audioDragRef.current
      const dx = event.clientX - drag.startX
      if (Math.abs(dx) > 1.5) drag.moved = true
      const rect = event.currentTarget.getBoundingClientRect()
      const plotW = Math.max(1, rect.width - PAD * 2)
      const viewSpan = Math.max(1e-6, clamp(viewSpanFrac, 0.002, 1) * duration)
      const delta = (dx / plotW) * viewSpan
      const next = Math.round((drag.startAudioStart + delta) * 1000) / 1000
      onAudioStartChange(next)
      setHoverTime(null)
      return
    }
    const t = timeFromEvent(event)
    setHoverTime(t)
    setHoverAudio(audioClipHit(event))
    if (draggingRef.current) onSeek(t)
  }

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (audioDragRef.current) {
      const drag = audioDragRef.current
      audioDragRef.current = null
      setDraggingAudio(false)
      if (!drag.moved) onSeek(timeFromEvent(event))
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }
      return
    }
    draggingRef.current = false
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  return (
    <div
      className={`timeline-canvas-wrap${hoverAudio ? ' audio-hover' : ''}${draggingAudio ? ' audio-dragging' : ''}`}
      ref={containerRef}
      title="拖动音频波形可调整音频位置；点击其他区域定位播放头"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onPointerLeave={() => {
        setHoverAudio(false)
        if (!draggingRef.current && !audioDragRef.current) setHoverTime(null)
      }}
    >
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
    </div>
  )
}
