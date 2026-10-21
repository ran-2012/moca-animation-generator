import type { SvpUploadInfo } from '../types'
import { formatDuration } from '../lib/format'
import { IconAlert, IconFilm, IconSpinner } from './Icons'

interface SvpPanelProps {
  svp: SvpUploadInfo | null
  selectedTrack: number | null
  onSelectTrack: (index: number) => void
  onGenerate: () => void
  generating: boolean
  onImport: () => void
  hasTimeline: boolean
  timelineFrames: number
  timelineDuration: number
  blinksCount: number
  warnings: string[]
}

export function SvpPanel({
  svp,
  selectedTrack,
  onSelectTrack,
  onGenerate,
  generating,
  onImport,
  hasTimeline,
  timelineFrames,
  timelineDuration,
  blinksCount,
  warnings,
}: SvpPanelProps) {
  return (
    <section className="panel svp-panel">
      <div className="panel-head">
        <span className="panel-title">
          <IconFilm size={14} />
          SVP 轨道
        </span>
        <span className="panel-badge">单轨</span>
      </div>

      {!svp ? (
        <div className="panel-empty compact">
          <p>导入 Synthesizer V 工程后，选择一条人声轨生成口型时间轴（本期只支持单轨）。</p>
          <button className="btn ghost" onClick={onImport}>
            导入 SVP
          </button>
        </div>
      ) : (
        <>
          <div className="source-line">
            <span className="source-name" title={svp.filename}>
              {svp.filename}
            </span>
            <span className="source-meta">{svp.version ?? 'SVP'}</span>
          </div>

          {svp.warnings && svp.warnings.length > 0 ? (
            <ul className="warn-list compact">
              {svp.warnings.map((warning, index) => (
                <li key={`${warning}-${index}`}>
                  <IconAlert size={11} />
                  <span>{warning}</span>
                </li>
              ))}
            </ul>
          ) : null}

          <div className="track-list" role="radiogroup" aria-label="SVP 轨道">
            {svp.tracks.map((track) => {
              const selected = selectedTrack === track.index
              return (
                <button
                  key={track.index}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  className={`track-row ${selected ? 'selected' : ''} ${track.noteCount === 0 ? 'empty-track' : ''}`}
                  onClick={() => onSelectTrack(track.index)}
                >
                  <span className={`radio-dot ${selected ? 'on' : ''}`} />
                  <span className="track-main">
                    <span className="track-name">{track.name}</span>
                    <span className="track-meta">
                      {track.noteCount} 音符 · 时长 {formatDuration(track.rangeEndSec - track.rangeStartSec)} ·{' '}
                      {formatDuration(track.rangeStartSec)} → {formatDuration(track.rangeEndSec)}
                    </span>
                  </span>
                  <span className={`track-tag ${track.isInstrumental ? 'inst' : 'vocal'}`}>
                    {track.isInstrumental ? '伴奏' : '人声'}
                  </span>
                </button>
              )
            })}
          </div>

          {selectedTrack != null ? (
            <div className="track-footnote">
              {(() => {
                const track = svp.tracks.find((candidate) => candidate.index === selectedTrack)
                if (!track) return null
                if (track.isInstrumental) return '伴奏轨没有音高音符，生成会返回 400，请改选人声轨。'
                return `将使用轨道 #${track.index}「${track.name}」，共 ${track.noteCount} 个音符。`
              })()}
            </div>
          ) : (
            <div className="track-footnote">请选择一条轨道（必需）。</div>
          )}

          <div className="btn-row">
            <button
              className="btn primary wide"
              onClick={onGenerate}
              disabled={selectedTrack == null || generating}
              title="POST /api/svp/{assetId}/timeline"
            >
              {generating ? <IconSpinner size={14} /> : <IconFilm size={14} />}
              {generating ? '生成中…' : '生成时间轴'}
            </button>
          </div>

          {hasTimeline ? (
            <div className="timeline-summary">
              <span className="summary-chip">{timelineFrames} 帧</span>
              <span className="summary-chip">{formatDuration(timelineDuration)}</span>
              <span className="summary-chip">{blinksCount} 眨眼</span>
              {warnings.map((warning, index) => (
                <span className="summary-warn" key={`${warning}-${index}`}>
                  <IconAlert size={11} />
                  {warning}
                </span>
              ))}
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}
