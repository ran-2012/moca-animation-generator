// In-browser mock for every backend endpoint the UI consumes. It implements the
// same request/response shapes as CONTRACT.md §5 so the real fetch code path is
// byte-for-byte the same — only `api.ts` swaps the transport.
import type {
  AnimationModeId,
  AudioSummary,
  AutomapResult,
  BakeManifest,
  Blink,
  LayerNode,
  MappingProfile,
  PeaksResult,
  PsdUploadInfo,
  RenderFormat,
  RenderJobInfo,
  RenderRequestPayload,
  SvpUploadInfo,
  Timeline,
  TimelineFrame,
  TimelineResult,
  TrackInfo,
  Viseme,
} from '../types'
import { buildMockManifest, MOCK_CANVAS } from './mockImages'

const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

const ID_PSD = 'a1b2c3d4e5f6'
const ID_SVP = 'b2c3d4e5f6a7'
const ID_AUDIO = 'c3d4e5f6a7b8'

// ---------------------------------------------------------------------------
// PSD layer tree
// ---------------------------------------------------------------------------

interface LayerSeed {
  id: string
  name: string
  bbox: [number, number, number, number]
  visible?: boolean
}

function pixel(path: string, seed: LayerSeed): LayerNode {
  const [left, top, right, bottom] = seed.bbox
  return {
    id: seed.id,
    path,
    name: seed.name,
    kind: 'pixel',
    visible: seed.visible ?? true,
    bbox: seed.bbox,
    width: right - left,
    height: bottom - top,
    opacity: 255,
    blendMode: 'normal',
    children: [],
  }
}

function group(path: string, id: string, name: string, bbox: [number, number, number, number], children: LayerNode[]): LayerNode {
  const [left, top, right, bottom] = bbox
  return {
    id,
    path,
    name,
    kind: 'group',
    visible: true,
    bbox,
    width: right - left,
    height: bottom - top,
    opacity: 255,
    blendMode: 'normal',
    children,
  }
}

function buildTree(): LayerNode {
  const body = group('0', 'g_body', '体', [100, 690, 620, 960], [
    pixel('0.0', { id: '10', name: '制服', bbox: [104, 726, 616, 960] }),
    pixel('0.1', { id: '11', name: 'リボン', bbox: [292, 700, 428, 812] }),
    pixel('0.2', { id: '12', name: '首', bbox: [306, 540, 414, 716] }),
  ])

  const eyes = group('1.0', 'g_eyes', '目', [200, 360, 520, 470], [
    pixel('1.0.0', { id: '119', name: '目開き', bbox: [212, 372, 298, 458] }),
    pixel('1.0.1', { id: '120', name: '目閉じ', bbox: [212, 372, 298, 458] }),
    pixel('1.0.2', { id: '121', name: '瞳', bbox: [266, 388, 306, 432] }),
  ])

  const browGroup = group('1.1', 'g_brow', '眉', [200, 326, 520, 402], [
    pixel('1.1.0', { id: '130', name: '眉_通常', bbox: [240, 340, 480, 380] }),
    pixel('1.1.1', { id: '131', name: '眉_怒り', bbox: [240, 340, 480, 380] }),
    pixel('1.1.2', { id: '132', name: '眉_困り', bbox: [240, 340, 480, 380] }),
    pixel('1.1.3', { id: '133', name: '眉_驚き', bbox: [240, 340, 480, 380] }),
  ])

  const mouthGroup = group('1.2', 'g_mouth', '口', [268, 452, 452, 560], [
    pixel('1.2.0', { id: '63', name: 'あ', bbox: [330, 478, 390, 532] }),
    pixel('1.2.1', { id: '62', name: 'い', bbox: [326, 482, 394, 512] }),
    pixel('1.2.2', { id: '61', name: 'う', bbox: [340, 478, 380, 522] }),
    pixel('1.2.3', { id: '60', name: 'え', bbox: [332, 478, 388, 524] }),
    pixel('1.2.4', { id: '59', name: 'お', bbox: [336, 476, 384, 526] }),
    pixel('1.2.5', { id: '42', name: 'ん', bbox: [338, 488, 382, 518] }),
    pixel('1.2.6', { id: '44', name: '口_閉じ', bbox: [334, 494, 386, 514] }),
  ])

  const cheekGroup = group('1.3', 'g_cheek', '頬', [176, 416, 544, 512], [
    pixel('1.3.0', { id: '140', name: '頬_通常', bbox: [180, 420, 540, 510] }),
    pixel('1.3.1', { id: '141', name: '頬_赤', bbox: [180, 420, 540, 510] }),
    pixel('1.3.2', { id: '142', name: '頬_濃', bbox: [180, 420, 540, 510] }),
  ])

  const head = group('1', 'g_head', '頭', [120, 120, 600, 720], [eyes, browGroup, mouthGroup, cheekGroup, pixel('1.4', { id: '13', name: '輪郭', bbox: [198, 200, 522, 560] })])

  const hair = group('2', 'g_hair', '髪', [96, 96, 624, 890], [
    pixel('2.0', { id: '31', name: '後ろ髪', bbox: [114, 128, 606, 882] }),
    pixel('2.1', { id: '32', name: '前髪', bbox: [176, 140, 544, 420] }),
    pixel('2.2', { id: '33', name: 'アホ毛', bbox: [360, 92, 462, 172] }),
  ])

  const fx = group('3', 'g_fx', '背景効果', [0, 0, 720, 960], [
    pixel('3.0', { id: '41', name: 'ハイライト', bbox: [0, 0, 720, 960] }),
    pixel('3.1', { id: '45', name: '影', bbox: [0, 0, 720, 960] }),
  ])

  return {
    id: 'root',
    path: '',
    name: 'moca.psd',
    kind: 'group',
    visible: true,
    bbox: [0, 0, MOCK_CANVAS[0], MOCK_CANVAS[1]],
    width: MOCK_CANVAS[0],
    height: MOCK_CANVAS[1],
    opacity: 255,
    blendMode: 'normal',
    children: [body, head, hair, fx, pixel('4', { id: '5', name: '線画', bbox: [0, 0, 720, 960], visible: false })],
  }
}

const TREE = buildTree()

function clone<T>(value: T): T {
  return structuredClone(value)
}

// ---------------------------------------------------------------------------
// mapping profile
// ---------------------------------------------------------------------------

function buildProfile(): MappingProfile {
  return {
    psdAssetId: ID_PSD,
    canvas: [MOCK_CANVAS[0], MOCK_CANVAS[1]],
    base: {
      hiddenGroups: ['3'],
      hiddenLayers: ['5'],
      defaultState: { mouth: 'closed', eyes: 'open', brow: 'neutral', cheek: 'normal' },
    },
    channels: {
      mouth: { a: '63', i: '62', u: '61', e: '60', o: '59', n: '42', closed: '44' },
      eyes: { open: '119', blink: '120', smile: null, cry: null },
      brow: { neutral: '130', angry: '131', question: '132', surprise: '133', sad: null },
      cheek: { normal: '140', blush: '141', deep: '142' },
      sweat: {},
      eyeEffect: {},
    },
    zorder: ['cheek', 'mouth', 'eyes', 'brow'],
    meta: {
      auto: true,
      confidence: { mouth: 0.96, eyes: 0.92, brow: 0.71, cheek: 0.84 },
      warnings: ['brow.sad 未找到对应图层，已留空', '已隐藏「背景効果」组 (路径 3)'],
    },
  }
}

// ---------------------------------------------------------------------------
// SVP tracks + timeline
// ---------------------------------------------------------------------------

function buildTracks(): TrackInfo[] {
  return [
    {
      index: 0,
      name: '未命名音轨 1',
      isInstrumental: false,
      noteCount: 0,
      rangeStartSec: 0,
      rangeEndSec: 0,
      groups: [],
    },
    {
      index: 1,
      name: 'Vocal-Chorus_L',
      isInstrumental: false,
      noteCount: 428,
      rangeStartSec: 15.82,
      rangeEndSec: 238.8,
      groups: [{ name: 'Vocal-Chorus_L', noteCount: 428 }],
    },
    {
      index: 2,
      name: 'Vocal-Chorus_R',
      isInstrumental: false,
      noteCount: 435,
      rangeStartSec: 15.79,
      rangeEndSec: 238.82,
      groups: [{ name: 'Vocal-Chorus_R', noteCount: 435 }],
    },
    {
      index: 3,
      name: 'ハモリ',
      isInstrumental: false,
      noteCount: 196,
      rangeStartSec: 27.4,
      rangeEndSec: 232.1,
      groups: [{ name: 'Harmony', noteCount: 196 }],
    },
    {
      index: 4,
      name: '未命名音轨 5',
      isInstrumental: false,
      noteCount: 435,
      rangeStartSec: 15.79,
      rangeEndSec: 238.82,
      groups: [
        { name: 'Vocal-Chorus_R', noteCount: 12 },
        { name: 'Vocal-Chorus_L', noteCount: 8 },
      ],
    },
    {
      index: 5,
      name: '伴奏 (Inst)',
      isInstrumental: true,
      noteCount: 1122,
      rangeStartSec: 0,
      rangeEndSec: 238.9,
      groups: [{ name: 'Piano', noteCount: 560 }, { name: 'Drums', noteCount: 562 }],
    },
  ]
}

function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const MOCK_DURATION = 28

function buildTimeline(
  trackIndex: number,
  fps: number,
  options: { mappingSetId?: string; animationModeId?: AnimationModeId } = {},
): { timeline: Timeline; blinks: Blink[]; stats: Record<string, unknown> } {
  const random = mulberry32(0x9e3779b9 + trackIndex * 7919)
  const frames: TimelineFrame[] = [{ t: 0, viseme: 'closed', openness: 0 }]

  const weighted: Array<[Viseme, number]> = [
    ['a', 0.24],
    ['i', 0.14],
    ['u', 0.1],
    ['e', 0.13],
    ['o', 0.11],
    ['n', 0.12],
    ['f', 0.05],
    ['closed', 0.11],
  ]
  const total = weighted.reduce((sum, [, weight]) => sum + weight, 0)

  let time = 0.4
  let previous: Viseme = 'closed'
  while (time < MOCK_DURATION - 0.2) {
    let roll = random() * total
    let viseme: Viseme = 'closed'
    for (const [candidate, weight] of weighted) {
      roll -= weight
      if (roll <= 0) {
        viseme = candidate
        break
      }
    }
    if (viseme === 'closed' && previous !== 'closed' && random() < 0.6) {
      viseme = 'n'
    }
    const openness =
      viseme === 'closed' ? 0 : Math.round((0.35 + random() * 0.62) * 100) / 100
    const mouthPose = options.animationModeId === 'classic'
      ? undefined
      : viseme === 'a' && openness > 0.8
        ? 'openLarge'
        : viseme === 'n' || viseme === 'f'
          ? 'narrow'
          : viseme === 'u' || viseme === 'o'
            ? 'roundSmall'
            : viseme
    frames.push({
      t: Math.round(time * 1000) / 1000,
      viseme,
      openness,
      mouthPose,
      phase: viseme === 'closed' ? 'idle' : 'sustain',
    })
    previous = viseme
    time += 0.07 + random() * 0.22
  }

  const blinks: Blink[] = []
  let blinkAt = 1.7 + random() * 1.2
  while (blinkAt < MOCK_DURATION - 0.4) {
    blinks.push({ t: Math.round(blinkAt * 1000) / 1000, duration: Math.round((0.1 + random() * 0.11) * 1000) / 1000 })
    blinkAt += 2.9 + random() * 1.8
  }

  const timeline: Timeline = {
    fps,
    duration: MOCK_DURATION,
    frames,
    source: { kind: 'svp', assetId: ID_SVP, trackIndex },
    mode: {
      mappingSetId: options.mappingSetId ?? 'standard',
      animationModeId: options.animationModeId ?? 'natural',
      animationModeVersion: 1,
    },
    sourceTracks: {
      notes: frames.slice(1, 25).map((frame, index) => ({
        index,
        start: frame.t,
        end: Math.min(MOCK_DURATION, frame.t + 0.28),
        lyric: ['流', '沙', '落', '在'][index % 4],
        pitchMidi: 58 + (index % 12),
      })),
      phonemes: frames.slice(1, 49).map((frame, index) => ({
        start: frame.t,
        end: Math.min(MOCK_DURATION, frame.t + 0.12),
        symbol: frame.viseme,
        kind: frame.viseme === 'closed' ? 'pause' : 'vowel',
        timing: 'estimated' as const,
        noteIndex: Math.floor(index / 2),
      })),
      pitch: frames.slice(1, 25).map((frame, index) => ({
        start: frame.t,
        end: Math.min(MOCK_DURATION, frame.t + 0.28),
        midi: 58 + (index % 12),
        source: 'note',
      })),
    },
    tracks: {
      mouth: frames.map((frame) => ({
        t: frame.t,
        state: frame.mouthPose ?? frame.viseme,
        viseme: frame.viseme,
        phase: frame.phase,
        openness: frame.openness,
      })),
      blink: blinks,
      eyes: blinks.flatMap((blink) => [
        { t: blink.t, state: 'blink' },
        { t: blink.t + blink.duration, state: 'open' },
      ]),
      brow: [],
      cheek: [],
      sweat: [],
      eyeEffect: [],
    },
  }

  const visemeSet = new Set(frames.map((frame) => frame.viseme))
  return {
    timeline,
    blinks,
    stats: {
      frames: frames.length,
      visemes: visemeSet.size,
      blinks: blinks.length,
      fps,
      notes: 435,
    },
  }
}

// ---------------------------------------------------------------------------
// mock audio (waveform peaks + a real playable WAV blob)
// ---------------------------------------------------------------------------

const MOCK_BPM = 76
const BEAT_SEC = 60 / MOCK_BPM
const SAMPLE_RATE = 8000

function envelopeAt(t: number): number {
  const beatPhase = (t % BEAT_SEC) / BEAT_SEC
  const pulse = Math.exp(-beatPhase * 7)
  const phrase = t < 4 ? 0.35 : t < 12 ? 0.72 : t < 18 ? 0.46 : t < 24 ? 0.86 : 0.3
  const wobble = 0.86 + 0.14 * Math.sin(t * 0.7)
  const value = 0.12 + phrase * pulse * 0.85 * wobble + 0.05 * Math.sin(t * 13.1)
  return Math.max(0.04, Math.min(1, value))
}

function buildPeaks(points: number): number[] {
  const peaks: number[] = []
  for (let i = 0; i < points; i += 1) {
    const t = (i / points) * MOCK_DURATION
    const detail = 0.72 + 0.28 * Math.abs(Math.sin(i * 0.37))
    peaks.push(Math.round(envelopeAt(t) * detail * 1000) / 1000)
  }
  return peaks
}

let audioPeaks: number[] = []
let audioBlobUrl: string | null = null

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i))
}

function buildWav(): Blob {
  const sampleCount = Math.floor(MOCK_DURATION * SAMPLE_RATE)
  const buffer = new ArrayBuffer(44 + sampleCount * 2)
  const view = new DataView(buffer)
  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + sampleCount * 2, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, SAMPLE_RATE, true)
  view.setUint32(28, SAMPLE_RATE * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, sampleCount * 2, true)

  let phase = 0
  for (let i = 0; i < sampleCount; i += 1) {
    const t = i / SAMPLE_RATE
    const beatPhase = (t % BEAT_SEC) / BEAT_SEC
    const pulse = Math.exp(-beatPhase * 7)
    const phrase = t < 4 ? 0.35 : t < 12 ? 0.72 : t < 18 ? 0.46 : t < 24 ? 0.86 : 0.3
    const carrier = Math.sin(phase) * 0.16 + Math.sin(phase * 1.5) * 0.09
    const beatTone = Math.sin(2 * Math.PI * 440 * (t % BEAT_SEC)) * pulse * 0.22 * phrase
    const pad = Math.sin(2 * Math.PI * 110 * t) * 0.06
    phase += (2 * Math.PI * (196 + 26 * Math.sin(t * 0.6))) / SAMPLE_RATE
    const sample = (carrier + beatTone + pad) * phrase
    view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true)
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

function ensureAudio(): { peaks: number[]; url: string } {
  if (!audioBlobUrl) audioBlobUrl = URL.createObjectURL(buildWav())
  audioPeaks = buildPeaks(1200)
  return { peaks: audioPeaks, url: audioBlobUrl }
}

// ---------------------------------------------------------------------------
// mutable mock state
// ---------------------------------------------------------------------------

interface MockState {
  psd: PsdUploadInfo | null
  profile: MappingProfile | null
  manifest: BakeManifest | null
  svp: SvpUploadInfo | null
  timeline: TimelineResult | null
  audio: AudioSummary | null
}

const state: MockState = {
  psd: null,
  profile: null,
  manifest: null,
  svp: null,
  timeline: null,
  audio: null,
}

export function resetMockState(): void {
  state.psd = null
  state.profile = null
  state.manifest = null
  state.svp = null
  state.timeline = null
  state.audio = null
  renderJobs.clear()
  previewCache.clear()
}

function requirePsd(assetId: string): void {
  if (!state.psd || state.psd.assetId !== assetId) {
    const error = new Error('PSD 素材不存在（mock）')
    ;(error as Error & { status?: number }).status = 404
    throw error
  }
}

// ---------------------------------------------------------------------------
// mocked endpoints
// ---------------------------------------------------------------------------

export async function uploadPsd(file: File): Promise<PsdUploadInfo> {
  await delay(650)
  state.psd = {
    assetId: ID_PSD,
    filename: file.name || 'moca.psd',
    width: MOCK_CANVAS[0],
    height: MOCK_CANVAS[1],
    dpi: 72,
    layerCount: 37,
    groupCount: 9,
  }
  state.profile = null
  state.manifest = null
  return clone(state.psd)
}

export async function getTree(assetId: string): Promise<LayerNode> {
  await delay(420)
  requirePsd(assetId)
  return clone(TREE)
}

export async function automap(assetId: string): Promise<AutomapResult> {
  await delay(950)
  requirePsd(assetId)
  state.profile = buildProfile()
  return { profile: clone(state.profile), warnings: clone(state.profile.meta.warnings ?? []) }
}

export async function saveProfile(assetId: string, profile: MappingProfile): Promise<void> {
  await delay(380)
  requirePsd(assetId)
  state.profile = clone(profile)
}

export async function bake(assetId: string, profile?: MappingProfile): Promise<BakeManifest> {
  await delay(2100)
  requirePsd(assetId)
  if (profile) state.profile = clone(profile)
  const manifest = await buildMockManifest(assetId)
  state.manifest = manifest
  return manifest
}

export async function getManifest(assetId: string): Promise<BakeManifest | null> {
  await delay(220)
  if (!state.psd || state.psd.assetId !== assetId) return null
  return state.manifest ? clone(state.manifest) : null
}

export async function uploadSvp(file: File): Promise<SvpUploadInfo> {
  await delay(520)
  state.svp = {
    assetId: ID_SVP,
    filename: file.name || '流沙.svp',
    version: 'Synthesizer V Studio Pro 1.11.0',
    tracks: buildTracks(),
    warnings: ['已跳过 3 条无音符的音轨'],
  }
  state.timeline = null
  return clone(state.svp)
}

export async function generateTimeline(
  assetId: string,
  trackIndex: number,
  fps: number,
  options?: { mappingSetId?: string; animationModeId?: AnimationModeId },
): Promise<TimelineResult> {
  await delay(1150)
  if (!state.svp || state.svp.assetId !== assetId) {
    const error = new Error('SVP 素材不存在（mock）')
    ;(error as Error & { status?: number }).status = 404
    throw error
  }
  const track = state.svp.tracks.find((candidate) => candidate.index === trackIndex)
  if (!track) {
    const error = new Error(`轨道 ${trackIndex} 不存在`)
    ;(error as Error & { status?: number }).status = 400
    throw error
  }
  if (track.isInstrumental) {
    const error = new Error('伴奏轨没有音符，无法生成口型时间轴，请选择人声轨')
    ;(error as Error & { status?: number }).status = 400
    throw error
  }
  const built = buildTimeline(trackIndex, fps, options)
  state.timeline = { timeline: built.timeline, blinks: built.blinks, stats: built.stats, warnings: ['mock 时间轴仅生成前 28 秒用于预览'] }
  return clone(state.timeline)
}

export async function uploadAudio(file: File): Promise<AudioSummary> {
  await delay(700)
  const { peaks } = ensureAudio()
  audioPeaks = peaks
  state.audio = {
    assetId: ID_AUDIO,
    filename: file.name || 'audio.wav',
    durationSec: MOCK_DURATION,
    bpm: MOCK_BPM,
    offsetSec: 0,
    sampleRate: SAMPLE_RATE,
    channels: 1,
  }
  return clone(state.audio)
}

export async function getPeaks(assetId: string, points: number): Promise<PeaksResult> {
  await delay(260)
  if (!state.audio || state.audio.assetId !== assetId) {
    const error = new Error('音频素材不存在（mock）')
    ;(error as Error & { status?: number }).status = 404
    throw error
  }
  ensureAudio()
  const source = audioPeaks
  if (points === source.length) return { points: source.length, peaks: [...source] }
  const peaks: number[] = []
  for (let i = 0; i < points; i += 1) {
    const start = Math.floor((i / points) * source.length)
    const end = Math.max(start + 1, Math.floor(((i + 1) / points) * source.length))
    let max = 0
    for (let j = start; j < end; j += 1) max = Math.max(max, source[j])
    peaks.push(max)
  }
  return { points: peaks.length, peaks }
}

export async function saveBpm(assetId: string, bpm: number, offsetSec: number): Promise<void> {
  await delay(320)
  if (!state.audio || state.audio.assetId !== assetId) {
    const error = new Error('音频素材不存在（mock）')
    ;(error as Error & { status?: number }).status = 404
    throw error
  }
  state.audio.bpm = bpm
  state.audio.offsetSec = offsetSec
}

export function audioFileUrl(assetId: string): string | null {
  if (!state.audio || state.audio.assetId !== assetId) return null
  ensureAudio()
  return audioBlobUrl
}

// ---------------------------------------------------------------------------
// render / export jobs (simulated progress; download is a composed preview PNG)
// ---------------------------------------------------------------------------

interface MockRenderJob {
  info: RenderJobInfo
  startedAt: number
  totalMs: number
  preview: Promise<string> | null
}

const renderJobs = new Map<string, MockRenderJob>()
const previewCache = new Map<number, Promise<string>>()
let mockRenderSeq = 0

const RENDER_FORMAT_EXT: Record<RenderFormat, string> = {
  png_zip: 'zip',
  prores4444: 'mov',
  webm_alpha: 'webm',
  mp4: 'mp4',
}

function renderError(message: string, status: number): Error {
  const error = new Error(message)
  ;(error as Error & { status?: number }).status = status
  return error
}

function loadImageElement(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('mock 预览图加载失败'))
    image.src = url
  })
}

/** Compose the mock character at the requested export width as a PNG data URL. */
function buildPreviewDataUrl(width: number, height: number): Promise<string> {
  const cached = previewCache.get(width)
  if (cached) return cached
  const promise = (async () => {
    const manifest = await buildMockManifest(ID_PSD)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    const scale = width / manifest.width
    ctx.fillStyle = '#101010'
    ctx.fillRect(0, 0, width, height)
    const base = await loadImageElement(manifest.base.url)
    ctx.drawImage(base, 0, 0, width, height)
    const initialState: Array<[string, string]> = [
      ['cheek', 'normal'],
      ['mouth', 'closed'],
      ['eyes', 'open'],
      ['brow', 'neutral'],
    ]
    for (const [channel, value] of initialState) {
      const patch = manifest.patches[`${channel}.${value}`]
      if (!patch) continue
      const image = await loadImageElement(patch.url)
      ctx.drawImage(
        image,
        patch.offset[0] * scale,
        patch.offset[1] * scale,
        patch.width * scale,
        patch.height * scale,
      )
    }
    return canvas.toDataURL('image/png')
  })()
  previewCache.set(width, promise)
  return promise
}

export async function submitRender(payload: RenderRequestPayload): Promise<RenderJobInfo> {
  await delay(200)
  if (!state.manifest) {
    throw renderError('该 PSD 还没有烘焙纹理（manifest 不存在）。请先在图层映射区点击「烘焙」。', 400)
  }
  const duration = payload.durationSec
  if (!(duration > 0)) throw renderError('durationSec 必须大于 0。', 400)
  if (duration > 300) throw renderError('单次导出最多 300 秒。', 400)
  const frameCount = Math.max(1, Math.ceil(duration * payload.outFps))
  if (frameCount > 6000) {
    throw renderError(`单次最多 6000 帧（当前 ${frameCount}），请缩短时长或降低 fps。`, 400)
  }
  if (payload.startSec + duration > payload.timeline.duration + 0.5) {
    throw renderError('导出区间超出时间轴范围。', 400)
  }
  mockRenderSeq += 1
  const jobId = `r_mock${String(mockRenderSeq).padStart(6, '0')}`
  const width = Math.max(200, Math.min(2480, Math.round(payload.width)))
  const height = Math.round((MOCK_CANVAS[1] * width) / MOCK_CANVAS[0])
  const info: RenderJobInfo = {
    jobId,
    status: 'queued',
    progress: 0,
    format: payload.format,
    fps: payload.outFps,
    width,
    height: height % 2 === 0 ? height : height + 1,
    frameCount,
    doneFrames: 0,
    fileUrl: null,
    fileName: null,
    error: null,
    elapsedSec: 0,
    createdAt: new Date().toISOString(),
  }
  renderJobs.set(jobId, {
    info,
    startedAt: Date.now(),
    totalMs: Math.min(3200, 600 + frameCount * 1.4),
    preview: null,
  })
  return clone(info)
}

export async function getRenderJob(jobId: string): Promise<RenderJobInfo> {
  await delay(140)
  const record = renderJobs.get(jobId)
  if (!record) throw renderError('渲染任务不存在（mock）。', 404)
  const info = record.info
  const elapsed = Date.now() - record.startedAt
  const progress = Math.min(1, elapsed / record.totalMs)
  if (progress >= 1) {
    if (!info.fileUrl) {
      record.preview = record.preview ?? buildPreviewDataUrl(info.width, info.height)
      let previewUrl = ''
      try {
        previewUrl = await record.preview
      } catch {
        previewUrl = ''
      }
      if (previewUrl) {
        info.status = 'done'
        info.progress = 1
        info.doneFrames = info.frameCount
        info.fileUrl = previewUrl
        info.fileName = `mock_preview_${info.width}x${info.height}.png`
        info.elapsedSec = Math.round(record.totalMs) / 1000
      } else {
        info.status = 'failed'
        info.error = '当前环境 canvas 不可用，mock 预览图生成失败。'
      }
    }
  } else {
    info.status = elapsed > 300 ? 'running' : 'queued'
    info.progress = Math.round(progress * 1000) / 1000
    info.doneFrames = Math.min(info.frameCount, Math.floor(progress * info.frameCount))
    info.elapsedSec = Math.round(elapsed / 100) / 10
  }
  return clone(info)
}

export function renderFileExtension(format: RenderFormat): string {
  return RENDER_FORMAT_EXT[format] ?? 'bin'
}
