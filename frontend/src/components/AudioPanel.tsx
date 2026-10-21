import type { AudioSummary, SwayConfig } from '../types'
import { formatDuration } from '../lib/format'
import { AudioWave } from './AudioWave'
import { IconClock, IconMusic, IconSave, IconSpinner } from './Icons'

interface AudioPanelProps {
  audio: AudioSummary | null
  audioUrl: string | null
  mockMode: boolean
  peaks: number[] | null
  time: number
  duration: number
  bpm: number | null
  offset: number
  sway: SwayConfig
  onBpm: (value: number | null) => void
  onOffset: (value: number) => void
  onSway: (value: SwayConfig) => void
  onSaveBpm: () => void
  savingBpm: boolean
  bpmDirty: boolean
  onImport: () => void
}

export function AudioPanel({
  audio,
  audioUrl,
  mockMode,
  peaks,
  time,
  duration,
  bpm,
  offset,
  sway,
  onBpm,
  onOffset,
  onSway,
  onSaveBpm,
  savingBpm,
  bpmDirty,
  onImport,
}: AudioPanelProps) {
  const parseNumber = (value: string): number | null => {
    if (value.trim() === '') return null
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }

  return (
    <section className="panel audio-panel">
      <div className="panel-head">
        <span className="panel-title">
          <IconMusic size={14} />
          音频 / BPM
        </span>
        <button className="mini-btn" onClick={onImport} title="导入或替换音频">
          导入
        </button>
      </div>

      {!audio ? (
        <div className="panel-empty compact">
          <p>导入音频后显示波形与节拍网格，播放时以音频时钟驱动时间轴。</p>
        </div>
      ) : (
        <>
          <div className="source-line">
            <span className="source-name" title={audio.filename}>
              {audio.filename}
            </span>
            <span className="source-meta">
              {formatDuration(audio.durationSec)}
              {audio.sampleRate ? ` · ${Math.round(audio.sampleRate / 1000)}kHz` : ''}
              {audio.channels ? ` · ${audio.channels}ch` : ''}
            </span>
          </div>
          <div className={`audio-source ${audioUrl?.startsWith('blob:') || mockMode ? 'mock' : 'live'}`}>
            {audioUrl?.startsWith('blob:') || mockMode
              ? 'MOCK 内置合成音频（含 440Hz 节拍哔声）'
              : `LIVE 后端音频 · ${audioUrl ?? `/api/audio/${audio.assetId}/file`}`}
          </div>
          {audioUrl ? (
            <a className="source-open" href={audioUrl} target="_blank" rel="noreferrer">
              在新标签页试听原始音频（用于区分文件本身与播放器问题）
            </a>
          ) : null}

          <AudioWave
            peaks={peaks}
            duration={duration}
            audioDuration={audio.durationSec ?? 0}
            start={offset}
            bpm={bpm}
            time={time}
          />

          <div className="audio-controls">
            <label className="field">
              <span>BPM</span>
              <input
                className="mini-input number"
                type="number"
                step="0.1"
                min="1"
                value={bpm ?? ''}
                placeholder="—"
                onChange={(event) => onBpm(parseNumber(event.target.value))}
              />
            </label>
            <label className="field">
              <span>音频起点 (s)</span>
              <input
                className="mini-input number"
                type="number"
                step="0.01"
                value={offset}
                onChange={(event) => onOffset(parseNumber(event.target.value) ?? 0)}
              />
            </label>
            <button
              className="mini-btn"
              onClick={() => onOffset(Math.round((offset - 0.1) * 1000) / 1000)}
              title="音频向左（提前）0.1s"
            >
              −0.1
            </button>
            <button
              className="mini-btn"
              onClick={() => onOffset(Math.round((offset + 0.1) * 1000) / 1000)}
              title="音频向右（延后）0.1s"
            >
              +0.1
            </button>
            <button
              className="mini-btn"
              onClick={() => onOffset(Math.round(time * 100) / 100)}
              title="把音频的 0 秒对齐到当前播放头"
            >
              对齐播放头
            </button>
            <button className="mini-btn" onClick={() => onOffset(0)} title="音频从时间轴 0 秒开始">
              归零
            </button>
            <button className="btn ghost" onClick={onSaveBpm} disabled={!bpmDirty || savingBpm} title="PUT /api/audio/{assetId}/bpm">
              {savingBpm ? <IconSpinner size={13} /> : <IconSave size={13} />}
              保存
            </button>
          </div>

          <div className="audio-note">
            <IconClock size={11} />
            音频起点 = 音频 0 秒对应的时间轴位置；<b>负值</b>表示音频从 0 秒之前开始（前奏会被裁掉），
            正值表示音频延后进入。也可直接拖动时间轴上的音频波形调整。
          </div>

          <div className="sway-controls">
            <label className="sway-toggle">
              <input
                type="checkbox"
                checked={sway.enabled}
                disabled={!bpm}
                onChange={(event) => onSway({ ...sway, enabled: event.target.checked })}
              />
              <span>随节奏摇摆</span>
            </label>
            <label className="field">
              <span>幅度 {Math.round(sway.amplitude * 100)}%</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={sway.amplitude}
                onChange={(event) => onSway({ ...sway, amplitude: Number(event.target.value) })}
              />
            </label>
            <label className="field">
              <span>频率 (次/拍)</span>
              <input
                className="mini-input number"
                type="number"
                min="0.125"
                max="4"
                step="0.125"
                value={sway.frequency}
                onChange={(event) => onSway({ ...sway, frequency: Number(event.target.value) })}
              />
            </label>
            <label className="field">
              <span>偏移 (拍)</span>
              <input
                className="mini-input number"
                type="number"
                min="-64"
                max="64"
                step="0.125"
                value={sway.offset}
                onChange={(event) => onSway({ ...sway, offset: Number(event.target.value) || 0 })}
              />
            </label>
          </div>
        </>
      )}
    </section>
  )
}
