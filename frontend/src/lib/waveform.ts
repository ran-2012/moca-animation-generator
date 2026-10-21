/** Shared waveform painter for the big timeline and the compact audio strip. */
export interface WaveformOptions {
  top?: number
  bottom?: number
  color?: string
  centerColor?: string | null
  minBar?: number
}

export function drawWaveform(
  ctx: CanvasRenderingContext2D,
  peaks: number[],
  width: number,
  height: number,
  options: WaveformOptions = {},
): void {
  const top = options.top ?? 0
  const bottom = options.bottom ?? height
  const center = (top + bottom) / 2
  const amplitude = Math.max(1, (bottom - top) / 2)
  ctx.save()
  if (options.centerColor !== null) {
    ctx.strokeStyle = options.centerColor ?? 'rgba(255, 255, 255, 0.06)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(0, Math.round(center) + 0.5)
    ctx.lineTo(width, Math.round(center) + 0.5)
    ctx.stroke()
  }
  ctx.fillStyle = options.color ?? 'rgba(56, 214, 196, 0.38)'
  const count = peaks.length
  if (count === 0) {
    ctx.restore()
    return
  }
  // One bar per device-independent pixel at most: keeps animation cheap.
  const columns = Math.max(1, Math.min(count, Math.floor(width)))
  let values: number[]
  if (count > columns) {
    values = new Array<number>(columns)
    for (let column = 0; column < columns; column += 1) {
      const start = Math.floor((column / columns) * count)
      const end = Math.max(start + 1, Math.floor(((column + 1) / columns) * count))
      let max = 0
      for (let index = start; index < end; index += 1) max = Math.max(max, peaks[index])
      values[column] = max
    }
  } else {
    values = peaks
  }
  const barWidth = Math.max(1, width / values.length)
  const minBar = options.minBar ?? 0.5
  for (let i = 0; i < values.length; i += 1) {
    const peak = Math.max(0, Math.min(1, values[i]))
    const h = Math.max(minBar, peak * amplitude)
    const x = (i / values.length) * width
    ctx.fillRect(x, center - h, Math.max(barWidth * 0.72, 1), h * 2)
  }
  ctx.restore()
}
