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

export type MouthSlot = 'a' | 'i' | 'u' | 'e' | 'o' | 'n' | 'closed'
export type EyesSlot = 'open' | 'blink' | 'smile' | 'cry'
export type BrowSlot = 'neutral' | 'angry' | 'question' | 'surprise' | 'sad'
export type CheekSlot = 'normal' | 'blush' | 'deep'
export type ChannelName = 'mouth' | 'eyes' | 'brow' | 'cheek'

export interface Channels {
  mouth: Partial<Record<MouthSlot, string | null>>
  eyes: Partial<Record<EyesSlot, string | null>>
  brow: Partial<Record<BrowSlot, string | null>>
  cheek: Partial<Record<CheekSlot, string | null>>
}

export interface DefaultState {
  mouth: string
  eyes: string
  brow: string
  cheek: string
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
}

export interface BakeManifest {
  assetId: string
  width: number
  height: number
  base: { url: string }
  patches: Record<string, PatchManifest>
  zorder: string[]
  profileVersion: string
  bakedAt: string
}

export interface TimelineFrame {
  t: number
  viseme: Viseme
  openness?: number
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
  blink: boolean
  brow: string
  cheek: string
  openness: number
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
  brow: string
  cheek: string
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
  fps: number
  audio: AudioSummary | null
  bpm: number | null
  offset: number
  updatedAt?: string | null
}

export interface SessionResponse {
  session: SessionState | null
  savedAt: string | null
}
