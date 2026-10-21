import type { Blink, TimelineFrame, Viseme } from '../types'
import { clamp } from './format'

export const VISEMES: Viseme[] = ['closed', 'n', 'f', 'a', 'i', 'u', 'e', 'o']

export const VISEME_COLORS: Record<Viseme, string> = {
  closed: '#59627a',
  n: '#6f8dff',
  f: '#9287ff',
  a: '#ff6b8a',
  i: '#ffd166',
  u: '#4fd1c5',
  e: '#b18bff',
  o: '#f59e0b',
}

export const VISEME_LABELS: Record<Viseme, string> = {
  closed: '闭口',
  n: 'ん',
  f: 'f',
  a: 'あ',
  i: 'い',
  u: 'う',
  e: 'え',
  o: 'お',
}

/** Index of the last frame with t <= time (binary search). -1 when before start. */
export function findFrameIndex(frames: TimelineFrame[], time: number): number {
  if (frames.length === 0) return -1
  let lo = 0
  let hi = frames.length - 1
  let result = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (frames[mid].t <= time + 1e-6) {
      result = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return result
}

export function visemeAt(frames: TimelineFrame[], time: number, fallback: Viseme = 'closed'): Viseme {
  const index = findFrameIndex(frames, time)
  return index >= 0 ? frames[index].viseme : fallback
}

export function opennessAt(frames: TimelineFrame[], time: number): number {
  const index = findFrameIndex(frames, time)
  if (index < 0) return 0
  return frames[index].openness ?? (frames[index].viseme === 'closed' ? 0 : 0.8)
}

export function isBlinkActive(blinks: Blink[], time: number): boolean {
  for (const blink of blinks) {
    if (time >= blink.t - 0.02 && time < blink.t + Math.max(blink.duration, 0.04) + 0.02) {
      return true
    }
  }
  return false
}

export interface VisemeBlock {
  start: number
  end: number
  viseme: Viseme
  openness?: number
}

/**
 * Merge consecutive frames carrying the same viseme into drawable blocks.
 * A block ends where the next block starts (or at `duration`).
 */
export function buildVisemeBlocks(frames: TimelineFrame[], duration: number): VisemeBlock[] {
  if (frames.length === 0) return []
  const blocks: VisemeBlock[] = []
  const end = duration > 0 ? duration : (frames[frames.length - 1].t ?? 0) + 0.5
  for (let i = 0; i < frames.length; i += 1) {
    const frame = frames[i]
    const isSame =
      blocks.length > 0 &&
      blocks[blocks.length - 1].viseme === frame.viseme &&
      Math.abs(blocks[blocks.length - 1].end - frame.t) < 1e-6
    if (isSame) {
      blocks[blocks.length - 1].end = i + 1 < frames.length ? frames[i + 1].t : end
    } else {
      blocks.push({
        start: frame.t,
        end: i + 1 < frames.length ? frames[i + 1].t : end,
        viseme: frame.viseme,
        openness: frame.openness,
      })
    }
  }
  return blocks.filter((block) => block.end > block.start)
}

/** Nice tick step (seconds) so the ruler shows roughly 6–10 labels. */
export function pickTickStep(duration: number, targetTicks = 8): number {
  const candidates = [0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]
  const ideal = Math.max(duration, 0.001) / targetTicks
  for (const candidate of candidates) {
    if (candidate >= ideal) return candidate
  }
  return candidates[candidates.length - 1]
}

export function clampTime(time: number, duration: number): number {
  if (!Number.isFinite(time)) return 0
  return clamp(time, 0, Math.max(duration, 0))
}
