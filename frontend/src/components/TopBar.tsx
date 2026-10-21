import type { HealthResult } from '../api'
import { formatTimecode } from '../lib/format'
import { IconDownload, IconFilm, IconImage, IconMusic, IconPause, IconPlay, IconPlus, IconSpinner } from './Icons'

interface TopBarProps {
  projectName: string
  onProjectName: (value: string) => void
  onNewProject: () => void
  onImportPsd: () => void
  onImportSvp: () => void
  onImportAudio: () => void
  onExport: () => void
  playing: boolean
  canPlay: boolean
  onTogglePlay: () => void
  time: number
  duration: number
  fps: number
  mockMode: boolean
  onToggleMock: () => void
  health: HealthResult
  busyLabel: string | null
  loaded: { psd: boolean; svp: boolean; audio: boolean }
}

export function TopBar({
  projectName,
  onProjectName,
  onNewProject,
  onImportPsd,
  onImportSvp,
  onImportAudio,
  onExport,
  playing,
  canPlay,
  onTogglePlay,
  time,
  duration,
  fps,
  mockMode,
  onToggleMock,
  health,
  busyLabel,
  loaded,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="brand">
        <svg className="brand-mark" width="26" height="26" viewBox="0 0 32 32" aria-hidden>
          <defs>
            <linearGradient id="brand-gradient" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#8b6dff" />
              <stop offset="1" stopColor="#38d6c4" />
            </linearGradient>
          </defs>
          <path
            d="M16 5.5 26 11v10L16 26.5 6 21V11z"
            fill="none"
            stroke="url(#brand-gradient)"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <circle cx="16" cy="16" r="3.4" fill="url(#brand-gradient)" />
        </svg>
        <div className="brand-text">
          <span className="brand-name">MocaDiff</span>
          <span className="brand-sub">STUDIO</span>
        </div>
      </div>

      <span className="topbar-divider" />

      <label className="project-field">
        <span className="field-label">项目</span>
        <input
          className="project-input"
          value={projectName}
          spellCheck={false}
          onChange={(event) => onProjectName(event.target.value)}
          placeholder="未命名项目"
        />
      </label>

      <button className="btn ghost" onClick={onNewProject} title="清空当前工作区（素材与映射）">
        <IconPlus size={14} />
        新建
      </button>

      <span className="topbar-divider" />

      <div className="import-group">
        <button className={`btn ghost ${loaded.psd ? 'loaded' : ''}`} onClick={onImportPsd} title="导入 PSD 立绘">
          <IconImage size={14} />
          导入 PSD
        </button>
        <button className={`btn ghost ${loaded.svp ? 'loaded' : ''}`} onClick={onImportSvp} title="导入 Synthesizer V 工程">
          <IconFilm size={14} />
          导入 SVP
        </button>
        <button className={`btn ghost ${loaded.audio ? 'loaded' : ''}`} onClick={onImportAudio} title="导入音频（wav / mp3 / flac / m4a）">
          <IconMusic size={14} />
          导入音频
        </button>
      </div>

      <div className="topbar-spacer" />

      {busyLabel ? (
        <span className="topbar-busy">
          <IconSpinner size={14} />
          {busyLabel}
        </span>
      ) : null}

      <div className="transport">
        <button
          className="play-btn"
          onClick={onTogglePlay}
          disabled={!canPlay}
          title={playing ? '暂停（空格）' : '播放（空格）'}
        >
          {playing ? <IconPause size={18} /> : <IconPlay size={18} />}
        </button>
        <div className="transport-time">
          <span className="transport-tc">{formatTimecode(time, true, fps)}</span>
          <span className="transport-duration">/ {formatTimecode(duration, false)}</span>
        </div>
      </div>

      <button
        className={`mock-switch ${mockMode ? 'on' : ''}`}
        onClick={onToggleMock}
        title={
          mockMode
            ? '当前使用内置 Mock 数据（点击切换到真实后端，会重置素材）'
            : `当前连接真实后端${health.version ? ` v${health.version}` : ''}（点击切换到 Mock，会重置素材）`
        }
        aria-pressed={mockMode}
      >
        <i className="mock-dot" />
        {mockMode ? 'MOCK' : 'LIVE'}
      </button>

      <button className="btn ghost" onClick={onExport} title="导出透明帧序列 / ProRes 4444 / WebM / MP4">
        <IconDownload size={14} />
        导出
      </button>
    </header>
  )
}
