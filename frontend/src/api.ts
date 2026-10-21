// Single fetch layer for the whole app. Every function has a real transport and
// a mock transport (toggle from the top bar / localStorage); the shapes are the
// CONTRACT.md §5 shapes in both cases.
import * as mock from './mock/mockBackend'
import type {
  AudioSummary,
  AutomapResult,
  BakeManifest,
  Blink,
  Channels,
  LayerNode,
  MappingProfile,
  PeaksResult,
  PsdUploadInfo,
  RenderFormat,
  RenderJobInfo,
  RenderJobStatus,
  RenderRequestPayload,
  SessionResponse,
  SessionState,
  SvpUploadInfo,
  Timeline,
  TimelineFrame,
  TimelineResult,
  TrackInfo,
  Viseme,
} from './types'
import { VISEMES } from './lib/timeline'

export class ApiError extends Error {
  status: number

  constructor(message: string, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// ---------------------------------------------------------------------------
// mock switch
// ---------------------------------------------------------------------------

let mockEnabled = true

export function setMockEnabled(enabled: boolean): void {
  mockEnabled = enabled
}

export function isMockEnabled(): boolean {
  return mockEnabled
}

async function callMock<T>(fn: () => Promise<T> | T): Promise<T> {
  try {
    return await fn()
  } catch (error) {
    const status = (error as { status?: number }).status ?? 0
    throw new ApiError(error instanceof Error ? error.message : 'Mock 调用失败', status)
  }
}

// ---------------------------------------------------------------------------
// transport
// ---------------------------------------------------------------------------

async function request<T>(path: string, init?: RequestInit, allow404 = false): Promise<T | null> {
  let response: Response
  try {
    response = await fetch(path, { ...init, cache: 'no-store' })
  } catch {
    throw new ApiError(`无法连接后端：${path}（请确认 127.0.0.1:8787 正在运行）`, 0)
  }
  if (response.status === 404 && allow404) return null
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const payload = (await response.json()) as { detail?: unknown }
      if (typeof payload?.detail === 'string' && payload.detail) detail = payload.detail
    } catch {
      /* binary or empty error body */
    }
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return null
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError(`响应不是合法 JSON（${path}）`, response.status)
  }
}

function jsonInit(payload: unknown, method = 'POST'): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  }
}

function uploadInit(file: File): RequestInit {
  const body = new FormData()
  body.append('file', file)
  return { method: 'POST', body }
}

// ---------------------------------------------------------------------------
// health
// ---------------------------------------------------------------------------

export interface HealthResult {
  online: boolean
  version?: string
}

/** Always talks to the real backend — used to decide the initial data source. */
export async function probeHealth(timeoutMs = 1600): Promise<HealthResult> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch('/api/health', { signal: controller.signal, cache: 'no-store' })
    if (!response.ok) return { online: false }
    const payload = (await response.json()) as { ok?: boolean; version?: string }
    return { online: payload?.ok !== false, version: payload?.version }
  } catch {
    return { online: false }
  } finally {
    window.clearTimeout(timer)
  }
}

// ---------------------------------------------------------------------------
// normalisers (defensive against backend nits)
// ---------------------------------------------------------------------------

function asNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function normalizeBbox(value: unknown): [number, number, number, number] {
  if (Array.isArray(value) && value.length >= 4) {
    return [asNumber(value[0]), asNumber(value[1]), asNumber(value[2]), asNumber(value[3])]
  }
  return [0, 0, 0, 0]
}

function normalizeTree(node: LayerNode | null | undefined): LayerNode {
  const raw = node ?? ({} as LayerNode)
  const bbox = normalizeBbox(raw.bbox)
  const children = Array.isArray(raw.children) ? raw.children.map(normalizeTree) : []
  const kind = raw.kind === 'group' || children.length > 0 ? 'group' : 'pixel'
  return {
    id: String(raw.id ?? ''),
    path: String(raw.path ?? ''),
    name: String(raw.name ?? '未命名图层'),
    kind,
    visible: raw.visible !== false,
    bbox,
    width: asNumber(raw.width, bbox[2] - bbox[0]),
    height: asNumber(raw.height, bbox[3] - bbox[1]),
    opacity: asNumber(raw.opacity, 255),
    blendMode: String(raw.blendMode ?? 'normal'),
    children,
  }
}

const DEFAULT_CHANNEL_KEYS: Record<string, string[]> = {
  mouth: ['a', 'i', 'u', 'e', 'o', 'n', 'closed', 'narrow', 'pressed', 'roundSmall', 'aSoft', 'wide', 'openLarge', 'openXLarge', 'scream'],
  eyes: ['open', 'blink', 'smile', 'cry'],
  brow: ['neutral', 'angry', 'question', 'surprise', 'sad'],
  cheek: ['normal', 'blush', 'deep'],
  sweat: ['single', 'double', 'neck'],
  eyeEffect: ['tear', 'cry'],
}

function normalizeProfile(input: MappingProfile | null | undefined, assetId: string): MappingProfile {
  const raw = (input ?? {}) as Partial<MappingProfile> & { channels?: Record<string, Record<string, unknown>> }
  const base = raw.base ?? { hiddenGroups: [], hiddenLayers: [], defaultState: {} }
  const defaultState = (base.defaultState ?? {}) as Partial<MappingProfile['base']['defaultState']>
  const channels = {} as Channels
  const channelNames = new Set([...Object.keys(DEFAULT_CHANNEL_KEYS), ...Object.keys(raw.channels ?? {})])
  for (const channel of channelNames) {
    const source = (raw.channels?.[channel] ?? {}) as Record<string, unknown>
    const target: Record<string, string | null> = {}
    const keys = new Set([...(DEFAULT_CHANNEL_KEYS[channel] ?? []), ...Object.keys(source)])
    for (const key of keys) {
      const value = source[key]
      target[key] = typeof value === 'string' && value ? value : null
    }
    channels[channel] = target
  }
  const canvas = Array.isArray(raw.canvas) ? raw.canvas : [0, 0]
  return {
    psdAssetId: String(raw.psdAssetId ?? assetId),
    canvas: [asNumber(canvas[0]), asNumber(canvas[1])],
    base: {
      hiddenGroups: Array.isArray(base.hiddenGroups) ? base.hiddenGroups.map(String) : [],
      hiddenLayers: Array.isArray(base.hiddenLayers) ? base.hiddenLayers.map(String) : [],
      defaultState: {
        mouth: String(defaultState.mouth ?? 'closed'),
        eyes: String(defaultState.eyes ?? 'open'),
        brow: String(defaultState.brow ?? 'neutral'),
        cheek: String(defaultState.cheek ?? 'normal'),
        sweat: String(defaultState.sweat ?? 'off'),
        eyeEffect: String(defaultState.eyeEffect ?? 'off'),
      },
    },
    channels,
    mappingSets: raw.mappingSets as MappingProfile['mappingSets'],
    defaultMappingSetId: String(raw.defaultMappingSetId ?? 'standard'),
    channelDefinitions: raw.channelDefinitions,
    zorder: Array.isArray(raw.zorder) && raw.zorder.length > 0 ? raw.zorder.map(String) : ['cheek', 'mouth', 'eyes', 'brow'],
    meta: {
      auto: raw.meta?.auto ?? false,
      confidence: raw.meta?.confidence ?? {},
      warnings: Array.isArray(raw.meta?.warnings) ? raw.meta.warnings.map(String) : [],
    },
  }
}

function normalizeManifest(input: BakeManifest | null, assetId: string): BakeManifest | null {
  if (!input) return null
  return {
    assetId: String(input.assetId ?? assetId),
    width: asNumber(input.width),
    height: asNumber(input.height),
    base: { url: String(input.base?.url ?? '') },
    patches: input.patches && typeof input.patches === 'object' ? input.patches : {},
    zorder: Array.isArray(input.zorder) && input.zorder.length > 0 ? input.zorder.map(String) : ['cheek', 'mouth', 'eyes', 'brow'],
    profileVersion: String(input.profileVersion ?? ''),
    bakedAt: String(input.bakedAt ?? ''),
  }
}

function normalizeTrack(raw: TrackInfo, index: number): TrackInfo {
  return {
    index: asNumber(raw.index, index),
    name: String(raw.name ?? `未命名音轨 ${index + 1}`),
    isInstrumental: raw.isInstrumental === true,
    noteCount: asNumber(raw.noteCount),
    rangeStartSec: asNumber(raw.rangeStartSec),
    rangeEndSec: asNumber(raw.rangeEndSec),
    groups: Array.isArray(raw.groups)
      ? raw.groups.map((group) =>
          typeof group === 'string'
            ? { name: group, noteCount: 0 }
            : { name: String(group?.name ?? ''), noteCount: asNumber(group?.noteCount) },
        )
      : [],
  }
}

function normalizeFrame(raw: TimelineFrame, fallbackTime: number): TimelineFrame {
  const viseme = (VISEMES as string[]).includes(raw.viseme) ? raw.viseme : 'closed'
  return {
    t: asNumber(raw.t, fallbackTime),
    viseme: viseme as Viseme,
    openness: raw.openness == null ? undefined : asNumber(raw.openness),
    mouthPose: raw.mouthPose == null ? undefined : String(raw.mouthPose),
    phase: raw.phase == null ? undefined : String(raw.phase),
    noteIndex: raw.noteIndex == null ? null : asNumber(raw.noteIndex),
  }
}

function normalizeTimeline(raw: Timeline | null | undefined, fallbackFps: number): Timeline {
  const timeline = raw ?? ({} as Timeline)
  const frames = Array.isArray(timeline.frames)
    ? timeline.frames.map((frame, index) => normalizeFrame(frame, index))
    : []
  frames.sort((a, b) => a.t - b.t)
  return {
    fps: asNumber(timeline.fps, fallbackFps),
    duration: asNumber(timeline.duration, frames.length > 0 ? frames[frames.length - 1].t : 0),
    frames,
    source: {
      kind: String(timeline.source?.kind ?? 'svp'),
      assetId: String(timeline.source?.assetId ?? ''),
      trackIndex: asNumber(timeline.source?.trackIndex),
    },
    mode: timeline.mode,
    sourceTracks: timeline.sourceTracks,
    tracks: timeline.tracks,
  }
}

function normalizeBlinks(raw: Blink[] | null | undefined): Blink[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((blink) => blink && typeof blink.t === 'number')
    .map((blink) => ({ t: asNumber(blink.t), duration: asNumber(blink.duration, 0.12) }))
}

// ---------------------------------------------------------------------------
// PSD
// ---------------------------------------------------------------------------

export async function uploadPsd(file: File): Promise<PsdUploadInfo> {
  if (mockEnabled) return callMock(() => mock.uploadPsd(file))
  const raw = await request<PsdUploadInfo>('/api/psd/upload', uploadInit(file))
  if (!raw) throw new ApiError('PSD 上传失败：后端返回空响应')
  return {
    assetId: String(raw.assetId ?? ''),
    filename: String(raw.filename ?? file.name),
    width: asNumber(raw.width),
    height: asNumber(raw.height),
    dpi: raw.dpi == null ? undefined : asNumber(raw.dpi),
    layerCount: asNumber(raw.layerCount),
    groupCount: asNumber(raw.groupCount),
  }
}

export async function getTree(assetId: string): Promise<LayerNode> {
  if (mockEnabled) return callMock(() => mock.getTree(assetId))
  const raw = await request<LayerNode>(`/api/psd/${assetId}/tree`)
  if (!raw) throw new ApiError('图层树为空')
  return normalizeTree(raw)
}

export function layerThumbUrl(assetId: string, layerId: string, size = 48): string {
  return `/api/psd/${assetId}/thumb/${encodeURIComponent(layerId)}?size=${size}`
}

export function psdPreviewUrl(assetId: string, width = 900): string {
  return `/api/psd/${assetId}/preview?width=${width}`
}

export async function automap(assetId: string): Promise<AutomapResult> {
  if (mockEnabled) {
    const result = await callMock(() => mock.automap(assetId))
    return { profile: normalizeProfile(result.profile, assetId), warnings: result.warnings ?? [] }
  }
  const raw = await request<AutomapResult>(`/api/psd/${assetId}/automap`, jsonInit({}))
  if (!raw) throw new ApiError('自动识别失败：后端返回空响应')
  const warnings = Array.isArray(raw.warnings)
    ? raw.warnings.map(String)
    : Array.isArray(raw.profile?.meta?.warnings)
      ? raw.profile.meta.warnings
      : []
  return { profile: normalizeProfile(raw.profile, assetId), warnings }
}

export async function saveProfile(assetId: string, profile: MappingProfile): Promise<void> {
  if (mockEnabled) {
    await callMock(() => mock.saveProfile(assetId, profile))
    return
  }
  await request(`/api/psd/${assetId}/profile`, jsonInit(profile, 'PUT'))
}

export async function bake(assetId: string, profile?: MappingProfile): Promise<BakeManifest> {
  if (mockEnabled) {
    const raw = await callMock(() => mock.bake(assetId, profile))
    return normalizeManifest(raw, assetId) as BakeManifest
  }
  const raw = await request<BakeManifest>(`/api/psd/${assetId}/bake`, jsonInit({ profile: profile ?? null }))
  const manifest = normalizeManifest(raw, assetId)
  if (!manifest || !manifest.base.url) throw new ApiError('烘焙失败：manifest 缺少 base 图')
  return manifest
}

export async function getManifest(assetId: string): Promise<BakeManifest | null> {
  if (mockEnabled) return callMock(() => mock.getManifest(assetId))
  const raw = await request<BakeManifest>(`/api/psd/${assetId}/manifest`, undefined, true)
  return normalizeManifest(raw, assetId)
}

// ---------------------------------------------------------------------------
// SVP
// ---------------------------------------------------------------------------

export async function uploadSvp(file: File): Promise<SvpUploadInfo> {
  if (mockEnabled) return callMock(() => mock.uploadSvp(file))
  const raw = await request<SvpUploadInfo>('/api/svp/upload', uploadInit(file))
  if (!raw) throw new ApiError('SVP 上传失败：后端返回空响应')
  const tracks = Array.isArray(raw.tracks) ? raw.tracks.map(normalizeTrack) : []
  return {
    assetId: String(raw.assetId ?? ''),
    filename: String(raw.filename ?? file.name),
    version: raw.version == null ? undefined : String(raw.version),
    tracks,
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
  }
}

export async function generateTimeline(
  assetId: string,
  trackIndex: number,
  fps = 60,
  options: { psdAssetId?: string; mappingSetId?: string; animationModeId?: import('./types').AnimationModeId } = {},
): Promise<TimelineResult> {
  if (mockEnabled) {
    const result = await callMock(() => mock.generateTimeline(assetId, trackIndex, fps, options))
    return {
      timeline: normalizeTimeline(result.timeline, fps),
      blinks: normalizeBlinks(result.blinks),
      stats: result.stats ?? {},
      warnings: result.warnings ?? [],
    }
  }
  const raw = await request<TimelineResult>(`/api/svp/${assetId}/timeline`, jsonInit({ trackIndex, fps, ...options }))
  if (!raw) throw new ApiError('时间轴生成失败：后端返回空响应')
  return {
    timeline: normalizeTimeline(raw.timeline, fps),
    blinks: normalizeBlinks(raw.blinks),
    stats: raw.stats ?? {},
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map(String) : [],
  }
}

// ---------------------------------------------------------------------------
// audio
// ---------------------------------------------------------------------------

export async function uploadAudio(file: File): Promise<AudioSummary> {
  if (mockEnabled) return callMock(() => mock.uploadAudio(file))
  const raw = await request<AudioSummary>('/api/audio/upload', uploadInit(file))
  if (!raw) throw new ApiError('音频上传失败：后端返回空响应')
  const duration = raw.durationSec ?? (raw as unknown as { duration?: number }).duration ?? null
  return {
    assetId: String(raw.assetId ?? ''),
    filename: String(raw.filename ?? file.name),
    durationSec: duration == null ? null : asNumber(duration, 0),
    bpm: raw.bpm == null ? null : asNumber(raw.bpm),
    offsetSec: raw.offsetSec == null ? 0 : asNumber(raw.offsetSec),
    sampleRate: raw.sampleRate == null ? null : asNumber(raw.sampleRate),
    channels: raw.channels == null ? null : asNumber(raw.channels),
  }
}

export async function getPeaks(assetId: string, points = 1200): Promise<PeaksResult> {
  if (mockEnabled) return callMock(() => mock.getPeaks(assetId, points))
  const raw = await request<PeaksResult | number[]>(`/api/audio/${assetId}/peaks?points=${points}`)
  const peaks = Array.isArray(raw) ? raw : Array.isArray(raw?.peaks) ? raw.peaks : []
  return {
    points: peaks.length,
    peaks: peaks.map((value) => Math.max(0, Math.min(1, asNumber(value)))),
  }
}

export async function saveBpm(assetId: string, bpm: number, offsetSec = 0): Promise<void> {
  if (mockEnabled) {
    await callMock(() => mock.saveBpm(assetId, bpm, offsetSec))
    return
  }
  await request(`/api/audio/${assetId}/bpm`, jsonInit({ bpm, offsetSec }, 'PUT'))
}

export function audioFileUrl(assetId: string): string {
  if (mockEnabled) return mock.audioFileUrl(assetId) ?? ''
  return `/api/audio/${assetId}/file`
}

// ---------------------------------------------------------------------------
// render / export
// ---------------------------------------------------------------------------

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function normalizeRenderJob(raw: RenderJobInfo, fallbackJobId = ''): RenderJobInfo {
  const formats: RenderFormat[] = ['png_zip', 'prores4444', 'webm_alpha', 'mp4']
  const statuses: RenderJobStatus[] = ['queued', 'running', 'done', 'failed']
  return {
    jobId: String(raw.jobId ?? fallbackJobId),
    status: statuses.includes(raw.status) ? raw.status : 'failed',
    progress: clamp01(asNumber(raw.progress)),
    format: formats.includes(raw.format) ? raw.format : 'png_zip',
    fps: asNumber(raw.fps, 24),
    width: asNumber(raw.width),
    height: asNumber(raw.height),
    frameCount: asNumber(raw.frameCount),
    doneFrames: asNumber(raw.doneFrames),
    fileUrl: raw.fileUrl ? String(raw.fileUrl) : null,
    fileName: raw.fileName ? String(raw.fileName) : null,
    error: raw.error ? String(raw.error) : null,
    elapsedSec: asNumber(raw.elapsedSec),
    createdAt: String(raw.createdAt ?? ''),
  }
}

export async function submitRender(payload: RenderRequestPayload): Promise<RenderJobInfo> {
  if (mockEnabled) {
    const raw = await callMock(() => mock.submitRender(payload))
    return normalizeRenderJob(raw)
  }
  const raw = await request<RenderJobInfo>('/api/render', jsonInit(payload))
  if (!raw) throw new ApiError('导出任务创建失败：后端返回空响应')
  return normalizeRenderJob(raw)
}

export async function getRenderJob(jobId: string): Promise<RenderJobInfo> {
  if (mockEnabled) {
    const raw = await callMock(() => mock.getRenderJob(jobId))
    return normalizeRenderJob(raw, jobId)
  }
  const raw = await request<RenderJobInfo>(`/api/render/${encodeURIComponent(jobId)}`)
  if (!raw) throw new ApiError('导出任务状态为空')
  return normalizeRenderJob(raw, jobId)
}

// ---------------------------------------------------------------------------
// session persistence (always hits the real backend, even in mock data mode)
// ---------------------------------------------------------------------------

export async function loadSession(): Promise<SessionResponse> {
  const raw = await request<SessionResponse>('/api/session', undefined, true)
  return raw ?? { session: null, savedAt: null }
}

export async function loadPreviousSession(): Promise<SessionResponse> {
  const raw = await request<SessionResponse>('/api/session/previous', undefined, true)
  return raw ?? { session: null, savedAt: null }
}

export async function saveSession(session: SessionState, keepalive = false): Promise<void> {
  const init = jsonInit(session, 'PUT')
  if (keepalive) init.keepalive = true
  await request('/api/session', init)
}

export async function clearSession(): Promise<void> {
  await request('/api/session', { method: 'DELETE' })
}
