import type { ProjectSummary } from '../types'
import { IconAlert, IconFolder, IconSpinner, IconX } from './Icons'

interface ProjectPanelProps {
  open: boolean
  projects: ProjectSummary[]
  loading: boolean
  error: string | null
  onClose: () => void
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  onRefresh: () => void
}

function formatUpdated(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function ProjectPanel({
  open,
  projects,
  loading,
  error,
  onClose,
  onOpen,
  onDelete,
  onRefresh,
}: ProjectPanelProps) {
  return (
    <div className={`modal-overlay ${open ? 'open' : ''}`} role="dialog" aria-label="打开项目" aria-hidden={!open}>
      <div className="modal project-modal">
        <div className="modal-head">
          <div>
            <span className="modal-kicker">PROJECTS</span>
            <h2>打开项目</h2>
            <p>每次自动保存都会记录项目快照；打开后会重新加载 PSD 映射、SVP 时间轴与音频。</p>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="关闭项目面板">
            <IconX size={16} />
          </button>
        </div>

        <div className="modal-body">
          {loading ? (
            <div className="project-loading">
              <IconSpinner size={16} />
              读取项目列表…
            </div>
          ) : null}

          {error ? (
            <div className="inline-error">
              <IconAlert size={14} />
              <div>
                <strong>无法读取项目</strong>
                <p>{error}</p>
              </div>
            </div>
          ) : null}

          {!loading && !error && projects.length === 0 ? (
            <div className="panel-empty">
              <p>还没有历史项目。导入素材并等待自动保存后，这里会出现可打开的项目。</p>
            </div>
          ) : null}

          <div className="project-list">
            {projects.map((project) => (
              <div className="project-row" key={project.id}>
                <span className="project-icon">
                  <IconFolder size={16} />
                </span>
                <div className="project-main">
                  <strong title={project.name}>{project.name}</strong>
                  <span className="project-meta">
                    {project.psd ?? '无 PSD'} · {project.svp ?? '无 SVP'} · {project.audio ?? '无音频'}
                  </span>
                  <span className="project-time">
                    {formatUpdated(project.updatedAt)} · {project.mockMode ? 'MOCK' : 'LIVE'}
                  </span>
                </div>
                <div className="project-actions">
                  <button className="btn primary" onClick={() => onOpen(project.id)} disabled={loading}>
                    打开
                  </button>
                  <button className="mini-btn" onClick={() => onDelete(project.id)} disabled={loading}>
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="modal-foot">
          <div className="modal-foot-left">
            <span className="export-mode-note">历史记录保存在本机 data/projects.json，不随素材一起分发。</span>
          </div>
          <button className="btn ghost" onClick={onRefresh} disabled={loading}>
            刷新
          </button>
          <button className="btn ghost" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
