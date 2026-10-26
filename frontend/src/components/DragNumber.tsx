import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'

interface DragNumberProps {
  value: number
  onChange: (value: number) => void
  /** Value change per drag pixel. */
  step?: number
  min?: number
  max?: number
  /** Decimals shown in the field. */
  precision?: number
  disabled?: boolean
  title?: string
  className?: string
  ariaLabel?: string
}

const clampValue = (value: number, min?: number, max?: number): number =>
  Math.max(min ?? Number.NEGATIVE_INFINITY, Math.min(max ?? Number.POSITIVE_INFINITY, value))

const roundValue = (value: number, precision: number): number =>
  precision > 0 ? Number(value.toFixed(precision)) : Math.round(value)

const formatValue = (value: number, precision: number): string =>
  precision > 0 ? value.toFixed(precision) : String(Math.round(value))

/**
 * Number field that can be scrubbed horizontally with the mouse, like Blender's
 * value fields: drag left/right to change the value, click (without moving) to
 * type an exact number. Shift = fine (0.1×), Ctrl/Cmd = coarse (10×).
 */
export function DragNumber({
  value,
  onChange,
  step = 1,
  min,
  max,
  precision = 0,
  disabled = false,
  title,
  className,
  ariaLabel,
}: DragNumberProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dragRef = useRef<{ startX: number; startValue: number; moved: boolean } | null>(null)
  const [text, setText] = useState(() => formatValue(value, precision))
  const [dragging, setDragging] = useState(false)

  // Keep the field in sync with outside changes (undo, session restore, ...)
  // but never fight the user while the field has focus.
  useEffect(() => {
    if (document.activeElement === inputRef.current) return
    setText(formatValue(value, precision))
  }, [value, precision])

  const commit = useCallback(
    (raw: string) => {
      const parsed = Number(raw.replace(',', '.').replace(/[^\d.eE+-]/g, ''))
      if (!Number.isFinite(parsed)) {
        setText(formatValue(value, precision))
        return
      }
      const next = roundValue(clampValue(parsed, min, max), precision)
      setText(formatValue(next, precision))
      if (next !== value) onChange(next)
    },
    [max, min, onChange, precision, value],
  )

  const handlePointerDown = (event: ReactPointerEvent<HTMLInputElement>) => {
    if (disabled || event.button !== 0) return
    // Blur first so a focused field commits its text instead of starting a
    // text selection while scrubbing.
    if (document.activeElement === inputRef.current) inputRef.current?.blur()
    dragRef.current = { startX: event.clientX, startValue: value, moved: false }
    setDragging(true)
  }

  useEffect(() => {
    if (!dragging) return
    const move = (event: PointerEvent) => {
      const state = dragRef.current
      if (!state) return
      const delta = event.clientX - state.startX
      if (!state.moved && Math.abs(delta) < 3) return
      state.moved = true
      const factor = event.shiftKey ? 0.1 : event.ctrlKey || event.metaKey ? 10 : 1
      const next = roundValue(
        clampValue(state.startValue + delta * step * factor, min, max),
        precision,
      )
      setText(formatValue(next, precision))
      if (next !== value) onChange(next)
      event.preventDefault()
    }
    const finish = () => {
      const state = dragRef.current
      dragRef.current = null
      setDragging(false)
      // A plain click (no scrub) should let the user type a value.
      if (state && !state.moved) {
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', finish)
    window.addEventListener('pointercancel', finish)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', finish)
      window.removeEventListener('pointercancel', finish)
    }
  }, [dragging, max, min, onChange, precision, step, value])

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      commit(event.currentTarget.value)
      event.currentTarget.blur()
      return
    }
    if (event.key === 'Escape') {
      setText(formatValue(value, precision))
      event.currentTarget.blur()
      return
    }
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
    event.preventDefault()
    const direction = event.key === 'ArrowUp' ? 1 : -1
    const factor = event.shiftKey ? 0.1 : event.ctrlKey || event.metaKey ? 10 : 1
    const next = roundValue(clampValue(value + direction * step * 10 * factor, min, max), precision)
    setText(formatValue(next, precision))
    if (next !== value) onChange(next)
  }

  return (
    <input
      ref={inputRef}
      className={className ?? 'mini-input number'}
      type="text"
      inputMode="decimal"
      spellCheck={false}
      value={text}
      disabled={disabled}
      title={title ?? '左右拖动调节数值，单击可直接输入'}
      aria-label={ariaLabel}
      style={{ cursor: dragging ? 'ew-resize' : 'text', touchAction: 'none' }}
      onPointerDown={handlePointerDown}
      onChange={(event) => setText(event.target.value)}
      onBlur={(event) => commit(event.target.value)}
      onKeyDown={handleKeyDown}
    />
  )
}
