import { useEffect, useMemo, useState } from 'react'
import type { BakeManifest, ChannelName, LayerNode, MappingProfile } from '../types'
import { formatTime } from '../lib/format'
import { IconAlert, IconBake, IconCheck, IconSave, IconSliders, IconSpinner, IconWand } from './Icons'

export interface BakeUiState {
  status: 'idle' | 'loading' | 'done' | 'error'
  startedAt?: number
  error?: string
  manifest?: BakeManifest | null
}

interface MappingPanelProps {
  profile: MappingProfile | null
  tree: LayerNode | null
  warnings: string[]
  dirty: boolean
  saving: boolean
  busyAutomap: boolean
  bake: BakeUiState
  stale: boolean
  onAutomap: () => void
  onSave: () => void
  onBake: () => void
  onImportPsd: () => void
  onSlotChange: (channel: ChannelName, slot: string, layerId: string) => void
  onDefaultChange: (channel: ChannelName, value: string) => void
}

interface SlotDef {
  key: string
  label: string
  sub: string
  required?: boolean
}

interface ChannelGroupDef {
  channel: ChannelName
  title: string
  requiredHint: string
  slots: SlotDef[]
}

const CHANNEL_GROUPS: ChannelGroupDef[] = [
  {
    channel: 'mouth',
    title: '口型 mouth',
    requiredHint: '7 个 viseme 全部必需',
    slots: [
      { key: 'a', label: 'a', sub: 'あ', required: true },
      { key: 'i', label: 'i', sub: 'い', required: true },
      { key: 'u', label: 'u', sub: 'う', required: true },
      { key: 'e', label: 'e', sub: 'え', required: true },
      { key: 'o', label: 'o', sub: 'お', required: true },
      { key: 'n', label: 'n', sub: 'ん', required: true },
      { key: 'closed', label: 'closed', sub: '闭口', required: true },
      { key: 'pressed', label: 'pressed', sub: '紧闭' },
      { key: 'narrow', label: 'narrow', sub: '窄口' },
      { key: 'roundSmall', label: 'roundSmall', sub: '小圆口' },
      { key: 'aSoft', label: 'aSoft', sub: '轻开口' },
      { key: 'openLarge', label: 'openLarge', sub: '大开口' },
      { key: 'openXLarge', label: 'openXLarge', sub: '特大开口' },
      { key: 'wide', label: 'wide', sub: '宽口' },
    ],
  },
  {
    channel: 'eyes',
    title: '眼睛 eyes',
    requiredHint: 'open / blink 必需',
    slots: [
      { key: 'open', label: 'open', sub: '睁眼', required: true },
      { key: 'blink', label: 'blink', sub: '闭眼', required: true },
      { key: 'smile', label: 'smile', sub: '笑眼' },
      { key: 'cry', label: 'cry', sub: '哭眼' },
    ],
  },
  {
    channel: 'brow',
    title: '眉毛 brow',
    requiredHint: '可选通道，缺失时降级',
    slots: [
      { key: 'neutral', label: 'neutral', sub: '平静' },
      { key: 'angry', label: 'angry', sub: '生气' },
      { key: 'question', label: 'question', sub: '疑惑' },
      { key: 'surprise', label: 'surprise', sub: '惊讶' },
      { key: 'sad', label: 'sad', sub: '难过' },
    ],
  },
  {
    channel: 'cheek',
    title: '脸颊 cheek',
    requiredHint: '可选通道，缺失时降级',
    slots: [
      { key: 'normal', label: 'normal', sub: '常态' },
      { key: 'blush', label: 'blush', sub: '脸红' },
      { key: 'deep', label: 'deep', sub: '深红' },
    ],
  },
  {
    channel: 'sweat',
    title: '汗 sweat',
    requiredHint: '可选叠加通道，默认关闭',
    slots: [
      { key: 'single', label: 'single', sub: '单汗' },
      { key: 'double', label: 'double', sub: '双汗' },
      { key: 'neck', label: 'neck', sub: '颈汗' },
    ],
  },
  {
    channel: 'eyeEffect',
    title: '眼部效果 eyeEffect',
    requiredHint: '可选叠加通道，默认关闭',
    slots: [
      { key: 'tear', label: 'tear', sub: '眼泪' },
      { key: 'cry', label: 'cry', sub: '哭泣' },
    ],
  },
]

const DEFAULT_CHOICES: Record<ChannelName, string[]> = {
  mouth: ['closed', 'pressed', 'narrow', 'roundSmall', 'aSoft', 'a', 'i', 'u', 'e', 'o', 'n', 'f', 'openLarge', 'openXLarge', 'wide'],
  eyes: ['open', 'blink', 'smile', 'cry'],
  brow: ['neutral', 'angry', 'question', 'surprise', 'sad'],
  cheek: ['normal', 'blush', 'deep'],
  sweat: ['off', 'single', 'double', 'neck'],
  eyeEffect: ['off', 'tear', 'cry'],
}

const DEFAULT_LABELS: Record<ChannelName, string> = {
  mouth: '默认口型',
  eyes: '默认眼睛',
  brow: '默认眉毛',
  cheek: '默认脸颊',
  sweat: '默认汗效果',
  eyeEffect: '默认眼部效果',
}

function flattenPixels(node: LayerNode | null): LayerNode[] {
  if (!node) return []
  const out: LayerNode[] = []
  const walk = (current: LayerNode): void => {
    if (current.kind === 'pixel') out.push(current)
    for (const child of current.children) walk(child)
  }
  walk(node)
  return out
}

export function MappingPanel({
  profile,
  tree,
  warnings,
  dirty,
  saving,
  busyAutomap,
  bake,
  stale,
  onAutomap,
  onSave,
  onBake,
  onImportPsd,
  onSlotChange,
  onDefaultChange,
}: MappingPanelProps) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (bake.status !== 'loading') return
    const timer = window.setInterval(() => setNow(Date.now()), 120)
    return () => window.clearInterval(timer)
  }, [bake.status])

  const pixelLayers = useMemo(() => flattenPixels(tree), [tree])
  const layerById = useMemo(() => new Map(pixelLayers.map((layer) => [layer.id, layer])), [pixelLayers])
  const elapsed = bake.startedAt ? Math.max(0, now - bake.startedAt) : 0

  return (
    <section className="panel mapping-panel">
      <div className="panel-head">
        <span className="panel-title">
          <IconSliders size={14} />
          语义映射
        </span>
        {dirty ? <span className="dirty-badge">未保存</span> : null}
        {profile?.meta?.auto ? <span className="auto-badge">自动</span> : null}
      </div>

      {!tree ? (
        <div className="panel-empty">
          <p>导入 PSD 后可自动识别口型、眼睛、眉毛与脸颊的语义图层。</p>
          <button className="btn primary" onClick={onImportPsd}>
            导入 PSD
          </button>
        </div>
      ) : (
        <>
          {!profile ? (
            <div className="panel-empty compact">
              <p>图层已加载。点击「自动识别」生成口型 / 眼睛 / 眉毛 / 脸颊四组语义槽位，再逐一确认。</p>
            </div>
          ) : null}

          {warnings.length > 0 ? (
            <ul className="warn-list">
              {warnings.slice(0, 4).map((warning, index) => (
                <li key={`${warning}-${index}`}>
                  <IconAlert size={12} />
                  <span>{warning}</span>
                </li>
              ))}
              {warnings.length > 4 ? <li className="warn-more">还有 {warnings.length - 4} 条提示</li> : null}
            </ul>
          ) : null}

          <div className="channel-groups">
            {CHANNEL_GROUPS.map((group) => {
              const confidence = profile?.meta?.confidence?.[group.channel]
              const channelValues = (profile?.channels?.[group.channel] ?? {}) as Record<string, string | null>
              return (
                <div className="channel-group" key={group.channel}>
                  <div className="channel-head">
                    <span className="channel-title">{group.title}</span>
                    <span className="channel-hint">
                      {typeof confidence === 'number' ? `置信 ${Math.round(confidence * 100)}% · ` : ''}
                      {group.requiredHint}
                    </span>
                  </div>
                  <div className="slot-list">
                    {group.slots.map((slot) => {
                      const value = channelValues[slot.key] ?? ''
                      const resolved = value ? layerById.get(value) : undefined
                      return (
                        <label className="slot-row" key={slot.key}>
                          <span className="slot-key">
                            <b>{slot.label}</b>
                            <em>{slot.sub}</em>
                            {slot.required ? <i className="required">必需</i> : null}
                          </span>
                          <span className="slot-control">
                            <select
                              className="select"
                              value={value}
                              disabled={!profile}
                              onChange={(event) => onSlotChange(group.channel, slot.key, event.target.value)}
                            >
                              <option value="">— 未设置 —</option>
                              {pixelLayers.map((layer) => (
                                <option key={layer.id} value={layer.id}>
                                  {layer.name} · #{layer.id}
                                </option>
                              ))}
                            </select>
                            {value ? (
                              <span className={`slot-resolved ${resolved ? 'ok' : 'missing'}`}>
                                {resolved ? resolved.name : '图层不存在'}
                              </span>
                            ) : null}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>

          {profile ? (
            <div className="default-state">
              <div className="channel-head">
                <span className="channel-title">基准状态 base.defaultState</span>
                <span className="channel-hint">无时间轴 / 无 patch 时使用</span>
              </div>
              <div className="default-grid">
                {(Object.keys(DEFAULT_CHOICES) as ChannelName[]).map((channel) => (
                  <label className="default-item" key={channel}>
                    <span>{DEFAULT_LABELS[channel]}</span>
                    <select
                      className="select"
                      value={profile.base.defaultState[channel]}
                      onChange={(event) => onDefaultChange(channel, event.target.value)}
                    >
                      {DEFAULT_CHOICES[channel].map((choice) => (
                        <option key={choice} value={choice}>
                          {choice}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          ) : null}

          <div className="mapping-actions">
            <button className="btn ghost" onClick={onAutomap} disabled={busyAutomap} title="重新解析图层名并填充槽位">
              {busyAutomap ? <IconSpinner size={14} /> : <IconWand size={14} />}
              自动识别
            </button>
            <button className="btn ghost" onClick={onSave} disabled={!profile || !dirty || saving}>
              {saving ? <IconSpinner size={14} /> : <IconSave size={14} />}
              保存映射
            </button>
            <button
              className="btn primary wide"
              onClick={onBake}
              disabled={!profile || bake.status === 'loading'}
              title="POST /api/psd/{assetId}/bake，同步执行约 10–30s"
            >
              {bake.status === 'loading' ? <IconSpinner size={14} /> : <IconBake size={14} />}
              {bake.status === 'loading' ? '烘焙中…' : stale ? '重新烘焙' : '烘焙'}
            </button>
          </div>

          {stale && bake.status !== 'loading' ? (
            <div className="inline-hint">
              <IconAlert size={13} />
              <span>贴图待更新 · 重新烘焙后预览与导出才会使用新的图层可见性和映射</span>
            </div>
          ) : null}

          {bake.status === 'loading' ? (
            <div className="bake-progress">
              <div className="progress-track">
                <div className="progress-bar" style={{ width: `${Math.min(92, 12 + elapsed / 90)}%` }} />
              </div>
              <span>
                base + patches 合成中 · {(elapsed / 1000).toFixed(1)}s <em>首次约 10–30s</em>
              </span>
            </div>
          ) : null}

          {bake.status === 'error' && bake.error ? (
            <div className="inline-error">
              <IconAlert size={14} />
              <div>
                <strong>烘焙失败</strong>
                <p>{bake.error}</p>
              </div>
            </div>
          ) : null}

          {bake.status === 'done' && dirty && !stale ? (
            <div className="inline-hint">
              <IconAlert size={13} />
              <span>图层显示已调整并即时生效 · 保存映射可记住当前可见性</span>
            </div>
          ) : null}

          {bake.status === 'done' && bake.manifest ? (
            <div className="inline-success">
              <IconCheck size={14} />
              <div>
                <strong>烘焙完成</strong>
                <p>
                  {Object.keys(bake.manifest.patches).length} 个 patch · {formatTime(bake.manifest.bakedAt)} · 舞台已加载
                </p>
              </div>
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}
