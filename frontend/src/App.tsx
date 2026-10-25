import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import {
  ApiError,
  audioFileUrl,
  automap,
  bake,
  deleteProject,
  generateTimeline,
  getManifest,
  getPeaks,
  getTree,
  isMockEnabled,
  layerThumbUrl,
  listProjects,
  loadPreviousSession,
  loadProject,
  loadSession,
  probeHealth,
  saveBpm,
  saveProfile,
  saveSession,
  setMockEnabled,
  uploadAudio,
  uploadPsd,
  uploadSvp,
} from './api'
import type { HealthResult } from './api'
import { mockThumb } from './mock/mockImages'
import { TopBar } from './components/TopBar'
import { LayerTree } from './components/LayerTree'
import { MappingPanel } from './components/MappingPanel'
import type { BakeUiState } from './components/MappingPanel'
import { Stage } from './components/Stage'
import { MultiTrackTimeline } from './components/MultiTrackTimeline'
import { SvpPanel } from './components/SvpPanel'
import { AudioPanel } from './components/AudioPanel'
import { ExportPanel } from './components/ExportPanel'
import { ProjectPanel } from './components/ProjectPanel'
import { StatePanel } from './components/StatePanel'
import { StatusBar } from './components/StatusBar'
import {
  IconAlert,
  IconCheck,
  IconClock,
  IconImage,
  IconLayers,
  IconPause,
  IconPlay,
  IconSparkles,
  IconSpinner,
} from './components/Icons'
import { clamp, formatDuration, formatTimecode, isAudioFile, isPsdFile, isSvpFile } from './lib/format'
import { DEFAULT_SWAY, normalizeSway } from './lib/sway'
import {
  VISEME_COLORS,
  VISEMES,
  VISEME_LABELS,
  eventStateAt,
  isBlinkActive,
  mouthPoseAt,
  opennessAt,
  visemeAt,
} from './lib/timeline'
import type {
  AnimationModeId,
  AudioSummary,
  BakeManifest,
  Blink,
  ChannelName,
  LayerNode,
  MappingProfile,
  ProjectSummary,
  PsdUploadInfo,
  SessionState,
  StageState,
  SvpUploadInfo,
  Timeline as TimelineData,
  TimelineDensity,
  ToastMessage,
  Viseme,
  SwayConfig,
} from './types'

const DEFAULT_STATE = { mouth: 'closed', eyes: 'open', brow: 'neutral', cheek: 'normal' }

const TIMELINE_FPS = 60

// Layout ------------------------------------------------------------------
// The workspace is three resizable columns (left / stage / right) plus a
// resizable timeline dock underneath. Sizes persist per browser.
type ResizeKind = 'left' | 'right' | 'timeline'

interface LayoutState {
  left: number
  right: number
  timeline: number
}

const LAYOUT_KEY = 'mocadiff.layout.v2'
const DENSITIES: TimelineDensity[] = ['compact', 'normal', 'expanded']
const LAYOUT_LIMITS: Record<ResizeKind, { min: number; max: number }> = {
  left: { min: 240, max: 540 },
  right: { min: 280, max: 580 },
  timeline: { min: 200, max: 460 },
}

function clampLayoutSize(kind: ResizeKind, value: number, viewportHeight = 900): number {
  const { min, max } = LAYOUT_LIMITS[kind]
  const dynamicMax = kind === 'timeline' ? Math.min(max, Math.max(min, viewportHeight - 260)) : max
  const size = Number.isFinite(value) ? value : min
  return Math.round(clamp(size, min, dynamicMax))
}

function loadLayout(): LayoutState {
  const fallback: LayoutState = { left: 234, right: 274, timeline: 228 }
  try {
    const raw = window.localStorage.getItem(LAYOUT_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as Partial<LayoutState>
    return {
      left: clampLayoutSize('left', Number(parsed.left)),
      right: clampLayoutSize('right', Number(parsed.right)),
      timeline: clampLayoutSize('timeline', Number(parsed.timeline), window.innerHeight),
    }
  } catch {
    return fallback
  }
}

function loadDensity(): TimelineDensity {
  const saved = window.localStorage.getItem('mocadiff.timeline.density')
  return DENSITIES.includes(saved as TimelineDensity) ? (saved as TimelineDensity) : 'normal'
}

export default function App() {
  // data source -------------------------------------------------------------
  const [health, setHealth] = useState<HealthResult>({ online: false })
  const [mockMode, setMockMode] = useState(true)

  // project / PSD -----------------------------------------------------------
  const [projectName, setProjectName] = useState('未命名项目')
  const [psd, setPsd] = useState<PsdUploadInfo | null>(null)
  const [tree, setTree] = useState<LayerNode | null>(null)
  const [profile, setProfile] = useState<MappingProfile | null>(null)
  const [automapWarnings, setAutomapWarnings] = useState<string[]>([])
  const [dirty, setDirty] = useState(false)
  const [busyAutomap, setBusyAutomap] = useState(false)
  const [saving, setSaving] = useState(false)
  const [bakeState, setBakeState] = useState<BakeUiState>({ status: 'idle' })
  const [manifest, setManifest] = useState<BakeManifest | null>(null)
  const [manifestStale, setManifestStale] = useState(false)
  const [hiddenGroups, setHiddenGroups] = useState<Set<string>>(new Set())
  const [hiddenLayers, setHiddenLayers] = useState<Set<string>>(new Set())
  const [exclusiveGroups, setExclusiveGroups] = useState<Set<string>>(new Set())
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null)

  // SVP / timeline ----------------------------------------------------------
  const [svp, setSvp] = useState<SvpUploadInfo | null>(null)
  const [selectedTrack, setSelectedTrack] = useState<number | null>(null)
  const [mappingSetId, setMappingSetId] = useState('standard')
  const [animationModeId, setAnimationModeId] = useState<AnimationModeId>('natural')
  const [generating, setGenerating] = useState(false)
  const [timeline, setTimeline] = useState<TimelineData | null>(null)
  const [blinks, setBlinks] = useState<Blink[]>([])
  const [timelineWarnings, setTimelineWarnings] = useState<string[]>([])

  // audio -------------------------------------------------------------------
  const [audio, setAudio] = useState<AudioSummary | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [peaks, setPeaks] = useState<number[] | null>(null)
  const [bpm, setBpm] = useState<number | null>(null)
  const [offset, setOffset] = useState(0)
  const [bpmDirty, setBpmDirty] = useState(false)
  const [savingBpm, setSavingBpm] = useState(false)
  const [sway, setSway] = useState<SwayConfig>(DEFAULT_SWAY)

  // playback ----------------------------------------------------------------
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [timelineView, setTimelineView] = useState({ start: 0, span: 1 })
  const [timelineDensity, setTimelineDensity] = useState<TimelineDensity>(loadDensity)
  const [toasts, setToasts] = useState<ToastMessage[]>([])
  const [statusText, setStatusText] = useState('就绪 · 导入 PSD 开始')
  const [busy, setBusy] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [sessionReady, setSessionReady] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectsLoading, setProjectsLoading] = useState(false)
  const [projectsError, setProjectsError] = useState<string | null>(null)

  // layout ------------------------------------------------------------------
  const [layout, setLayout] = useState<LayoutState>(loadLayout)
  const layoutRef = useRef(layout)
  const resizeRef = useRef<{
    kind: ResizeKind
    startX: number
    startY: number
    start: LayoutState
  } | null>(null)

  // refs --------------------------------------------------------------------
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const timeRef = useRef(0)
  const durationRef = useRef(0)
  const offsetRef = useRef(0)
  const audioDurationRef = useRef(0)
  const clockBaseRef = useRef({ perf: 0, time: 0 })
  const toastSeq = useRef(0)
  const psdInputRef = useRef<HTMLInputElement | null>(null)
  const svpInputRef = useRef<HTMLInputElement | null>(null)
  const audioInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    layoutRef.current = layout
    try {
      window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout))
    } catch {
      // storage may be unavailable; sizing still works for this session
    }
  }, [layout])

  useEffect(() => {
    try {
      window.localStorage.setItem('mocadiff.timeline.density', timelineDensity)
    } catch {
      // storage may be unavailable; the current session keeps the choice
    }
  }, [timelineDensity])

  useEffect(() => {
    const onMove = (event: PointerEvent): void => {
      const drag = resizeRef.current
      if (!drag) return
      const dx = event.clientX - drag.startX
      const dy = event.clientY - drag.startY
      if (drag.kind === 'left') {
        const left = clampLayoutSize('left', drag.start.left + dx)
        setLayout((current) => (current.left === left ? current : { ...current, left }))
      } else if (drag.kind === 'right') {
        const right = clampLayoutSize('right', drag.start.right - dx)
        setLayout((current) => (current.right === right ? current : { ...current, right }))
      } else {
        const timeline = clampLayoutSize('timeline', drag.start.timeline - dy, window.innerHeight)
        setLayout((current) => (current.timeline === timeline ? current : { ...current, timeline }))
      }
    }
    const finish = (): void => {
      if (!resizeRef.current) return
      resizeRef.current = null
      delete document.body.dataset.resizing
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
      delete document.body.dataset.resizing
    }
  }, [])

  const startResize = useCallback(
    (kind: ResizeKind) => (event: ReactPointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return
      event.preventDefault()
      resizeRef.current = {
        kind,
        startX: event.clientX,
        startY: event.clientY,
        start: layoutRef.current,
      }
      document.body.dataset.resizing = kind
      try {
        event.currentTarget.setPointerCapture(event.pointerId)
      } catch {
        // capture is a nicety; window listeners already drive the drag
      }
    },
    [],
  )

  const layoutStyle = {
    '--left-width': `${layout.left}px`,
    '--right-width': `${layout.right}px`,
    '--timeline-height': `${layout.timeline}px`,
  } as CSSProperties

  const duration = Math.max(
    timeline?.duration ?? 0,
    audio?.durationSec ? Math.max(0, offset + audio.durationSec) : 0,
  )
  const fps = timeline?.fps ?? TIMELINE_FPS
  const defaultState = profile?.base.defaultState ?? DEFAULT_STATE
  const currentMock = mockMode

  const buildSession = useCallback(
    (): SessionState => ({
      version: 1,
      projectName,
      mockMode,
      time: Number((timeRef.current || 0).toFixed(3)),
      psd,
      profile,
      hiddenGroups: Array.from(hiddenGroups),
      hiddenLayers: Array.from(hiddenLayers),
      exclusiveGroups: Array.from(exclusiveGroups),
      selectedLayerId,
      svp,
      selectedTrack,
      mappingSetId,
      animationModeId,
      fps: timeline?.fps ?? TIMELINE_FPS,
      timelineView,
      audio,
      bpm,
      offset,
      sway,
      manifestStale: manifestStale && Boolean(manifest),
      updatedAt: null,
    }),
    [
      projectName,
      mockMode,
      psd,
      profile,
      hiddenGroups,
      hiddenLayers,
      exclusiveGroups,
      selectedLayerId,
      svp,
      selectedTrack,
      mappingSetId,
      animationModeId,
      timeline?.fps,
      timelineView,
      audio,
      bpm,
      offset,
      sway,
      manifestStale,
    ],
  )

  const persistSession = useCallback(
    async (snapshot: SessionState, keepalive = false): Promise<void> => {
      try {
        window.localStorage.setItem('mocadiff.session', JSON.stringify(snapshot))
      } catch {
        // localStorage may be full/unavailable; the backend is authoritative
      }
      try {
        await saveSession(snapshot, keepalive)
      } catch {
        // offline / backend unavailable: localStorage mirror still restores
      }
    },
    [],
  )

  useEffect(() => {
    durationRef.current = duration
  }, [duration])

  useEffect(() => {
    offsetRef.current = offset
  }, [offset])

  useEffect(() => {
    audioDurationRef.current = audio?.durationSec ?? 0
  }, [audio?.durationSec])

  const notify = useCallback((kind: ToastMessage['kind'], text: string) => {
    toastSeq.current += 1
    const id = toastSeq.current
    setToasts((current) => [...current, { id, kind, text }])
    window.setTimeout(
      () => setToasts((current) => current.filter((toast) => toast.id !== id)),
      kind === 'error' ? 7000 : 4200,
    )
  }, [])

  const describeError = useCallback((error: unknown): string => {
    if (error instanceof ApiError) {
      if (error.status === 404) return `接口 404：${error.message}`
      if (error.status === 0) return error.message
      return `${error.message}（HTTP ${error.status}）`
    }
    return error instanceof Error ? error.message : String(error)
  }, [])

  const reportError = useCallback(
    (context: string, error: unknown) => {
      const message = describeError(error)
      setStatusText(`${context}失败：${message}`)
      notify('error', `${context}失败：${message}`)
    },
    [describeError, notify],
  )

  // Mapping / visibility edits only invalidate the baked textures.  Keep the
  // previous manifest on screen so the preview never blanks out; the stale
  // flag blocks export and nudges the user to re-bake.
  const invalidateBake = useCallback(() => {
    setManifestStale(true)
    setBakeState({ status: 'idle' })
  }, [])

  // Layers referenced by semantic channels are driven by the animation and
  // cannot be toggled by hand; everything else stays freely switchable.
  const mappedIds = useMemo(() => {
    const ids = new Set<string>()
    if (profile) {
      for (const channel of Object.values(profile.channels) as Array<Record<string, string | null>>) {
        for (const value of Object.values(channel)) {
          if (value) ids.add(value)
        }
      }
    }
    return ids
  }, [profile])

  const layerIndex = useMemo(() => {
    const nodes = new Map<string, LayerNode>()
    const groups = new Map<string, LayerNode>()
    const walk = (node: LayerNode): void => {
      nodes.set(node.id, node)
      if (node.kind === 'group') groups.set(node.path, node)
      node.children.forEach(walk)
    }
    if (tree) walk(tree)
    return { nodes, groups }
  }, [tree])

  const hiddenStaticLayers = useMemo(() => {
    const hidden = new Set(hiddenLayers)
    for (const [id, layer] of Object.entries(manifest?.layers ?? {})) {
      for (const group of hiddenGroups) {
        if (layer.path === group || layer.path.startsWith(`${group}.`)) {
          hidden.add(id)
          break
        }
      }
    }
    return hidden
  }, [hiddenGroups, hiddenLayers, manifest])

  // Exclusive groups behave like radio buttons: showing one child hides its siblings.
  const applyExclusive = useCallback(
    (node: LayerNode, layers: Set<string>, groups: Set<string>) => {
      const separator = node.path.lastIndexOf('.')
      const parentPath = separator >= 0 ? node.path.slice(0, separator) : ''
      if (!exclusiveGroups.has(parentPath)) return
      for (const sibling of layerIndex.groups.get(parentPath)?.children ?? []) {
        if (sibling.id === node.id || (sibling.kind === 'pixel' && mappedIds.has(sibling.id))) continue
        if (sibling.kind === 'pixel') layers.add(sibling.id)
        else groups.add(sibling.path)
      }
    },
    [exclusiveGroups, layerIndex, mappedIds],
  )

  // One restore path shared by startup hydration and opening a saved project.
  const applyTokenRef = useRef(0)

  const applySession = useCallback(
    async (session: SessionState, note: string) => {
      const token = ++applyTokenRef.current
      const alive = (): boolean => applyTokenRef.current === token

      setPlaying(false)
      audioRef.current?.pause()

      const nextMock = Boolean(session.mockMode)
      setMockMode(nextMock)
      setMockEnabled(nextMock)
      try {
        window.localStorage.setItem('mocadiff.mock', nextMock ? '1' : '0')
      } catch {
        // storage unavailable
      }

      setProjectName(session.projectName || '未命名项目')
      setPsd(session.psd ?? null)
      setProfile(session.profile ?? null)
      setHiddenGroups(new Set(session.hiddenGroups ?? []))
      setHiddenLayers(new Set(session.hiddenLayers ?? []))
      setExclusiveGroups(new Set(session.exclusiveGroups ?? []))
      setSelectedLayerId(session.selectedLayerId ?? null)
      setSvp(session.svp ?? null)
      setSelectedTrack(session.selectedTrack ?? null)
      setMappingSetId(session.mappingSetId ?? session.profile?.defaultMappingSetId ?? 'standard')
      setAnimationModeId(session.animationModeId ?? 'natural')
      if (session.timelineView) {
        const span = clamp(session.timelineView.span, 0.002, 1)
        setTimelineView({
          start: clamp(session.timelineView.start, 0, 1 - span),
          span,
        })
      }
      setAudio(session.audio ?? null)
      setAudioUrl(session.audio?.assetId ? audioFileUrl(session.audio.assetId) : null)
      setBpm(session.bpm ?? null)
      setOffset(session.offset ?? 0)
      setSway(normalizeSway(session.sway))
      setBpmDirty(false)
      setDirty(false)

      // Drop derived state from whatever project was open before.
      setTree(null)
      setManifest(null)
      setManifestStale(false)
      setBakeState({ status: 'idle' })
      setTimeline(null)
      setBlinks([])
      setTimelineWarnings([])
      setPeaks(null)
      setGenerating(false)
      setStatusText('正在打开项目…')

      let restoredDuration = session.audio?.durationSec ?? 0

      if (session.psd?.assetId) {
        try {
          const [treeData, manifestData] = await Promise.all([
            getTree(session.psd.assetId),
            getManifest(session.psd.assetId),
          ])
          if (!alive()) return
          setTree(treeData)
          if (manifestData) {
            setManifest(manifestData)
            setManifestStale(Boolean(session.manifestStale))
            setBakeState({ status: 'done', manifest: manifestData })
          }
        } catch (error) {
          if (alive()) notify('error', `恢复 PSD 缓存失败：${describeError(error)}`)
        }
      }

      if (session.svp?.assetId && session.selectedTrack != null) {
        try {
          const result = await generateTimeline(
            session.svp.assetId,
            session.selectedTrack,
            session.fps || 60,
            {
              psdAssetId: session.psd?.assetId,
              mappingSetId: session.mappingSetId ?? session.profile?.defaultMappingSetId ?? 'standard',
              animationModeId: session.animationModeId ?? 'natural',
            },
          )
          if (!alive()) return
          setTimeline(result.timeline)
          setBlinks(result.blinks)
          setTimelineWarnings(result.warnings ?? [])
          if (result.timeline.duration > 0) restoredDuration = result.timeline.duration
        } catch (error) {
          if (alive()) notify('error', `恢复口型时间轴失败：${describeError(error)}`)
        }
      }

      if (session.audio?.assetId) {
        try {
          const peaksData = await getPeaks(session.audio.assetId, 1200)
          if (alive()) setPeaks(peaksData.peaks)
        } catch (error) {
          if (alive()) notify('error', `恢复音频波形失败：${describeError(error)}`)
        }
      }

      if (!alive()) return
      const restoredTime =
        restoredDuration > 0 ? Math.min(session.time || 0, restoredDuration) : session.time || 0
      setTime(restoredTime)
      timeRef.current = restoredTime
      setStatusText(note)
      setSessionReady(true)
    },
    [describeError, notify],
  )

  // Project history: every autosave upserts an entry; opening one replays the
  // same restore path as startup.
  const refreshProjects = useCallback(async () => {
    setProjectsLoading(true)
    setProjectsError(null)
    try {
      setProjects(await listProjects())
    } catch (error) {
      setProjectsError(describeError(error))
    } finally {
      setProjectsLoading(false)
    }
  }, [describeError])

  const openProjectsPanel = useCallback(() => {
    setProjectsOpen(true)
    void refreshProjects()
  }, [refreshProjects])

  const handleOpenProject = useCallback(
    async (projectId: string) => {
      setProjectsLoading(true)
      try {
        const result = await loadProject(projectId)
        if (!result.session) throw new Error('该项目快照为空')
        const label = result.session.projectName || '未命名项目'
        setProjectsOpen(false)
        await applySession(result.session, `已打开项目：${label}`)
        notify('success', `已打开项目：${label}`)
      } catch (error) {
        notify('error', `打开项目失败：${describeError(error)}`)
      } finally {
        setProjectsLoading(false)
      }
    },
    [applySession, describeError, notify],
  )

  const handleDeleteProject = useCallback(
    async (projectId: string) => {
      try {
        await deleteProject(projectId)
        setProjects((prev) => prev.filter((item) => item.id !== projectId))
        notify('info', '已删除该项目的历史记录')
      } catch (error) {
        notify('error', `删除项目失败：${describeError(error)}`)
      }
    },
    [describeError, notify],
  )

  // initial data-source detection + restore the last backend session ----------
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const probe = await probeHealth()
      if (cancelled) return
      setHealth(probe)

      const savedMock = window.localStorage.getItem('mocadiff.mock')
      let nextMock = savedMock === null ? !probe.online : savedMock === '1'

      // A switch between LIVE and MOCK stores the snapshot for the target
      // mode and reloads with this marker.  It takes precedence over the
      // backend session, so both modes keep their own last project.
      let pending: SessionState | null = null
      try {
        const raw = window.localStorage.getItem('mocadiff.pendingRestore')
        if (raw) {
          window.localStorage.removeItem('mocadiff.pendingRestore')
          const parsed = JSON.parse(raw) as SessionState
          if (parsed && typeof parsed === 'object' && parsed.version === 1) pending = parsed
        }
      } catch {
        // corrupt pending snapshot: ignore
      }

      // Backend session is authoritative; localStorage is an offline mirror.
      let session: SessionState | null = pending
      if (!session && probe.online) {
        try {
          session = (await loadSession()).session
        } catch {
          // ignore, fall back to the mirror below
        }
      }
      if (!session) {
        try {
          const raw = window.localStorage.getItem('mocadiff.session')
          if (raw) {
            const parsed = JSON.parse(raw) as SessionState
            if (parsed && typeof parsed === 'object' && parsed.version === 1) session = parsed
          }
        } catch {
          // corrupt mirror: ignore
        }
      }

      if (pending) nextMock = Boolean(pending.mockMode)

      // If the current snapshot has no project (e.g. the user switched
      // LIVE <-> MOCK and the reset empty state was saved), recover the last
      // real project from the backend's previous-session slot.
      const sessionHasProject = (value: SessionState | null): boolean =>
        Boolean(value && (value.psd || value.svp || value.audio))
      let restoredPrevious = Boolean(pending && sessionHasProject(pending))
      if ((!pending || !pending.mockMode) && (!session || !sessionHasProject(session)) && probe.online) {
        try {
          const previous = (await loadPreviousSession()).session
          if (previous && sessionHasProject(previous)) {
            session = previous
            restoredPrevious = true
          }
        } catch {
          // ignore: normal empty workspace
        }
      }

      if (!session) {
        setMockMode(nextMock)
        setMockEnabled(nextMock)
        setStatusText(
          nextMock
            ? probe.online
              ? '就绪 · 后端在线，当前使用 Mock 数据源（顶栏可切换）'
              : '就绪 · 后端离线，使用内置 Mock 数据源（顶栏可切换）'
            : '就绪 · 已连接真实后端',
        )
        if (!cancelled) setSessionReady(true)
        return
      }

      if (cancelled) return
      await applySession(
        session,
        restoredPrevious
          ? '已恢复切换数据源前的项目 · 可继续编辑'
          : '已恢复上次会话 · 刷新前的工作区已还原',
      )
      if (cancelled) return
      if (restoredPrevious) {
        notify('info', '检测到切换数据源时被重置的项目，已自动恢复上次项目。')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [applySession, notify])

  // Auto-save the session after meaningful edits (not every playback frame).
  useEffect(() => {
    if (!sessionReady) return
    const timer = window.setTimeout(() => {
      void persistSession(buildSession())
    }, 700)
    return () => window.clearTimeout(timer)
  }, [sessionReady, buildSession, persistSession])

  // Save when playback pauses so the last viewed time is kept.
  useEffect(() => {
    if (!sessionReady || playing) return
    void persistSession(buildSession())
  }, [sessionReady, playing, buildSession, persistSession])

  // Last-chance save when the tab is hidden/closed, including the current time.
  useEffect(() => {
    if (!sessionReady) return
    const flush = (): void => {
      const snapshot = buildSession()
      try {
        window.localStorage.setItem('mocadiff.session', JSON.stringify(snapshot))
      } catch {
        // ignore
      }
      void saveSession(snapshot, true).catch(() => {
        // backend offline: the localStorage mirror is enough
      })
    }
    const onVisibility = (): void => {
      if (document.visibilityState === 'hidden') flush()
    }
    window.addEventListener('pagehide', flush)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('pagehide', flush)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [sessionReady, buildSession])

  const resetWorkspace = useCallback(() => {
    setPlaying(false)
    audioRef.current?.pause()
    setTime(0)
    timeRef.current = 0
    setPsd(null)
    setTree(null)
    setProfile(null)
    setDirty(false)
    setAutomapWarnings([])
    setBakeState({ status: 'idle' })
    setManifest(null)
    setManifestStale(false)
    setHiddenGroups(new Set())
    setHiddenLayers(new Set())
    setExclusiveGroups(new Set())
    setSelectedLayerId(null)
    setSvp(null)
    setSelectedTrack(null)
    setGenerating(false)
    setTimeline(null)
    setBlinks([])
    setTimelineWarnings([])
    setAudio(null)
    setAudioUrl(null)
    setPeaks(null)
    setBpm(null)
    setOffset(0)
    setSway(DEFAULT_SWAY)
    setBpmDirty(false)
  }, [])

  const toggleMock = useCallback(async () => {
    const next = !mockMode
    const currentSlot = mockMode ? 'mock' : 'live'
    const targetSlot = next ? 'mock' : 'live'
    const snapshot = buildSession()
    const empty: SessionState = {
      version: 1,
      projectName: '未命名项目',
      mockMode: next,
      time: 0,
      psd: null,
      profile: null,
      hiddenGroups: [],
      hiddenLayers: [],
      exclusiveGroups: [],
      selectedLayerId: null,
      svp: null,
      selectedTrack: null,
      fps: 60,
      audio: null,
      bpm: null,
      offset: 0,
      sway: DEFAULT_SWAY,
    }
    try {
      window.localStorage.setItem(`mocadiff.session.${currentSlot}`, JSON.stringify(snapshot))
      const targetRaw = window.localStorage.getItem(`mocadiff.session.${targetSlot}`)
      const target = targetRaw ? (JSON.parse(targetRaw) as SessionState) : empty
      window.localStorage.setItem('mocadiff.pendingRestore', JSON.stringify(target))
      window.localStorage.setItem('mocadiff.mock', next ? '1' : '0')
    } catch {
      // storage unavailable: fall back to a plain reset
    }

    // Keep the LIVE snapshot in the backend as well; the mock reset will
    // overwrite it, but the backend keeps a previous-session backup.
    if (!mockMode) {
      try {
        await saveSession(snapshot)
      } catch {
        // backend offline: localStorage snapshot is enough
      }
    }

    setMockMode(next)
    setMockEnabled(next)
    setStatusText(next ? '正在切换到 Mock 数据源…' : '正在恢复到真实后端项目…')

    const canReload =
      typeof window !== 'undefined' && !window.navigator.userAgent.toLowerCase().includes('jsdom')
    if (canReload) {
      window.location.reload()
      return
    }

    // jsdom smoke: no navigation available, just reset in place.
    try {
      window.localStorage.removeItem('mocadiff.pendingRestore')
    } catch {
      // ignore
    }
    resetWorkspace()
    void probeHealth().then(setHealth)
    notify(
      'info',
      next
        ? '已切换到内置 Mock 数据源，当前素材已重置'
        : '已切换到真实后端（127.0.0.1:8787），当前素材已重置',
    )
  }, [buildSession, mockMode, notify, resetWorkspace])

  const handleNewProject = useCallback(() => {
    resetWorkspace()
    setProjectName('未命名项目')
    setStatusText('新建工作区 · 导入 PSD 开始')
    notify('info', '已新建工作区')
  }, [notify, resetWorkspace])

  // PSD flows ---------------------------------------------------------------
  const handlePsdFile = useCallback(
    async (file: File) => {
      if (!isPsdFile(file)) {
        notify('error', '请选择 .psd 文件')
        return
      }
      setBusy('上传 PSD…')
      setStatusText(`上传 PSD：${file.name}`)
      try {
        const info = await uploadPsd(file)
        setPsd(info)
        setTree(null)
        setProfile(null)
        setDirty(false)
        setAutomapWarnings([])
        setManifest(null)
        setManifestStale(false)
        setBakeState({ status: 'idle' })
        setHiddenGroups(new Set())
        setHiddenLayers(new Set())
        setSelectedLayerId(null)
        setStatusText(`PSD 已上传：${info.filename} · ${info.width}×${info.height} · ${info.layerCount} 图层`)
        notify('success', `PSD 已上传（${info.layerCount} 图层 / ${info.groupCount} 组）`)
        const root = await getTree(info.assetId)
        setTree(root)
        setStatusText(`图层树已加载 · 点击「自动识别」生成语义映射`)
      } catch (error) {
        reportError('PSD 上传', error)
      } finally {
        setBusy(null)
      }
    },
    [notify, reportError],
  )

  const handleAutomap = useCallback(async () => {
    if (!psd) {
      notify('error', '请先导入 PSD')
      return
    }
    setBusyAutomap(true)
    setStatusText('自动识别语义图层…')
    try {
      const result = await automap(psd.assetId)
      const slots = (Object.values(result.profile.channels) as Array<Record<string, string | null>>).reduce(
        (sum, channel) => sum + Object.values(channel).filter(Boolean).length,
        0,
      )
      setProfile(result.profile)
      setMappingSetId(result.profile.defaultMappingSetId ?? 'standard')
      setAutomapWarnings(result.warnings)
      setHiddenGroups(new Set(result.profile.base.hiddenGroups))
      setHiddenLayers(new Set(result.profile.base.hiddenLayers))
      invalidateBake()
      setDirty(true)
      setStatusText(`自动识别完成 · 已填充 ${slots} 个槽位，请确认后保存`)
      notify('success', `自动识别完成，填充 ${slots} 个语义槽位`)
    } catch (error) {
      reportError('自动识别', error)
    } finally {
      setBusyAutomap(false)
    }
  }, [notify, psd, reportError])

  const updateSlot = useCallback((channel: ChannelName, slot: string, layerId: string) => {
    setProfile((current) => {
      if (!current) return current
      const channels = { ...current.channels }
      const values = { ...(channels[channel] as Record<string, string | null>) }
      values[slot] = layerId || null
      channels[channel] = values as never
      const mappingSets = current.mappingSets
        ? {
            ...current.mappingSets,
            [mappingSetId]: {
              ...(current.mappingSets[mappingSetId] ?? { label: mappingSetId, channels }),
              channels,
            },
          }
        : current.mappingSets
      return { ...current, channels, mappingSets }
    })
    invalidateBake()
    setDirty(true)
  }, [invalidateBake, mappingSetId])

  const handleMappingSetChange = useCallback((value: string) => {
    setProfile((current) => {
      const mappingSet = current?.mappingSets?.[value]
      if (!current || !mappingSet) return current
      return {
        ...current,
        channels: mappingSet.channels,
        defaultMappingSetId: value,
      }
    })
    setMappingSetId(value)
    invalidateBake()
    setDirty(true)
    setTimeline(null)
    setBlinks([])
    setTimelineWarnings([])
  }, [invalidateBake])

  const updateDefaultState = useCallback((channel: ChannelName, value: string) => {
    setProfile((current) =>
      current
        ? { ...current, base: { ...current.base, defaultState: { ...current.base.defaultState, [channel]: value } } }
        : current,
    )
    invalidateBake()
    setDirty(true)
  }, [invalidateBake])

  const toggleGroupVisibility = useCallback(
    (path: string) => {
      const turningOn = hiddenGroups.has(path)
      const nextGroups = new Set(hiddenGroups)
      const nextLayers = new Set(hiddenLayers)
      if (turningOn) nextGroups.delete(path)
      else nextGroups.add(path)
      const node = layerIndex.groups.get(path)
      if (turningOn && node) applyExclusive(node, nextLayers, nextGroups)
      setHiddenGroups(nextGroups)
      setHiddenLayers(nextLayers)
      setProfile((current) =>
        current
          ? {
              ...current,
              base: { ...current.base, hiddenGroups: [...nextGroups], hiddenLayers: [...nextLayers] },
            }
          : current,
      )
      setDirty(true)
    },
    [applyExclusive, hiddenGroups, hiddenLayers, layerIndex],
  )

  const toggleLayerVisibility = useCallback(
    (id: string) => {
      if (mappedIds.has(id)) return
      const turningOn = hiddenLayers.has(id)
      const nextLayers = new Set(hiddenLayers)
      const nextGroups = new Set(hiddenGroups)
      if (turningOn) nextLayers.delete(id)
      else nextLayers.add(id)
      const node = layerIndex.nodes.get(id)
      if (turningOn && node) applyExclusive(node, nextLayers, nextGroups)
      setHiddenLayers(nextLayers)
      setHiddenGroups(nextGroups)
      setProfile((current) =>
        current
          ? {
              ...current,
              base: { ...current.base, hiddenGroups: [...nextGroups], hiddenLayers: [...nextLayers] },
            }
          : current,
      )
      setDirty(true)
    },
    [applyExclusive, hiddenGroups, hiddenLayers, layerIndex, mappedIds],
  )

  const toggleExclusiveGroup = useCallback((path: string) => {
    setExclusiveGroups((current) => {
      const next = new Set(current)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  const handleSaveProfile = useCallback(async () => {
    if (!psd || !profile) return
    setSaving(true)
    setStatusText('保存映射（PUT /api/psd/{assetId}/profile）…')
    try {
      await saveProfile(psd.assetId, profile)
      setDirty(false)
      setStatusText('映射已保存 · 可开始烘焙')
      notify('success', '映射已保存')
    } catch (error) {
      reportError('保存映射', error)
    } finally {
      setSaving(false)
    }
  }, [notify, profile, psd, reportError])

  const handleBake = useCallback(async () => {
    if (!psd || !profile) {
      notify('error', '请先导入 PSD 并完成自动识别')
      return
    }
    setBakeState({ status: 'loading', startedAt: Date.now() })
    setStatusText('烘焙中：合成 base + patch，首次约 10–30s…')
    try {
      if (dirty) {
        await saveProfile(psd.assetId, profile)
        setDirty(false)
      }
      const started = performance.now()
      const result = await bake(psd.assetId, profile)
      setManifest(result)
      setManifestStale(false)
      const defaultHidden = Object.entries(result.layers ?? {})
        .filter(([, layer]) => layer.visible === false)
        .map(([id]) => id)
      if (defaultHidden.length > 0) {
        setHiddenLayers((current) => new Set([...current, ...defaultHidden]))
      }
      setBakeState({ status: 'done', manifest: result })
      setStatusText(
        `烘焙完成 · ${(performance.now() - started).toFixed(1)}s · ${Object.keys(result.patches).length} patches`,
      )
      notify('success', `烘焙完成（${Object.keys(result.patches).length} 个 patch）`)
    } catch (error) {
      setBakeState({ status: 'error', error: describeError(error) })
      reportError('烘焙', error)
    }
  }, [describeError, dirty, notify, profile, psd, reportError])

  // SVP flows ---------------------------------------------------------------
  const handleSvpFile = useCallback(
    async (file: File) => {
      if (!isSvpFile(file)) {
        notify('error', '请选择 .svp 文件')
        return
      }
      setBusy('上传 SVP…')
      setStatusText(`上传 SVP：${file.name}`)
      try {
        const info = await uploadSvp(file)
        setSvp(info)
        setSelectedTrack(null)
        setTimeline(null)
        setBlinks([])
        setTimelineWarnings([])
        setStatusText(`SVP 已上传 · ${info.tracks.length} 条轨道，请选择一条人声轨`)
        notify('success', `SVP 已上传（${info.tracks.length} 条轨道）`)
      } catch (error) {
        reportError('SVP 上传', error)
      } finally {
        setBusy(null)
      }
    },
    [notify, reportError],
  )

  const handleGenerateTimeline = useCallback(async () => {
    if (!svp) {
      notify('error', '请先导入 SVP')
      return
    }
    if (selectedTrack == null) {
      notify('error', '请先选择一条轨道（单轨必选）')
      return
    }
    setGenerating(true)
    setStatusText(`生成时间轴 · 轨道 #${selectedTrack}…`)
    try {
      const result = await generateTimeline(svp.assetId, selectedTrack, TIMELINE_FPS, {
        psdAssetId: psd?.assetId,
        mappingSetId,
        animationModeId,
      })
      setTimeline(result.timeline)
      setBlinks(result.blinks)
      setTimelineWarnings(result.warnings ?? [])
      setPlaying(false)
      setTime(0)
      timeRef.current = 0
      setStatusText(
        `时间轴已生成 · ${result.timeline.frames.length} 帧 · ${formatDuration(result.timeline.duration)} · ${result.blinks.length} 次眨眼`,
      )
      notify('success', `时间轴已生成（${result.timeline.frames.length} 帧 / ${result.blinks.length} 眨眼）`)
    } catch (error) {
      reportError('生成时间轴', error)
    } finally {
      setGenerating(false)
    }
  }, [animationModeId, mappingSetId, notify, psd?.assetId, reportError, selectedTrack, svp])

  // audio flows -------------------------------------------------------------
  const handleAudioFile = useCallback(
    async (file: File) => {
      if (!isAudioFile(file)) {
        notify('error', '请选择音频文件（wav / mp3 / flac / m4a）')
        return
      }
      setBusy('上传音频…')
      setStatusText(`上传音频：${file.name}`)
      setPlaying(false)
      try {
        const info = await uploadAudio(file)
        setAudio(info)
        setBpm(info.bpm ?? null)
        setOffset(info.offsetSec ?? 0)
        setBpmDirty(false)
        const url = audioFileUrl(info.assetId)
        setAudioUrl(url || null)
        setStatusText(`音频已上传：${info.filename} · ${formatDuration(info.durationSec)}`)
        notify('success', `音频已上传（${formatDuration(info.durationSec)}）`)
        if (isMockEnabled()) {
          notify(
            'info',
            '当前是 MOCK 模式：播放的是内置合成节拍（会听到 440Hz 哔声），上传的文件没有被播放；点顶栏 MOCK/LIVE 切到 LIVE。',
          )
        }
        try {
          const peakResult = await getPeaks(info.assetId, 1600)
          setPeaks(peakResult.peaks)
        } catch (error) {
          notify('error', `波形加载失败：${describeError(error)}`)
        }
      } catch (error) {
        reportError('音频上传', error)
      } finally {
        setBusy(null)
      }
    },
    [describeError, notify, reportError],
  )

  const handleAudioStart = useCallback((value: number) => {
    setOffset(Math.round(value * 1000) / 1000)
    setBpmDirty(true)
  }, [])

  const handleTimelineView = useCallback((next: { start: number; span: number }) => {
    setTimelineView(() => {
      const span = clamp(next.span, 0.002, 1)
      const start = clamp(next.start, 0, 1 - span)
      return { start, span }
    })
  }, [])

  const zoomTimeline = useCallback((factor: number) => {
    setTimelineView((current) => {
      const span = clamp(current.span * factor, 0.002, 1)
      const center = current.start + current.span / 2
      const start = clamp(center - span / 2, 0, 1 - span)
      return { start, span }
    })
  }, [])

  const resetTimelineView = useCallback(() => setTimelineView({ start: 0, span: 1 }), [])

  // Reset the zoom window when the timeline/audio source changes.
  useEffect(() => {
    setTimelineView({ start: 0, span: 1 })
  }, [audio?.assetId, timeline?.source.assetId, timeline?.source.trackIndex])

  // Keep a zoomed view following the playhead while playing.
  useEffect(() => {
    if (!playing || timelineView.span >= 0.999 || duration <= 0) return
    const fraction = time / duration
    const edge = timelineView.start + timelineView.span
    if (fraction >= timelineView.start && fraction <= edge) return
    const start = clamp(fraction - timelineView.span * 0.25, 0, 1 - timelineView.span)
    setTimelineView({ start, span: timelineView.span })
  }, [duration, playing, time, timelineView])

  const handleSaveBpm = useCallback(async () => {
    if (!audio || bpm == null) {
      notify('error', '请先导入音频并填写 BPM')
      return
    }
    setSavingBpm(true)
    try {
      await saveBpm(audio.assetId, bpm, offset)
      setBpmDirty(false)
      setStatusText(`BPM 已保存：${bpm} · 音频起点 ${offset >= 0 ? '+' : ''}${offset.toFixed(2)}s`)
      notify('success', 'BPM / 音频位置已保存')
    } catch (error) {
      reportError('保存 BPM', error)
    } finally {
      setSavingBpm(false)
    }
  }, [audio, bpm, notify, offset, reportError])

  // playback ----------------------------------------------------------------
  const togglePlay = useCallback(() => {
    if (duration <= 0) {
      notify('info', '先生成时间轴或导入音频，再开始播放')
      return
    }
    setPlaying((current) => {
      if (current) audioRef.current?.pause()
      return !current
    })
  }, [duration, notify])

  const seek = useCallback(
    (nextTime: number) => {
      const clamped = clamp(nextTime, 0, durationRef.current)
      timeRef.current = clamped
      clockBaseRef.current = { perf: performance.now(), time: clamped }
      setTime(clamped)
      const audioElement = audioRef.current
      if (audioElement && audioUrl) {
        const audioTime = clamped - offsetRef.current
        try {
          audioElement.currentTime = clamp(audioTime, 0, Math.max(0, audioDurationRef.current))
        } catch {
          /* metadata not ready yet */
        }
      }
    },
    [audioUrl],
  )

  useEffect(() => {
    const audioElement = audioRef.current
    if (!audioElement || !audioUrl) return
    const syncPosition = (): void => {
      const audioTime = timeRef.current - offsetRef.current
      try {
        audioElement.currentTime = clamp(audioTime, 0, Math.max(0, audioDurationRef.current))
      } catch {
        /* metadata not ready yet */
      }
    }
    audioElement.addEventListener('loadedmetadata', syncPosition)
    syncPosition()
    return () => {
      audioElement.removeEventListener('loadedmetadata', syncPosition)
    }
  }, [audioUrl, offset])

  useEffect(() => {
    if (!playing) return
    const audioElement = audioRef.current
    const audioDuration = audioDurationRef.current
    let raf = 0
    let lastPerf = performance.now()
    let playPending = false
    let audioActive = false
    let lastResumeAttempt = 0

    const isAudioActive = (t: number): boolean =>
      Boolean(
        audioElement &&
          audioUrl &&
          audioDuration > 0 &&
          t >= offsetRef.current &&
          t < offsetRef.current + audioDuration,
      )

    const startAudio = (t: number): void => {
      if (!audioElement || !audioUrl) return
      try {
        audioElement.currentTime = Math.max(0, t - offsetRef.current)
      } catch {
        /* ignore */
      }
      if (audioElement.paused && !playPending) {
        playPending = true
        void audioElement
          .play()
          .catch(() => {
            notify('error', '浏览器阻止了音频播放，请再次点击播放')
          })
          .finally(() => {
            playPending = false
          })
      }
    }

    audioActive = isAudioActive(timeRef.current)
    if (audioActive) startAudio(timeRef.current)

    const tick = (): void => {
      const now = performance.now()
      const dt = Math.max(0, (now - lastPerf) / 1000)
      lastPerf = now
      const current = timeRef.current
      const active = isAudioActive(current)

      // Only touch the media element on activation/deactivation transitions;
      // writing currentTime every frame makes some browsers glitch audibly.
      if (active !== audioActive) {
        if (active) {
          startAudio(current)
        } else if (audioElement && !audioElement.paused) {
          audioElement.pause()
        }
        audioActive = active
      } else if (
        active &&
        audioElement &&
        audioElement.paused &&
        !playPending &&
        now - lastResumeAttempt > 500
      ) {
        lastResumeAttempt = now
        playPending = true
        void audioElement.play().catch(() => {}).finally(() => {
          playPending = false
        })
      }

      let next: number
      if (active && audioElement && !audioElement.paused) {
        next = Math.max(0, audioElement.currentTime + offsetRef.current)
      } else {
        next = current + dt
      }

      const max = durationRef.current
      if (max > 0 && next >= max) {
        timeRef.current = max
        setTime(max)
        setPlaying(false)
        audioElement?.pause()
        return
      }
      timeRef.current = next
      setTime(next)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      audioElement?.pause()
    }
  }, [audio?.durationSec, audioUrl, notify, offset, playing])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      if (event.code === 'Space') {
        event.preventDefault()
        togglePlay()
      } else if (event.code === 'ArrowRight') {
        event.preventDefault()
        seek(timeRef.current + (event.shiftKey ? 5 : 1))
      } else if (event.code === 'ArrowLeft') {
        event.preventDefault()
        seek(timeRef.current - (event.shiftKey ? 5 : 1))
      } else if (event.code === 'Home') {
        event.preventDefault()
        seek(0)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [seek, togglePlay])

  // derived stage state -----------------------------------------------------
  const stageState = useMemo<StageState>(
    () => {
      const channels = Object.fromEntries(
        Object.entries(timeline?.tracks ?? {})
          .filter(([channel]) => !['mouth', 'blink'].includes(channel))
          .map(([channel, events]) => [channel, eventStateAt(events, time)])
          .filter((entry): entry is [string, string] => Boolean(entry[1])),
      )
      return {
        viseme: (timeline ? visemeAt(timeline.frames, time, defaultState.mouth as Viseme) : defaultState.mouth) as Viseme,
        mouthPose: timeline ? mouthPoseAt(timeline.frames, time) : undefined,
        blink: isBlinkActive(blinks, time),
        brow: channels.brow ?? defaultState.brow,
        cheek: channels.cheek ?? defaultState.cheek,
        openness: timeline ? opennessAt(timeline.frames, time) : 0,
        channels,
      }
    },
    [blinks, defaultState, time, timeline],
  )

  const thumbFor = useCallback(
    (node: LayerNode): string | null => {
      if (node.kind !== 'pixel') return null
      if (currentMock) return mockThumb(node.id, 40)
      if (!psd) return null
      return layerThumbUrl(psd.assetId, node.id, 40)
    },
    [currentMock, psd],
  )

  const handleSelectLayer = useCallback(
    (node: LayerNode) => {
      setSelectedLayerId(node.id)
      setStatusText(`已选图层：${node.name} · #${node.id} · ${node.width}×${node.height}`)
    },
    [],
  )

  const handleExport = useCallback(() => {
    setExportOpen(true)
  }, [])

  const openPsdPicker = useCallback(() => psdInputRef.current?.click(), [])
  const openSvpPicker = useCallback(() => svpInputRef.current?.click(), [])
  const openAudioPicker = useCallback(() => audioInputRef.current?.click(), [])

  const inputHandlers = {
    psd: (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      event.target.value = ''
      if (file) void handlePsdFile(file)
    },
    svp: (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      event.target.value = ''
      if (file) void handleSvpFile(file)
    },
    audio: (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0]
      event.target.value = ''
      if (file) void handleAudioFile(file)
    },
  }

  const rightDuration = duration

  return (
    <div className="app-shell" style={layoutStyle}>
      <TopBar
        projectName={projectName}
        onProjectName={setProjectName}
        onNewProject={handleNewProject}
        onOpenProjects={openProjectsPanel}
        onImportPsd={openPsdPicker}
        onImportSvp={openSvpPicker}
        onImportAudio={openAudioPicker}
        onExport={handleExport}
        mockMode={mockMode}
        onToggleMock={toggleMock}
        health={health}
        busyLabel={busy}
        loaded={{ psd: Boolean(psd), svp: Boolean(svp), audio: Boolean(audio) }}
      />

      <div className="workspace">
        <aside className="left-panel">
          <section className="panel asset-panel">
            <div className="panel-head">
              <span className="panel-title">
                <IconImage size={14} />
                PSD 素材
              </span>
              {psd ? (
                <button className="mini-btn" onClick={openPsdPicker} title="替换 PSD">
                  替换
                </button>
              ) : null}
            </div>
            {psd ? (
              <div className="asset-card">
                <div className="asset-thumb">
                  <IconImage size={20} />
                </div>
                <div className="asset-info">
                  <strong title={psd.filename}>{psd.filename}</strong>
                  <span>
                    {psd.width}×{psd.height} · {psd.layerCount} 图层 / {psd.groupCount} 组
                  </span>
                  <span className="asset-status">
                    {manifest
                      ? `烘焙就绪 · ${Object.keys(manifest.patches).length} patches`
                      : tree
                        ? '图层树已加载'
                        : '加载图层树…'}
                  </span>
                </div>
              </div>
            ) : (
              <div className="panel-empty compact">
                <p>导入 moca.psd，自动识别口型 / 眼睛 / 眉毛 / 脸颊图层并烘焙预览。</p>
                <button className="btn primary" onClick={openPsdPicker}>
                  导入 PSD
                </button>
              </div>
            )}
          </section>

          <section className="panel layer-panel">
            <div className="panel-head">
              <span className="panel-title">
                <IconLayers size={14} />
                图层树
              </span>
              {selectedLayerId ? <span className="panel-badge">#{selectedLayerId}</span> : null}
            </div>
            <LayerTree
              root={tree}
              thumbFor={thumbFor}
              mappedIds={mappedIds}
              hiddenGroups={hiddenGroups}
              hiddenLayers={hiddenLayers}
              exclusiveGroups={exclusiveGroups}
              selectedId={selectedLayerId}
              onSelect={handleSelectLayer}
              onToggleGroup={toggleGroupVisibility}
              onToggleLayer={toggleLayerVisibility}
              onToggleExclusive={toggleExclusiveGroup}
            />
          </section>

          <MappingPanel
            profile={profile}
            tree={tree}
            warnings={automapWarnings}
            dirty={dirty}
            saving={saving}
            busyAutomap={busyAutomap}
            bake={bakeState}
            stale={manifestStale && Boolean(manifest)}
            onAutomap={() => void handleAutomap()}
            onSave={() => void handleSaveProfile()}
            onBake={() => void handleBake()}
            onImportPsd={openPsdPicker}
            onSlotChange={updateSlot}
            onDefaultChange={updateDefaultState}
          />
        </aside>

        <div
          className="split-handle split-vertical"
          onPointerDown={startResize('left')}
          role="separator"
          aria-orientation="vertical"
          aria-label="调整左栏宽度"
          title="拖动调整左栏宽度"
        />

        <main className="stage-column">
          <Stage
            manifest={manifest}
            defaultState={defaultState}
            state={stageState}
            time={time}
            duration={duration}
            fps={fps}
            bpm={bpm}
            sway={sway}
            audioStart={offset}
            playing={playing}
            canPlay={duration > 0}
            onTogglePlay={togglePlay}
            onSeek={seek}
            stale={manifestStale && Boolean(manifest)}
            hiddenLayers={hiddenStaticLayers}
            loading={bakeState.status === 'loading'}
            loadingLabel="烘焙中"
            onImportPsd={openPsdPicker}
          />
        </main>

        <div
          className="split-handle split-vertical"
          onPointerDown={startResize('right')}
          role="separator"
          aria-orientation="vertical"
          aria-label="调整右栏宽度"
          title="拖动调整右栏宽度"
        />

        <aside className="right-panel">
          <SvpPanel
            svp={svp}
            selectedTrack={selectedTrack}
            onSelectTrack={setSelectedTrack}
            onGenerate={() => void handleGenerateTimeline()}
            generating={generating}
            onImport={openSvpPicker}
            hasTimeline={Boolean(timeline)}
            timelineFrames={timeline?.frames.length ?? 0}
            timelineDuration={timeline?.duration ?? 0}
            blinksCount={blinks.length}
            warnings={timelineWarnings}
            mappingSetId={mappingSetId}
            mappingSets={Object.entries(profile?.mappingSets ?? { standard: { label: '标准', channels: profile?.channels } }).map(
              ([id, item]) => ({ id, label: item.label }),
            )}
            animationModeId={animationModeId}
            onMappingSetChange={handleMappingSetChange}
            onAnimationModeChange={setAnimationModeId}
          />

          <AudioPanel
            audio={audio}
            audioUrl={audioUrl}
            mockMode={mockMode}
            peaks={peaks}
            time={time}
            duration={duration}
            bpm={bpm}
            offset={offset}
            sway={sway}
            onBpm={(value) => {
              setBpm(value)
              setBpmDirty(true)
            }}
            onOffset={(value) => {
              setOffset(value)
              setBpmDirty(true)
            }}
            onSway={(value) => setSway(normalizeSway(value))}
            onSaveBpm={() => void handleSaveBpm()}
            savingBpm={savingBpm}
            bpmDirty={bpmDirty}
            onImport={openAudioPicker}
          />

          <StatePanel
            state={stageState}
            time={time}
            duration={duration}
            fps={fps}
            playing={playing}
            frameCount={timeline?.frames.length ?? 0}
            blinkCount={blinks.length}
            hasAudio={Boolean(audio)}
            hasTimeline={Boolean(timeline)}
          />
        </aside>
      </div>

      <div
        className="split-handle split-horizontal"
        onPointerDown={startResize('timeline')}
        role="separator"
        aria-orientation="horizontal"
        aria-label="调整时间轴高度"
        title="拖动调整时间轴高度"
      />

      <section className="timeline-dock">
        <section className="panel timeline-panel">
          <div className="panel-head">
            <span className="panel-title">
              <IconClock size={14} />
              时间轴
            </span>
            <span className="timeline-mode" title="动画模式 · 素材方案">
              {timeline?.mode?.animationModeId ?? 'classic'} · {timeline?.mode?.mappingSetId ?? 'standard'}
            </span>
            <div className="timeline-head-actions">
              <button className="icon-btn small" onClick={togglePlay} disabled={duration <= 0} title="播放 / 暂停（空格）">
                {playing ? <IconPause size={14} /> : <IconPlay size={14} />}
              </button>
              <span className="timecode small">{formatTimecode(time, true, fps)}</span>
              <span className="hud-muted">/ {formatTimecode(rightDuration, false)}</span>
              <span className="zoom-chip" title="当前时间轴缩放">
                {Math.round(100 / timelineView.span)}%
              </span>
              <button
                className="icon-btn small"
                onClick={() => zoomTimeline(1 / 1.6)}
                disabled={duration <= 0 || timelineView.span <= 0.0021}
                title="放大时间轴（+）"
              >
                +
              </button>
              <button
                className="icon-btn small"
                onClick={() => zoomTimeline(1.6)}
                disabled={duration <= 0 || timelineView.span >= 0.999}
                title="缩小时间轴（−）"
              >
                −
              </button>
              <div className="segmented density-switch" role="group" aria-label="轨道高度">
                {DENSITIES.map((value) => (
                  <button
                    key={value}
                    className={timelineDensity === value ? 'active' : ''}
                    onClick={() => setTimelineDensity(value)}
                    title={`轨道高度：${{ compact: '紧凑', normal: '标准', expanded: '展开' }[value]}`}
                  >
                    {{ compact: '紧凑', normal: '标准', expanded: '展开' }[value]}
                  </button>
                ))}
              </div>
              <button
                className="mini-btn"
                onClick={resetTimelineView}
                disabled={timelineView.span >= 0.999 && timelineView.start <= 0.0001}
                title="显示完整时间轴"
              >
                全览
              </button>
            </div>
          </div>
          <MultiTrackTimeline
            timeline={timeline}
            blinks={blinks}
            peaks={peaks}
            duration={duration}
            time={time}
            bpm={bpm}
            audioStart={offset}
            audioDuration={audio?.durationSec ?? 0}
            sway={sway}
            density={timelineDensity}
            viewStartFrac={timelineView.start}
            viewSpanFrac={timelineView.span}
            onSeek={seek}
            onAudioStartChange={handleAudioStart}
            onViewChange={handleTimelineView}
            onDensityChange={setTimelineDensity}
          />
          <div className="timeline-legend">
            {VISEMES.map((viseme) => (
              <span className="legend-item" key={viseme}>
                <i style={{ background: VISEME_COLORS[viseme] }} />
                {VISEME_LABELS[viseme]}
              </span>
            ))}
            <span className="legend-item blink">
              <i />
              眨眼
            </span>
            <span className="legend-item audio-drag-hint">
              <i />
              拖动波形调音频位置
            </span>
            <span className="legend-item zoom-hint">滚轮缩放 · Shift+滚轮平移</span>
          </div>
        </section>
      </section>

      <StatusBar
        mockMode={mockMode}
        health={health}
        statusText={statusText}
        psdId={psd?.assetId ?? null}
        svpId={svp?.assetId ?? null}
        audioId={audio?.assetId ?? null}
        time={time}
        duration={duration}
        fps={fps}
      />

      <div className="toasts">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.kind}`}>
            {toast.kind === 'error' ? (
              <IconAlert size={15} />
            ) : toast.kind === 'success' ? (
              <IconCheck size={15} />
            ) : (
              <IconSparkles size={15} />
            )}
            <span>{toast.text}</span>
          </div>
        ))}
      </div>

      <input ref={psdInputRef} type="file" accept=".psd" hidden onChange={inputHandlers.psd} />
      <input ref={svpInputRef} type="file" accept=".svp" hidden onChange={inputHandlers.svp} />
      <input
        ref={audioInputRef}
        type="file"
        accept="audio/*,.wav,.mp3,.flac,.m4a,.ogg"
        hidden
        onChange={inputHandlers.audio}
      />
      <audio
        ref={audioRef}
        src={audioUrl ?? undefined}
        preload="auto"
        style={{ display: 'none' }}
        onError={() => notify('error', '音频加载失败：请检查文件格式或后端 /api/audio/{id}/file')}
      />

      {!isMockEnabled() && !health.online ? (
        <div className="backend-banner">
          <IconSpinner size={13} />
          真实后端离线：请确认 127.0.0.1:8787 正在运行，或点击顶栏 MOCK 切换回内置数据。
        </div>
      ) : null}

      <ExportPanel
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        psdAssetId={psd?.assetId ?? null}
        psdWidth={psd?.width ?? 0}
        psdHeight={psd?.height ?? 0}
        manifestStale={manifestStale && Boolean(manifest)}
        manifestReady={Boolean(manifest)}
        hiddenLayers={Array.from(hiddenStaticLayers)}
        timeline={timeline}
        blinks={blinks}
        currentTime={time}
        defaultBrow={defaultState.brow}
        defaultCheek={defaultState.cheek}
        mockMode={mockMode}
        sway={sway}
        bpm={bpm}
        audioStart={offset}
        onNotify={notify}
      />

      <ProjectPanel
        open={projectsOpen}
        projects={projects}
        loading={projectsLoading}
        error={projectsError}
        onClose={() => setProjectsOpen(false)}
        onOpen={handleOpenProject}
        onDelete={handleDeleteProject}
        onRefresh={() => void refreshProjects()}
      />
    </div>
  )
}
