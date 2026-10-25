// Shared types — keep in sync with moca-diff/CONTRACT.md §4 (camelCase JSON).

export type LayerKind = 'group' | 'pixel'

export interface LayerNode {
  id: string
  path: string
  name: string
  kind: LayerKind
  visible: boolean
  bbox: [number, number, number, number]
  width: number
  height: number
  opacity: number
  blendMode: string
  children: LayerNode[]
}

export type Viseme = 'closed' | 'n' | 'f' | 'a' | 'i' | 'u' | 'e' | 'o'

export type MouthSlot =
  | 'a' | 'i' | 'u' | 'e' | 'o' | 'n' | 'closed'
  | 'narrow' | 'pressed' | 'roundSmall' | 'aSoft' | 'wide' | 'openLarge' | 'openXLarge' | 'scream'
export type EyesSlot = 'open' | 'blink' | 'smile' | 'cry'
export type BrowSlot = 'neutral' | 'angry' | 'question' | 'surprise' | 'sad'
export type CheekSlot = 'normal' | 'blush' | 'deep'
export type ChannelName = 'mouth' | 'eyes' | 'brow' | 'cheek' | 'sweat' | 'eyeEffect'
export type AnimationModeId = 'classic' | 'clear' | 'natural' | 'expressive'
export type TimelineDensity = 'compact' | 'normal' | 'expanded'

export interface Channels {
  mouth: Partial<Record<MouthSlot, string | null>>
  eyes: Partial<Record<EyesSlot, string | null>>
  brow: Partial<Record<BrowSlot, string | null>>
  cheek: Partial<Record<CheekSlot, string | null>>
  sweat: Record<string, string | null>
  eyeEffect: Record<string, string | null>
  [channel: string]: Record<string, string | null>
}

export interface DefaultState {
  mouth: string
  eyes: string
  brow: string
  cheek: string
  sweat?: string
  eyeEffect?: string
}

export interface MappingSet {
  label: string
  channels: Channels
}

export interface MappingProfile {
  psdAssetId: string
  canvas: [number, number]
  base: {
    hiddenGroups: string[]
    hiddenLayers: string[]
    defaultState: DefaultState
  }
  channels: Channels
  mappingSets?: Record<string, MappingSet>
  defaultMappingSetId?: string
  channelDefinitions?: Record<string, { behavior: 'exclusive' | 'overlay'; defaultState: string }>
  zorder: string[]
  meta: {
    auto?: boolean
    confidence?: Record<string, number>
    warnings?: string[]
  }
}

export interface PatchManifest {
  url: string
  offset: [number, number]
  width: number
  height: number
  z?: number
}

export interface StaticLayerManifest {
  url: string
  offset: [number, number]
  width: number
  height: number
  z: number
  name: string
  path: string
  group: string
  visible?: boolean
}

export interface BakeManifest {
  assetId: string
  width: number
  height: number
  base: { url: string }
  patches: Record<string, PatchManifest>
  layers?: Record<string, StaticLayerManifest>
  zorder: string[]
  profileVersion: string
  bakedAt: string
}

export interface TimelineFrame {
  t: number
  viseme: Viseme
  openness?: number
  mouthPose?: string
  phase?: string
  noteIndex?: number | null
}

export interface TimelineEvent {
  t: number
  state?: string
  viseme?: Viseme
  phase?: string
  openness?: number
  duration?: number
  noteIndex?: number | null
}

export interface SourceNote {
  index: number
  start: number
  end: number
  lyric: string
  pitchMidi: number
}

export interface SourcePhoneme {
  start: number
  end: number
  symbol: string
  kind: string
  timing: 'estimated' | 'source'
  noteIndex: number
}

export interface SourcePitch {
  start: number
  end: number
  midi: number
  source: string
}

export interface Timeline {
  fps: number
  duration: number
  frames: TimelineFrame[]
  source: {
    kind: string
    assetId: string
    trackIndex: number
  }
  mode?: {
    mappingSetId: string
    animationModeId: AnimationModeId
    animationModeVersion: number
  }
  sourceTracks?: {
    notes: SourceNote[]
    phonemes: SourcePhoneme[]
    pitch: SourcePitch[]
  }
  tracks?: Record<string, TimelineEvent[]>
}

export interface Blink {
  t: number
  duration: number
}

export interface Emotion {
  start: number
  end: number
  mood: string
  intensity: number
}

export interface TrackGroup {
  name: string
  noteCount: number
}

export interface TrackInfo {
  index: number
  name: string
  isInstrumental: boolean
  noteCount: number
  rangeStartSec: number
  rangeEndSec: number
  groups?: TrackGroup[]
}

export interface PsdUploadInfo {
  assetId: string
  filename: string
  width: number
  height: number
  dpi?: number
  layerCount: number
  groupCount: number
}

export interface SvpUploadInfo {
  assetId: string
  filename: string
  version?: string
  tracks: TrackInfo[]
  warnings?: string[]
}

export interface AudioSummary {
  assetId: string
  filename: string
  durationSec: number | null
  bpm: number | null
  offsetSec?: number
  sampleRate?: number | null
  channels?: number | null
}

export interface AutomapResult {
  profile: MappingProfile
  warnings: string[]
}

export interface TimelineResult {
  timeline: Timeline
  blinks: Blink[]
  stats?: Record<string, unknown>
  warnings?: string[]
}

export interface PeaksResult {
  points: number
  peaks: number[]
}

/** Derived per-frame state consumed by the stage renderer. */
export interface StageState {
  viseme: Viseme
  mouthPose?: string
  blink: boolean
  brow: string
  cheek: string
  openness: number
  channels: Record<string, string>
}

export interface SwayConfig {
  enabled: boolean
  amplitude: number
  frequency: number
  offset: number
}

export interface RenderSwayConfig extends SwayConfig {
  bpm: number | null
  audioStart: number
}

export interface ToastMessage {
  id: number
  kind: 'info' | 'success' | 'error'
  text: string
}

// ---------------------------------------------------------------------------
// render / export (CONTRACT.md §5.6)
// ---------------------------------------------------------------------------

export type RenderFormat = 'png_zip' | 'prores4444' | 'webm_alpha' | 'mp4'

export type RenderJobStatus = 'queued' | 'running' | 'done' | 'failed'

export interface RenderTimelinePayload {
  fps: number
  duration: number
  frames: TimelineFrame[]
  tracks?: Record<string, TimelineEvent[]>
}

export interface RenderRequestPayload {
  psdAssetId: string
  timeline: RenderTimelinePayload
  blinks: Blink[]
  startSec: number
  durationSec: number
  outFps: number
  width: number
  format: RenderFormat
  background: string
  brow: string | null
  cheek: string | null
  sway?: RenderSwayConfig
  hiddenLayers?: string[]
}

export interface RenderJobInfo {
  jobId: string
  status: RenderJobStatus
  progress: number
  format: RenderFormat
  fps: number
  width: number
  height: number
  frameCount: number
  doneFrames: number
  fileUrl: string | null
  fileName: string | null
  error: string | null
  elapsedSec: number
  createdAt: string
}

/** Compact workspace snapshot persisted by the backend session endpoint. */
export interface SessionState {
  version: number
  projectName: string
  mockMode: boolean
  time: number
  psd: PsdUploadInfo | null
  profile: MappingProfile | null
  hiddenGroups: string[]
  hiddenLayers: string[]
  selectedLayerId: string | null
  svp: SvpUploadInfo | null
  selectedTrack: number | null
  mappingSetId?: string
  animationModeId?: AnimationModeId
  fps: number
  timelineView?: { start: number; span: number }
  audio: AudioSummary | null
  bpm: number | null
  offset: number
  sway?: SwayConfig
  exclusiveGroups?: string[]
  manifestStale?: boolean
  updatedAt?: string | null
}

export interface SessionResponse {
  session: SessionState | null
  savedAt: string | null
}

export interface ProjectSummary {
  id: string
  name: string
  createdAt: string
  updatedAt: string
  psd: string | null
  svp: string | null
  audio: string | null
  mockMode: boolean
}
