export function clamp(value: number, min: number, max: number): number {
  return value < min ? min : value > max ? max : value
}

/** mm:ss.cs — used by timecode overlays; withFrames appends the frame number. */
export function formatTimecode(seconds: number, withFrames = false, fps = 60): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0
  const totalSeconds = Math.floor(safe)
  const mm = Math.floor(totalSeconds / 60)
  const ss = totalSeconds % 60
  if (withFrames) {
    const safeFps = Math.max(1, Math.round(fps))
    const frame = Math.min(safeFps - 1, Math.max(0, Math.floor((safe - totalSeconds) * safeFps)))
    return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}:${String(frame).padStart(2, '0')}`
  }
  const cs = Math.floor((safe - totalSeconds) * 100)
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}.${String(cs).padStart(2, '0')}`
}

/** 1:23 / 12.4s style labels for compact stats. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const mm = Math.floor(seconds / 60)
  const ss = Math.round(seconds % 60)
  return `${mm}:${String(ss).padStart(2, '0')}`
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}`
}

export function isAudioFile(file: File): boolean {
  return /\.(wav|mp3|flac|m4a|ogg|aac)$/i.test(file.name) || file.type.startsWith('audio/')
}

export function isPsdFile(file: File): boolean {
  return /\.psd$/i.test(file.name)
}

export function isSvpFile(file: File): boolean {
  return /\.svp$/i.test(file.name)
}
