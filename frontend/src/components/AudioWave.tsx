import { useCallback, useEffect, useRef, useState } from 'react'
import { drawWaveform } from '../lib/waveform'
import { clamp } from '../lib/format'

interface AudioWaveProps {
  peaks: number[] | null
  duration: number
  audioDuration: number
  start: number
  bpm: number | null
  time: number
}

export function AudioWave({ peaks, duration, audioDuration, start, bpm, time }: AudioWaveProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

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
    ctx.fillStyle = 'rgba(10, 13, 20, 0.9)'
    ctx.fillRect(0, 0, width, height)

    if (bpm && bpm > 0 && duration > 0) {
      const beat = 60 / bpm
      const beatPx = (beat / duration) * width
      if (beatPx >= 6) {
        ctx.strokeStyle = 'rgba(124, 92, 255, 0.16)'
        ctx.lineWidth = 1
        const audioEnd = start + audioDuration
        const from = audioDuration > 0 ? Math.max(0, start) : 0
        const to = audioDuration > 0 ? Math.min(duration, audioEnd) : duration
        const firstBeat = audioDuration > 0 ? start : 0
        const offsetToFirst = firstBeat >= 0 ? 0 : Math.ceil(-firstBeat / beat) * beat
        for (let t = firstBeat + offsetToFirst; t <= to; t += beat) {
          if (t < from) continue
          const x = Math.round((t / duration) * width) + 0.5
          ctx.beginPath()
          ctx.moveTo(x, 0)
          ctx.lineTo(x, height)
          ctx.stroke()
        }
      }
    }

    if (peaks && peaks.length > 0 && audioDuration > 0 && duration > 0) {
      const x0 = (start / duration) * width
      const x1 = ((start + audioDuration) / duration) * width
      const visibleStart = Math.max(0, x0)
      const visibleEnd = Math.min(width, x1)
      if (visibleEnd > visibleStart) {
        ctx.save()
        ctx.beginPath()
        ctx.rect(visibleStart, 0, visibleEnd - visibleStart, height)
        ctx.clip()
        ctx.translate(x0, 0)
        drawWaveform(ctx, peaks, x1 - x0, height, {
          top: 6,
          bottom: height - 6,
          color: 'rgba(86, 209, 224, 0.55)',
          centerColor: 'rgba(255, 255, 255, 0.07)',
        })
        ctx.restore()
      }
      if (duration > 0) {
        const x = clamp(time / duration, 0, 1) * width
        ctx.fillStyle = '#ff6b8a'
        ctx.fillRect(x - 0.75, 0, 1.5, height)
      }
    } else if (peaks && peaks.length > 0) {
      ctx.fillStyle = 'rgba(160, 170, 190, 0.45)'
      ctx.font = '10px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('音频在当前时间轴之外', width / 2, height / 2 + 3)
      ctx.textAlign = 'left'
    } else {
      ctx.fillStyle = 'rgba(160, 170, 190, 0.45)'
      ctx.font = '10px system-ui, sans-serif'
      ctx.textAlign = 'center'
      ctx.fillText('未导入音频', width / 2, height / 2 + 3)
      ctx.textAlign = 'left'
    }
  }, [audioDuration, bpm, duration, peaks, size, start, time])

  useEffect(() => {
    draw()
  }, [draw])

  return (
    <div className="audio-wave" ref={containerRef}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />
    </div>
  )
}
