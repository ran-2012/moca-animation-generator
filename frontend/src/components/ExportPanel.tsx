import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, getRenderJob, submitRender } from '../api'
import type { Blink, RenderFormat, RenderJobInfo, RenderRequestPayload, SwayConfig, Timeline, ToastMessage } from '../types'
import { clamp, formatDuration, formatTimecode } from '../lib/format'
import {
  EXPORT_BROW_STATES,
  EXPORT_CHEEK_STATES,
  EXPORT_FPS,
  EXPORT_WIDTHS,
  RENDER_FORMATS,
  downloadFileName,
  exportHeight,
  getRenderFormat,
} from '../lib/export'
import { IconAlert, IconCheck, IconDownload, IconSpinner, IconX } from './Icons'

type RangeMode = 'head' | 'full' | 'custom'

interface ExportPanelProps {
  open: boolean
  onClose: () => void
  psdAssetId: string | null
  psdWidth: number
  psdHeight: number
  manifestReady: boolean
  timeline: Timeline | null
  blinks: Blink[]
  currentTime: number
  defaultBrow: string
  defaultCheek: string
  mockMode: boolean
  sway: SwayConfig
  bpm: number | null
  audioStart: number
  onNotify: (kind: ToastMessage['kind'], text: string) => void
}

const POLL_INTERVAL_MS = 600

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return '渲染任务不存在（后端可能已重启），请重新提交。'
    if (error.status === 0) return error.message
    return `${error.message}（HTTP ${error.status}）`
  }
  return error instanceof Error ? error.message : String(error)
}

export function ExportPanel({
  open,
  onClose,
  psdAssetId,
  psdWidth,
  psdHeight,
  manifestReady,
  timeline,
  blinks,
  currentTime,
  defaultBrow,
  defaultCheek,
  mockMode,
  sway,
  bpm,
  audioStart,
  onNotify,
}: ExportPanelProps) {
  const [format, setFormat] = useState<RenderFormat>('png_zip')
  const [rangeMode, setRangeMode] = useState<RangeMode>('head')
  const [headSeconds, setHeadSeconds] = useState('10')
  const [customStart, setCustomStart] = useState('0')
  const [customDuration, setCustomDuration] = useState('10')
  const [outFps, setOutFps] = useState<number>(24)
  const [width, setWidth] = useState<number>(1080)
  const [background, setBackground] = useState('#101010')
  const [brow, setBrow] = useState('')
  const [cheek, setCheek] = useState('')
  const [job, setJob] = useState<RenderJobInfo | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setBrow('')
    setCheek('')
  }, [defaultBrow, defaultCheek])

  const maxTimeline = timeline?.duration ?? 0
  const safeCurrent = clamp(currentTime, 0, maxTimeline)

  const startSec = useMemo(() => {
    if (rangeMode === 'head') return safeCurrent
    if (rangeMode === 'full') return 0
    const parsed = Number(customStart)
    return Number.isFinite(parsed) ? Math.max(0, parsed) : 0
  }, [customStart, rangeMode, safeCurrent])

  const durationSec = useMemo(() => {
    if (rangeMode === 'head') {
      const parsed = Number(headSeconds)
      return Number.isFinite(parsed) ? Math.max(0, parsed) : 0
    }
    if (rangeMode === 'full') return maxTimeline
    const parsed = Number(customDuration)
    return Number.isFinite(parsed) ? Math.max(0, parsed) : 0
  }, [customDuration, headSeconds, maxTimeline, rangeMode])

  const frameCount = Math.max(1, Math.ceil(durationSec * outFps))
  const outputHeight = exportHeight(width, psdWidth, psdHeight)
  const formatOption = getRenderFormat(format)

  const problems = useMemo(() => {
    const list: string[] = []
    if (!psdAssetId || !manifestReady) list.push('缺少已烘焙的 PSD（manifest）：请先导入 PSD 并点击「烘焙」。')
    if (!timeline || timeline.frames.length === 0) list.push('缺少口型时间轴：请先导入 SVP、选择轨道并生成时间轴。')
    if (maxTimeline > 0 && durationSec <= 0) list.push('导出时长必须大于 0 秒。')
    if (durationSec > 300) list.push(`单次导出最多 300 秒（当前 ${durationSec.toFixed(1)}s）。`)
    if (durationSec > 0 && frameCount > 6000) {
      list.push(`帧数 ${frameCount} 超过上限 6000，请缩短时长或降低帧率。`)
    }
    if (maxTimeline > 0 && durationSec > 0 && startSec + durationSec > maxTimeline + 0.5) {
      list.push(
        `导出区间 ${startSec.toFixed(2)}–${(startSec + durationSec).toFixed(2)}s 超出时间轴 0–${maxTimeline.toFixed(2)}s。`,
      )
    }
    return list
  }, [durationSec, frameCount, manifestReady, maxTimeline, psdAssetId, startSec, timeline])

  const ready = problems.length === 0 && Boolean(psdAssetId) && Boolean(timeline)
  const busy = job !== null && (job.status === 'queued' || job.status === 'running')
  const locked = busy || submitting

  const handleSubmit = useCallback(async () => {
    if (!ready || !timeline || !psdAssetId) return
    setSubmitting(true)
    setError(null)
    setJob(null)
    const payload: RenderRequestPayload = {
      psdAssetId,
      timeline: {
        fps: timeline.fps,
        duration: timeline.duration,
        frames: timeline.frames,
        tracks: timeline.tracks,
      },
      blinks,
      startSec,
      durationSec,
      outFps,
      width,
      format,
      background,
      brow: brow || null,
      cheek: cheek || null,
      sway: { ...sway, bpm, audioStart },
    }
    try {
      const created = await submitRender(payload)
      setJob(created)
      onNotify('info', `导出任务已提交：${created.frameCount} 帧 @ ${created.width}×${created.height}`)
    } catch (submitError) {
      const message = describeError(submitError)
      setError(message)
      onNotify('error', `提交导出失败：${message}`)
    } finally {
      setSubmitting(false)
    }
  }, [audioStart, background, blinks, bpm, brow, cheek, durationSec, format, onNotify, outFps, psdAssetId, ready, startSec, sway, timeline, width])

  // poll the render job until it finishes
  const jobId = job?.jobId
  const jobStatus = job?.status
  useEffect(() => {
    if (!jobId || (jobStatus !== 'queued' && jobStatus !== 'running')) return
    let cancelled = false
    const timer = window.setInterval(async () => {
      try {
        const next = await getRenderJob(jobId)
        if (cancelled) return
        setJob(next)
        if (next.status === 'done') {
          window.clearInterval(timer)
          onNotify('success', `导出完成：${next.fileName ?? '文件已就绪'}（${next.frameCount} 帧）`)
        } else if (next.status === 'failed') {
          window.clearInterval(timer)
          onNotify('error', `导出失败：${next.error ?? '未知错误'}`)
        }
      } catch (pollError) {
        if (cancelled) return
        window.clearInterval(timer)
        const message = describeError(pollError)
        setJob((current) => (current ? { ...current, status: 'failed', error: message } : current))
        onNotify('error', `导出失败：${message}`)
      }
    }, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [jobId, jobStatus, onNotify])

  const resetJob = (): void => {
    setJob(null)
    setError(null)
  }

  const progressPercent = job ? Math.round(Math.min(1, Math.max(0, job.progress)) * 100) : 0

  return (
    <div
      className={`modal-overlay ${open ? 'open' : ''}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div className="modal export-panel" role="dialog" aria-modal="true" aria-label="导出">
        <header className="modal-head">
          <div>
            <span className="modal-kicker">EXPORT</span>
            <h2>导出透明立绘序列</h2>
            <p>按当前烘焙纹理 + 时间轴离线渲染，PNG zip 为 FilmCraft 首选，ProRes 4444 给 AE / 达芬奇。</p>
          </div>
          <button className="icon-btn" onClick={onClose} title="关闭导出面板">
            <IconX size={16} />
          </button>
        </header>

        <div className="modal-body">
          {!manifestReady || !timeline ? (
            <div className="export-banner">
              <IconAlert size={14} />
              <div>
                <strong>暂时无法导出</strong>
                <p>
                  {!manifestReady ? '请先导入 PSD → 自动识别 → 烘焙，生成 base + patch 纹理。' : ''}
                  {!timeline ? ' 请先导入 SVP → 选择一条人声轨 → 生成口型时间轴。' : ''}
                </p>
              </div>
            </div>
          ) : null}

          <section className="export-section">
            <div className="export-section-head">
              <span>输出格式</span>
              <em>{formatOption.alpha ? '保留 alpha 透明通道' : '无 alpha，背景色参与合成'}</em>
            </div>
            <div className="format-grid">
              {RENDER_FORMATS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`format-card ${format === option.value ? 'selected' : ''}`}
                  onClick={() => setFormat(option.value)}
                  disabled={locked}
                  data-testid={`export-format-${option.value}`}
                >
                  <span className="format-title">
                    {option.short}
                    <em className={`alpha-tag ${option.alpha ? 'yes' : 'no'}`}>{option.tag}</em>
                  </span>
                  <span className="format-desc">{option.description}</span>
                </button>
              ))}
            </div>
            {format === 'mp4' ? (
              <label className="export-color-row">
                <span>背景色</span>
                <input
                  type="color"
                  value={background}
                  onChange={(event) => setBackground(event.target.value)}
                  disabled={locked}
                  data-testid="export-background"
                />
                <code>{background}</code>
                <em>MP4 无透明通道，其余格式忽略此设置</em>
              </label>
            ) : null}
          </section>

          <section className="export-section">
            <div className="export-section-head">
              <span>导出范围</span>
              <em>时间轴 0 – {maxTimeline > 0 ? formatDuration(maxTimeline) : '—'}</em>
            </div>
            <div className="segmented">
              <button
                type="button"
                className={rangeMode === 'head' ? 'active' : ''}
                onClick={() => setRangeMode('head')}
                disabled={locked}
              >
                播放头起
              </button>
              <button
                type="button"
                className={rangeMode === 'full' ? 'active' : ''}
                onClick={() => setRangeMode('full')}
                disabled={locked}
              >
                全曲
              </button>
              <button
                type="button"
                className={rangeMode === 'custom' ? 'active' : ''}
                onClick={() => setRangeMode('custom')}
                disabled={locked}
              >
                自定义
              </button>
            </div>
            {rangeMode === 'head' ? (
              <div className="export-fields">
                <label className="field">
                  <span>起点（当前播放头）</span>
                  <input className="mini-input" readOnly value={formatTimecode(safeCurrent, false)} />
                </label>
                <label className="field">
                  <span>时长（秒）</span>
                  <input
                    className="mini-input"
                    type="number"
                    min={0.1}
                    step={0.5}
                    value={headSeconds}
                    onChange={(event) => setHeadSeconds(event.target.value)}
                    disabled={locked}
                    data-testid="export-seconds"
                  />
                </label>
              </div>
            ) : rangeMode === 'full' ? (
              <p className="export-note">
                从 0 秒导出到时间轴末尾（{maxTimeline > 0 ? formatDuration(maxTimeline) : '—'}，共{' '}
                {maxTimeline > 0 ? Math.ceil(maxTimeline * outFps) : 0} 帧 @ {outFps}fps）。
              </p>
            ) : (
              <div className="export-fields">
                <label className="field">
                  <span>起点（秒）</span>
                  <input
                    className="mini-input"
                    type="number"
                    min={0}
                    step={0.5}
                    value={customStart}
                    onChange={(event) => setCustomStart(event.target.value)}
                    disabled={locked}
                    data-testid="export-start"
                  />
                </label>
                <label className="field">
                  <span>时长（秒）</span>
                  <input
                    className="mini-input"
                    type="number"
                    min={0.1}
                    step={0.5}
                    value={customDuration}
                    onChange={(event) => setCustomDuration(event.target.value)}
                    disabled={locked}
                    data-testid="export-duration"
                  />
                </label>
              </div>
            )}
          </section>

          <section className="export-section export-two-col">
            <div>
              <div className="export-section-head">
                <span>帧率</span>
              </div>
              <div className="segmented small">
                {EXPORT_FPS.map((fpsOption) => (
                  <button
                    key={fpsOption}
                    type="button"
                    className={outFps === fpsOption ? 'active' : ''}
                    onClick={() => setOutFps(fpsOption)}
                    disabled={locked}
                    data-testid={`export-fps-${fpsOption}`}
                  >
                    {fpsOption}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="export-section-head">
                <span>宽度</span>
              </div>
              <div className="segmented small">
                {EXPORT_WIDTHS.map((widthOption) => (
                  <button
                    key={widthOption}
                    type="button"
                    className={width === widthOption ? 'active' : ''}
                    onClick={() => setWidth(widthOption)}
                    disabled={locked}
                    data-testid={`export-width-${widthOption}`}
                  >
                    {widthOption}
                  </button>
                ))}
              </div>
            </div>
          </section>

          <section className="export-section">
            <div className="export-section-head">
              <span>表情（可选）</span>
              <em>默认跟随动画轨，也可整段固定</em>
            </div>
            <div className="export-fields">
              <label className="field">
                <span>眉毛</span>
                <select className="select" value={brow} onChange={(event) => setBrow(event.target.value)} disabled={locked}>
                  <option value="">跟随动画轨 / {defaultBrow}</option>
                  {EXPORT_BROW_STATES.map((state) => (
                    <option key={state} value={state}>
                      {state}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>脸颊</span>
                <select className="select" value={cheek} onChange={(event) => setCheek(event.target.value)} disabled={locked}>
                  <option value="">跟随动画轨 / {defaultCheek}</option>
                  {EXPORT_CHEEK_STATES.map((state) => (
                    <option key={state} value={state}>
                      {state}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <div className="export-summary">
            <div className="export-metrics">
              <span>
                <b>{frameCount}</b> 帧
              </span>
              <span>
                <b>{outputHeight > 0 ? `${width}×${outputHeight}` : '—'}</b> 尺寸
              </span>
              <span>
                <b>{durationSec.toFixed(2)}s</b> 时长
              </span>
              <span>
                <b>{outFps}</b> fps
              </span>
              <span>
                <b>{formatOption.ext}</b> 格式
              </span>
            </div>
            {problems.length > 0 ? (
              <ul className="export-problems">
                {problems.map((problem) => (
                  <li key={problem}>
                    <IconAlert size={12} />
                    {problem}
                  </li>
                ))}
              </ul>
            ) : frameCount > 2000 ? (
              <p className="export-note warn">
                帧数较多（{frameCount} 帧），首次渲染可能需要数十秒，请保持面板打开或稍后回来查看。
              </p>
            ) : null}
          </div>

          {submitting ? (
            <div className="export-progress" data-testid="export-progress">
              <div className="export-progress-head">
                <span>正在提交任务…</span>
                <IconSpinner size={14} />
              </div>
            </div>
          ) : null}

          {busy && job ? (
            <div className="export-progress" data-testid="export-progress">
              <div className="export-progress-head">
                <span>{job.status === 'queued' ? '排队中…' : '渲染中…'}</span>
                <b>{progressPercent}%</b>
              </div>
              <div className="progress-track">
                <div className="progress-bar" style={{ width: `${Math.max(2, progressPercent)}%` }} />
              </div>
              <div className="export-progress-meta">
                <span>
                  {job.doneFrames} / {job.frameCount} 帧
                </span>
                <span>
                  {job.width}×{job.height}
                </span>
                <span>{job.elapsedSec.toFixed(1)}s</span>
                <span>{job.jobId}</span>
              </div>
            </div>
          ) : null}

          {job?.status === 'done' ? (
            <div className="export-success" data-testid="export-done">
              <IconCheck size={15} />
              <div>
                <strong>导出完成</strong>
                <p>
                  {job.fileName ?? '文件已就绪'} · {job.frameCount} 帧 · {job.width}×{job.height} · 耗时{' '}
                  {job.elapsedSec.toFixed(1)}s
                </p>
              </div>
            </div>
          ) : null}

          {job?.status === 'failed' || error ? (
            <div className="inline-error" data-testid="export-error">
              <IconAlert size={14} />
              <div>
                <strong>导出失败</strong>
                <p>{job?.error ?? error}</p>
              </div>
            </div>
          ) : null}
        </div>

        <footer className="modal-foot">
          <div className="modal-foot-left">
            {mockMode ? (
              <span className="export-mode-note">Mock 模式：进度为本地模拟，下载内容为预览 PNG</span>
            ) : (
              <span className="export-mode-note">真实渲染：完成后通过 {job?.jobId ? `/api/render/${job.jobId}/download` : 'GET /api/render/{jobId}/download'} 下载</span>
            )}
          </div>
          {job?.status === 'done' ? (
            <>
              <button className="btn ghost" onClick={resetJob}>
                重新导出
              </button>
              <a
                className="btn primary"
                href={job.fileUrl ?? '#'}
                download={downloadFileName(job)}
                data-testid="export-download"
              >
                <IconDownload size={14} />
                下载 {job.fileName ?? ''}
              </a>
            </>
          ) : busy ? (
            <>
              <span className="export-running-label">渲染中 {progressPercent}%</span>
              <button className="btn ghost" onClick={onClose}>
                后台继续
              </button>
            </>
          ) : (
            <>
              <button className="btn ghost" onClick={onClose}>
                取消
              </button>
              <button
                className="btn primary"
                onClick={() => void handleSubmit()}
                disabled={!ready || submitting}
                data-testid="export-submit"
                title={ready ? '提交 /api/render' : problems[0] ?? '请先完成 PSD 烘焙与时间轴生成'}
              >
                {submitting ? <IconSpinner size={14} /> : <IconDownload size={14} />}
                开始导出
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  )
}
