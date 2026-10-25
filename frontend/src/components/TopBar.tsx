import type { HealthResult } from '../api'
import { IconSpinner } from './Icons'

interface TopBarProps {
  projectName: string
  onProjectName: (value: string) => void
  onNewProject: () => void
  onOpenProjects: () => void
  onImportPsd: () => void
  onImportSvp: () => void
  onImportAudio: () => void
  onExport: () => void
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
  onOpenProjects,
  onImportPsd,
  onImportSvp,
  onImportAudio,
  onExport,
  mockMode,
  onToggleMock,
  health,
  busyLabel,
  loaded,
}: TopBarProps) {
  return (
    <header className="topbar">
      <span className="brand">MocaDiff</span>

      <span className="topbar-divider" />

      <label className="project-field">
        <input
          className="project-input"
          value={projectName}
          spellCheck={false}
          onChange={(event) => onProjectName(event.target.value)}
          placeholder="未命名项目"
          title="项目名称"
        />
      </label>

      <button className="btn ghost topbar-new" onClick={onNewProject} title="清空当前工作区（素材与映射）">
        新建
      </button>

      <button className="btn ghost topbar-open" onClick={onOpenProjects} title="打开自动保存的历史项目">
        打开项目
      </button>

      <div className="topbar-spacer" />

      {busyLabel ? (
        <span className="topbar-busy">
          <IconSpinner size={13} />
          {busyLabel}
        </span>
      ) : null}

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

      <div className="import-group">
        <button className={`btn ghost ${loaded.psd ? 'loaded' : ''}`} onClick={onImportPsd} title="导入 PSD 立绘">
          导入 PSD
        </button>
        <button className={`btn ghost ${loaded.svp ? 'loaded' : ''}`} onClick={onImportSvp} title="导入 Synthesizer V 工程">
          导入 SVP
        </button>
        <button className={`btn ghost ${loaded.audio ? 'loaded' : ''}`} onClick={onImportAudio} title="导入音频（wav / mp3 / flac / m4a）">
          导入音频
        </button>
      </div>

      <button className="btn primary" onClick={onExport} title="导出透明帧序列 / ProRes 4444 / WebM / MP4">
        导出
      </button>
    </header>
  )
}
