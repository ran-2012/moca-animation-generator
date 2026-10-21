import type { HealthResult } from '../api'
import { formatTimecode } from '../lib/format'

interface StatusBarProps {
  mockMode: boolean
  health: HealthResult
  statusText: string
  psdId: string | null
  svpId: string | null
  audioId: string | null
  time: number
  duration: number
  fps: number
}

export function StatusBar({ mockMode, health, statusText, psdId, svpId, audioId, time, duration, fps }: StatusBarProps) {
  return (
    <footer className="statusbar">
      <div className="status-left">
        <span className={`status-dot ${mockMode ? 'mock' : health.online ? 'online' : 'offline'}`} />
        <span className="status-source">{mockMode ? 'Mock 数据源' : '真实后端'}</span>
        <span className="status-divider" />
        <span className={`status-health ${health.online ? 'ok' : 'down'}`}>
          {health.online ? `后端在线${health.version ? ` v${health.version}` : ''}` : '后端离线'}
        </span>
      </div>
      <div className="status-center" title={statusText}>
        {statusText}
      </div>
      <div className="status-right">
        <span className="status-id">PSD {psdId ?? '—'}</span>
        <span className="status-id">SVP {svpId ?? '—'}</span>
        <span className="status-id">AUD {audioId ?? '—'}</span>
        <span className="status-divider" />
        <span className="status-time">
          {formatTimecode(time, true, fps)} / {formatTimecode(duration, false)}
        </span>
      </div>
    </footer>
  )
}
