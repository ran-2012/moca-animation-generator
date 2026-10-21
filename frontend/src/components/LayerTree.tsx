import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { LayerNode } from '../types'
import { IconChevronDown, IconChevronRight, IconEye, IconEyeOff, IconLayers } from './Icons'

interface LayerTreeProps {
  root: LayerNode | null
  thumbFor: (node: LayerNode) => string | null
  mappedIds: Set<string>
  hiddenGroups: Set<string>
  hiddenLayers: Set<string>
  selectedId: string | null
  onSelect: (node: LayerNode) => void
  onToggleGroup: (path: string) => void
  onToggleLayer: (id: string) => void
}

function countPixels(node: LayerNode): number {
  if (node.kind === 'pixel') return 1
  return node.children.reduce((sum, child) => sum + countPixels(child), 0)
}

function collectGroupIds(node: LayerNode, into: string[]): void {
  if (node.kind === 'group') {
    into.push(node.id)
    for (const child of node.children) collectGroupIds(child, into)
  }
}

export function LayerTree({
  root,
  thumbFor,
  mappedIds,
  hiddenGroups,
  hiddenLayers,
  selectedId,
  onSelect,
  onToggleGroup,
  onToggleLayer,
}: LayerTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')

  // expand the group folders that contain mapped layers by default
  useEffect(() => {
    if (!root) {
      setExpanded(new Set())
      return
    }
    const next = new Set<string>()
    next.add(root.id)
    const visit = (node: LayerNode, ancestors: string[]): void => {
      if (mappedIds.has(node.id)) {
        for (const id of ancestors) next.add(id)
        if (node.kind === 'group') next.add(node.id)
      }
      for (const child of node.children) visit(child, [...ancestors, node.id])
    }
    visit(root, [])
    for (const child of root.children) {
      if (child.kind === 'group') next.add(child.id)
    }
    setExpanded(next)
  }, [root, mappedIds])

  const allGroupIds = useMemo(() => {
    const ids: string[] = []
    if (root) collectGroupIds(root, ids)
    return ids
  }, [root])

  const pixelCount = useMemo(() => (root ? countPixels(root) : 0), [root])

  const matchesQuery = (node: LayerNode, needle: string): boolean => {
    if (!needle) return true
    const self = node.name.toLowerCase().includes(needle) || node.id.toLowerCase() === needle
    if (self) return true
    return node.children.some((child) => matchesQuery(child, needle))
  }

  const renderNode = (node: LayerNode, depth: number): ReactNode => {
    if (!matchesQuery(node, query.trim())) return null
    const isGroup = node.kind === 'group'
    const isOpen = query.trim() ? true : expanded.has(node.id)
    const hidden = isGroup ? hiddenGroups.has(node.path) : hiddenLayers.has(node.id)
    const mapped = mappedIds.has(node.id)
    const selected = selectedId === node.id
    const thumb = isGroup ? null : thumbFor(node)
    return (
      <div key={node.id}>
        <div
          className={`layer-row ${selected ? 'selected' : ''} ${hidden ? 'is-hidden' : ''}`}
          style={{ paddingLeft: 4 + depth * 14 }}
          onClick={() => {
            if (isGroup) {
              setExpanded((current) => {
                const next = new Set(current)
                if (next.has(node.id)) next.delete(node.id)
                else next.add(node.id)
                return next
              })
            } else {
              onSelect(node)
            }
          }}
          title={`${node.name}  ·  id ${node.id}  ·  ${node.width}×${node.height}`}
        >
          {isGroup ? (
            <span className="layer-chev">{isOpen ? <IconChevronDown size={12} /> : <IconChevronRight size={12} />}</span>
          ) : (
            <span className="layer-chev-spacer" />
          )}
          <span className={`layer-thumb ${isGroup ? 'group' : ''}`}>
            {thumb ? <img src={thumb} alt="" loading="lazy" draggable={false} /> : <IconLayers size={12} />}
          </span>
          <span className="layer-name">{node.name}</span>
          {isGroup ? <span className="layer-count">{node.children.length}</span> : null}
          {mapped ? <span className="mapped-dot" title="已映射到语义槽位" /> : null}
          {!isGroup ? (
            <span className="layer-meta">
              {node.width}×{node.height}
            </span>
          ) : null}
          <button
            className={`layer-eye ${hidden ? 'off' : ''}`}
            title={hidden ? '在烘焙基准图中显示该图层/组' : '从烘焙基准图中隐藏该图层/组'}
            onClick={(event) => {
              event.stopPropagation()
              if (isGroup) onToggleGroup(node.path)
              else onToggleLayer(node.id)
            }}
          >
            {hidden ? <IconEyeOff size={12} /> : <IconEye size={12} />}
          </button>
        </div>
        {isGroup && isOpen ? node.children.map((child) => renderNode(child, depth + 1)) : null}
      </div>
    )
  }

  return (
    <div className="layer-tree">
      <div className="layer-tree-toolbar">
        <input
          className="mini-input"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="过滤图层名 / id"
          spellCheck={false}
        />
        <button
          className="mini-btn"
          onClick={() => setExpanded(new Set(allGroupIds))}
          title="展开全部"
        >
          展开
        </button>
        <button className="mini-btn" onClick={() => setExpanded(new Set())} title="折叠全部">
          折叠
        </button>
      </div>
      <div className="layer-tree-scroll">
        {root ? (
          <>
            {renderNode(root, 0)}
            <div className="layer-tree-foot">
              {pixelCount} 个像素层 · 眼睛图标会写入 base.hiddenGroups / hiddenLayers
            </div>
          </>
        ) : (
          <div className="panel-empty small">
            <IconLayers size={20} />
            <p>导入 PSD 后在这里查看图层树</p>
          </div>
        )}
      </div>
    </div>
  )
}
