import type { RenderFormat, RenderJobInfo } from '../types'

export interface RenderFormatOption {
  value: RenderFormat
  label: string
  short: string
  ext: string
  description: string
  alpha: boolean
  tag: string
}

export const RENDER_FORMATS: RenderFormatOption[] = [
  {
    value: 'png_zip',
    label: 'PNG 序列 (zip)',
    short: 'PNG 序列 · ZIP',
    ext: '.zip',
    description: 'RGBA 透明帧序列，FilmCraft 首选；帧数多时体积较大',
    alpha: true,
    tag: '透明',
  },
  {
    value: 'prores4444',
    label: 'ProRes 4444 (MOV)',
    short: 'ProRes 4444 · MOV',
    ext: '.mov',
    description: '带 alpha 通道，After Effects / DaVinci 首选',
    alpha: true,
    tag: '透明',
  },
  {
    value: 'webm_alpha',
    label: 'WebM alpha',
    short: 'WebM · VP9 alpha',
    ext: '.webm',
    description: 'VP9 + alpha，体积小，可直接在浏览器预览',
    alpha: true,
    tag: '透明',
  },
  {
    value: 'mp4',
    label: 'MP4 (H.264)',
    short: 'MP4 · H.264',
    ext: '.mp4',
    description: '无 alpha 通道，需要指定背景色，适合快速预览',
    alpha: false,
    tag: '不透明',
  },
]

export const EXPORT_FPS = [24, 30, 60] as const
export const EXPORT_WIDTHS = [1080, 1240, 1920] as const
export const EXPORT_BROW_STATES = ['neutral', 'angry', 'question', 'surprise', 'sad'] as const
export const EXPORT_CHEEK_STATES = ['normal', 'blush', 'deep'] as const

/** Same rule as backend render_service._even(): proportional height, even pixels. */
export function exportHeight(width: number, psdWidth: number, psdHeight: number): number {
  if (width <= 0 || psdWidth <= 0 || psdHeight <= 0) return 0
  const raw = Math.max(2, Math.round((psdHeight * width) / psdWidth))
  return raw % 2 === 0 ? raw : raw + 1
}

export function getRenderFormat(value: RenderFormat): RenderFormatOption {
  return RENDER_FORMATS.find((option) => option.value === value) ?? RENDER_FORMATS[0]
}

export function downloadFileName(job: RenderJobInfo): string {
  if (job.fileName) return job.fileName
  return `mocadiff_${job.width}x${job.height}${getRenderFormat(job.format).ext}`
}

export function renderStatusLabel(job: RenderJobInfo): string {
  switch (job.status) {
    case 'queued':
      return '排队中'
    case 'running':
      return '渲染中'
    case 'done':
      return '渲染完成'
    case 'failed':
      return '渲染失败'
    default:
      return job.status
  }
}
