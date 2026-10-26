import type { SwayConfig } from '../types'

export const DEFAULT_SWAY: SwayConfig = {
  enabled: false,
  amplitude: 0.35,
  frequency: 0.5,
  offsetMs: 0,
}

export function normalizeSway(value?: Partial<SwayConfig> | null): SwayConfig {
  const number = (candidate: unknown, fallback: number): number => {
    const parsed = Number(candidate)
    return Number.isFinite(parsed) ? parsed : fallback
  }
  return {
    enabled: Boolean(value?.enabled),
    amplitude: Math.max(0, Math.min(1, number(value?.amplitude, DEFAULT_SWAY.amplitude))),
    frequency: Math.max(0.125, Math.min(4, number(value?.frequency, DEFAULT_SWAY.frequency))),
    offsetMs: Math.max(-2000, Math.min(2000, Math.round(number(value?.offsetMs, DEFAULT_SWAY.offsetMs)))),
  }
}

export function swaySafetyScale(config: SwayConfig): number {
  return config.enabled ? 1 - 0.12 * normalizeSway(config).amplitude : 1
}

export function swayTransform(time: number, bpm: number | null, config: SwayConfig, audioStart = 0) {
  const normalized = normalizeSway(config)
  if (!normalized.enabled || !bpm || bpm <= 0 || normalized.amplitude <= 0) {
    return { angle: 0, scaleY: 1 }
  }
  // 偏移用毫秒：正值表示摇摆相位提前。
  const beat = (time - audioStart + normalized.offsetMs / 1000) * bpm / 60
  const phase = Math.PI * 2 * (beat * normalized.frequency)
  const strength = normalized.amplitude
  return {
    angle: (Math.PI / 180) * 4 * strength * Math.sin(phase),
    scaleY: 1 + 0.02 * strength * Math.cos(phase * 2),
  }
}

export function swayEvents(duration: number, bpm: number | null, config: SwayConfig, audioStart = 0) {
  const normalized = normalizeSway(config)
  if (!normalized.enabled || !bpm || bpm <= 0 || duration <= 0) return []
  const beat = 60 / bpm
  const step = beat / normalized.frequency
  let first = audioStart - normalized.offsetMs / 1000
  while (first < 0) first += step
  const events = []
  for (let t = first; t <= duration; t += step) {
    if (t >= 0) events.push({ t: Math.round(t * 1_000_000) / 1_000_000, duration: Math.min(0.12, step * 0.25), state: 'beat' })
  }
  return events
}