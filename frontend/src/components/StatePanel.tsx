import type { StageState } from '../types'
import { VISEME_COLORS, VISEME_LABELS } from '../lib/timeline'
import { formatTimecode } from '../lib/format'
import { IconSparkles } from './Icons'

interface StatePanelProps {
  state: StageState
  time: number
  duration: number
  fps: number
  playing: boolean
  frameCount: number
  blinkCount: number
  hasAudio: boolean
  hasTimeline: boolean
}

export function StatePanel({
  state,
  time,
  duration,
  fps,
  playing,
  frameCount,
  blinkCount,
  hasAudio,
  hasTimeline,
}: StatePanelProps) {
  const color = VISEME_COLORS[state.viseme]
  return (
    <section className="panel state-panel">
      <div className="panel-head">
        <span className="panel-title">
          <IconSparkles size={14} />
          当前状态
        </span>
        <span className={`live-dot ${playing ? 'on' : ''}`} title={playing ? '播放中' : '已暂停'} />
      </div>

      <div className="state-hero">
        <span className="viseme-badge" style={{ background: color }}>
          {VISEME_LABELS[state.viseme] ?? state.viseme}
        </span>
        <div className="state-hero-text">
          <strong>{state.viseme}</strong>
          <span>openness {Math.round(state.openness * 100)}%</span>
        </div>
        <div className="state-hero-time">
          <span>{formatTimecode(time, true, fps)}</span>
          <em>第 {Math.floor(time * fps)} 帧</em>
        </div>
      </div>

      <dl className="state-grid">
        <div>
          <dt>眨眼</dt>
          <dd className={state.blink ? 'accent-amber' : ''}>{state.blink ? '闭眼命中' : '睁眼'}</dd>
        </div>
        <div>
          <dt>眉毛</dt>
          <dd>{state.brow}</dd>
        </div>
        <div>
          <dt>脸颊</dt>
          <dd>{state.cheek}</dd>
        </div>
        <div>
          <dt>时间轴</dt>
          <dd>{hasTimeline ? `${frameCount} 帧` : '未生成'}</dd>
        </div>
        <div>
          <dt>眨眼事件</dt>
          <dd>{blinkCount}</dd>
        </div>
        <div>
          <dt>时钟源</dt>
          <dd>{hasAudio ? '音频' : 'perf.now'}</dd>
        </div>
        <div>
          <dt>时长</dt>
          <dd>{duration > 0 ? `${duration.toFixed(2)}s` : '—'}</dd>
        </div>
        <div>
          <dt>FPS</dt>
          <dd>{fps}</dd>
        </div>
      </dl>
    </section>
  )
}
