// Mock PSD assets: a stylised character rendered entirely with canvas 2D so the
// mock bake output (base PNG + patch PNGs + offsets) exercises exactly the same
// preview code path as a real bake from the backend.
import type { BakeManifest, PatchManifest } from '../types'

export const MOCK_CANVAS: [number, number] = [720, 960]

type Ctx = CanvasRenderingContext2D

function makeCanvas(width: number, height: number): { canvas: HTMLCanvasElement; ctx: Ctx } {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas 2d context unavailable')
  return { canvas, ctx }
}

function linear(ctx: Ctx, x0: number, y0: number, x1: number, y1: number, stops: Array<[number, string]>): CanvasGradient {
  const gradient = ctx.createLinearGradient(x0, y0, x1, y1)
  for (const [offset, color] of stops) gradient.addColorStop(offset, color)
  return gradient
}

function radial(ctx: Ctx, x: number, y: number, r0: number, r1: number, stops: Array<[number, string]>): CanvasGradient {
  const gradient = ctx.createRadialGradient(x, y, r0, x, y, r1)
  for (const [offset, color] of stops) gradient.addColorStop(offset, color)
  return gradient
}

// ---------------------------------------------------------------------------
// base artwork (no face features — those come from patches, exactly like bake)
// ---------------------------------------------------------------------------

function drawBase(): HTMLCanvasElement {
  const { canvas, ctx } = makeCanvas(MOCK_CANVAS[0], MOCK_CANVAS[1])

  // back hair silhouette
  const hairBack = linear(ctx, 0, 130, 0, 880, [
    [0, '#4b3879'],
    [0.45, '#332555'],
    [1, '#1c1631'],
  ])
  ctx.fillStyle = hairBack
  ctx.beginPath()
  ctx.moveTo(158, 400)
  ctx.bezierCurveTo(118, 250, 195, 132, 360, 128)
  ctx.bezierCurveTo(525, 132, 602, 250, 562, 400)
  ctx.bezierCurveTo(578, 530, 596, 680, 606, 832)
  ctx.bezierCurveTo(510, 882, 210, 882, 114, 832)
  ctx.bezierCurveTo(124, 680, 142, 530, 158, 400)
  ctx.closePath()
  ctx.fill()

  // back hair inner shadow + strands
  ctx.fillStyle = 'rgba(18, 12, 34, 0.45)'
  ctx.beginPath()
  ctx.ellipse(360, 690, 210, 170, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = 'rgba(146, 116, 214, 0.18)'
  ctx.lineWidth = 9
  ctx.lineCap = 'round'
  for (const offset of [-118, -64, 64, 118]) {
    ctx.beginPath()
    ctx.moveTo(360 + offset * 0.7, 180)
    ctx.bezierCurveTo(360 + offset, 340, 360 + offset * 1.15, 620, 360 + offset * 1.05, 800)
    ctx.stroke()
  }

  // shoulders / jacket
  const bodyGradient = linear(ctx, 0, 660, 0, 960, [
    [0, '#283750'],
    [0.55, '#1a2539'],
    [1, '#101724'],
  ])
  ctx.fillStyle = bodyGradient
  ctx.beginPath()
  ctx.moveTo(104, 960)
  ctx.bezierCurveTo(120, 838, 172, 760, 268, 726)
  ctx.lineTo(452, 726)
  ctx.bezierCurveTo(548, 760, 600, 838, 616, 960)
  ctx.closePath()
  ctx.fill()

  // jacket shading
  ctx.fillStyle = 'rgba(255, 255, 255, 0.04)'
  ctx.beginPath()
  ctx.moveTo(268, 726)
  ctx.bezierCurveTo(250, 800, 236, 880, 232, 960)
  ctx.lineTo(320, 960)
  ctx.bezierCurveTo(318, 860, 330, 780, 358, 736)
  ctx.closePath()
  ctx.fill()

  // sailor collar
  ctx.fillStyle = linear(ctx, 0, 700, 0, 860, [
    [0, '#e8edf9'],
    [1, '#c3cee6'],
  ])
  ctx.beginPath()
  ctx.moveTo(292, 700)
  ctx.lineTo(360, 790)
  ctx.lineTo(300, 862)
  ctx.bezierCurveTo(262, 820, 250, 756, 262, 706)
  ctx.closePath()
  ctx.fill()
  ctx.beginPath()
  ctx.moveTo(428, 700)
  ctx.lineTo(360, 790)
  ctx.lineTo(420, 862)
  ctx.bezierCurveTo(458, 820, 470, 756, 458, 706)
  ctx.closePath()
  ctx.fill()

  // teal trim + collar shadow
  ctx.strokeStyle = 'rgba(56, 214, 196, 0.75)'
  ctx.lineWidth = 5
  ctx.beginPath()
  ctx.moveTo(292, 704)
  ctx.lineTo(360, 792)
  ctx.lineTo(428, 704)
  ctx.stroke()
  ctx.fillStyle = 'rgba(12, 20, 34, 0.45)'
  ctx.beginPath()
  ctx.moveTo(300, 860)
  ctx.lineTo(330, 742)
  ctx.lineTo(360, 790)
  ctx.lineTo(390, 742)
  ctx.lineTo(420, 860)
  ctx.lineTo(360, 918)
  ctx.closePath()
  ctx.fill()

  // neck
  ctx.fillStyle = linear(ctx, 320, 540, 400, 660, [
    [0, '#f2cbb8'],
    [1, '#dda88f'],
  ])
  ctx.beginPath()
  ctx.moveTo(322, 540)
  ctx.bezierCurveTo(322, 610, 318, 648, 306, 690)
  ctx.bezierCurveTo(340, 716, 380, 716, 414, 690)
  ctx.bezierCurveTo(402, 648, 398, 610, 398, 540)
  ctx.closePath()
  ctx.fill()

  // ears
  const skin = linear(ctx, 240, 300, 480, 560, [
    [0, '#fbe3d3'],
    [0.62, '#f3cfba'],
    [1, '#e6b69c'],
  ])
  for (const [cx, flip] of [
    [204, -1],
    [516, 1],
  ] as Array<[number, number]>) {
    ctx.fillStyle = skin
    ctx.beginPath()
    ctx.ellipse(cx, 398, 22, 36, flip * 0.1, 0, Math.PI * 2)
    ctx.fill()
    ctx.strokeStyle = 'rgba(198, 132, 112, 0.45)'
    ctx.lineWidth = 3
    ctx.beginPath()
    ctx.arc(cx + flip * 2, 398, 11, -1.2, 1.2)
    ctx.stroke()
  }

  // head
  ctx.fillStyle = skin
  ctx.beginPath()
  ctx.ellipse(360, 382, 158, 176, 0, 0, Math.PI * 2)
  ctx.fill()

  // cheek / jaw shading
  ctx.fillStyle = radial(ctx, 360, 300, 40, 220, [
    [0, 'rgba(255, 255, 255, 0.18)'],
    [1, 'rgba(255, 255, 255, 0)'],
  ])
  ctx.beginPath()
  ctx.ellipse(360, 380, 158, 176, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = 'rgba(203, 130, 112, 0.10)'
  ctx.beginPath()
  ctx.ellipse(360, 500, 92, 58, 0, 0, Math.PI)
  ctx.fill()

  // nose
  ctx.strokeStyle = 'rgba(190, 126, 112, 0.55)'
  ctx.lineWidth = 3
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(356, 462)
  ctx.quadraticCurveTo(352, 478, 362, 480)
  ctx.stroke()

  // front hair cap + fringe
  const hairFront = linear(ctx, 180, 140, 540, 420, [
    [0, '#5b4296'],
    [0.55, '#3d2c68'],
    [1, '#2a2045'],
  ])
  ctx.fillStyle = hairFront
  ctx.beginPath()
  ctx.moveTo(196, 392)
  ctx.bezierCurveTo(176, 268, 212, 158, 360, 150)
  ctx.bezierCurveTo(508, 158, 544, 268, 524, 392)
  ctx.bezierCurveTo(510, 352, 492, 330, 470, 322)
  ctx.bezierCurveTo(458, 290, 436, 268, 406, 292)
  ctx.bezierCurveTo(396, 258, 374, 240, 352, 286)
  ctx.bezierCurveTo(330, 246, 300, 258, 292, 296)
  ctx.bezierCurveTo(262, 282, 236, 304, 228, 336)
  ctx.bezierCurveTo(214, 350, 204, 368, 196, 392)
  ctx.closePath()
  ctx.fill()

  // hair sheen
  ctx.strokeStyle = 'rgba(198, 170, 255, 0.30)'
  ctx.lineWidth = 10
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(238, 262)
  ctx.bezierCurveTo(268, 196, 332, 176, 382, 184)
  ctx.stroke()
  ctx.strokeStyle = 'rgba(198, 170, 255, 0.18)'
  ctx.lineWidth = 5
  ctx.beginPath()
  ctx.moveTo(442, 196)
  ctx.bezierCurveTo(486, 230, 506, 284, 508, 344)
  ctx.stroke()

  // side locks
  for (const side of [-1, 1] as const) {
    const baseX = side < 0 ? 196 : 524
    ctx.fillStyle = hairFront
    ctx.beginPath()
    ctx.moveTo(baseX, 360)
    ctx.bezierCurveTo(baseX + side * -22, 470, baseX + side * -34, 600, baseX + side * -16, 730)
    ctx.bezierCurveTo(baseX + side * 14, 700, baseX + side * 22, 560, baseX + side * 20, 400)
    ctx.closePath()
    ctx.fill()
  }

  // ahoge
  ctx.strokeStyle = '#3d2c68'
  ctx.lineWidth = 13
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(370, 164)
  ctx.bezierCurveTo(392, 108, 444, 96, 456, 132)
  ctx.stroke()

  // shoulder highlight
  ctx.strokeStyle = 'rgba(142, 178, 255, 0.18)'
  ctx.lineWidth = 6
  ctx.beginPath()
  ctx.moveTo(196, 820)
  ctx.bezierCurveTo(206, 766, 240, 742, 286, 734)
  ctx.stroke()

  return canvas
}

// ---------------------------------------------------------------------------
// patch artwork
// ---------------------------------------------------------------------------

function eyeOpen(ctx: Ctx, cx: number, cy: number): void {
  // sclera
  ctx.save()
  ctx.beginPath()
  ctx.moveTo(cx - 38, cy)
  ctx.quadraticCurveTo(cx, cy - 30, cx + 38, cy)
  ctx.quadraticCurveTo(cx, cy + 20, cx - 38, cy)
  ctx.closePath()
  ctx.fillStyle = '#fcf8ff'
  ctx.fill()
  // iris
  ctx.beginPath()
  ctx.arc(cx + 1, cy - 1, 22, 0, Math.PI * 2)
  ctx.fillStyle = radial(ctx, cx - 6, cy - 9, 2, 24, [
    [0, '#b9a0ff'],
    [0.45, '#7b5cff'],
    [1, '#3b2a86'],
  ])
  ctx.fill()
  // pupil
  ctx.beginPath()
  ctx.arc(cx + 1, cy - 1, 9.5, 0, Math.PI * 2)
  ctx.fillStyle = '#1b1433'
  ctx.fill()
  // highlights
  ctx.fillStyle = 'rgba(255, 255, 255, 0.92)'
  ctx.beginPath()
  ctx.arc(cx - 7, cy - 10, 5.2, 0, Math.PI * 2)
  ctx.fill()
  ctx.beginPath()
  ctx.arc(cx + 9, cy + 7, 2.6, 0, Math.PI * 2)
  ctx.fill()
  // eyelid / lashes
  ctx.strokeStyle = '#2c2148'
  ctx.lineWidth = 6
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(cx - 40, cy)
  ctx.quadraticCurveTo(cx, cy - 36, cx + 40, cy - 2)
  ctx.stroke()
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(cx - 36, cy + 3)
  ctx.quadraticCurveTo(cx, cy + 22, cx + 34, cy + 2)
  ctx.stroke()
  // outer lash flick
  const outer = cx < 160 ? -1 : 1
  ctx.lineWidth = 5
  ctx.beginPath()
  ctx.moveTo(cx + outer * 38, cy - 4)
  ctx.lineTo(cx + outer * 50, cy - 14)
  ctx.stroke()
  ctx.restore()
}

function eyeBlink(ctx: Ctx, cx: number, cy: number): void {
  ctx.save()
  ctx.strokeStyle = '#2c2148'
  ctx.lineWidth = 6
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(cx - 40, cy + 2)
  ctx.quadraticCurveTo(cx, cy + 18, cx + 40, cy + 2)
  ctx.stroke()
  const outer = cx < 160 ? -1 : 1
  ctx.lineWidth = 4
  ctx.beginPath()
  ctx.moveTo(cx + outer * 36, cy + 2)
  ctx.lineTo(cx + outer * 50, cy - 6)
  ctx.stroke()
  // lashes
  for (const dx of [-18, 0, 18]) {
    ctx.beginPath()
    ctx.moveTo(cx + dx, cy + 12)
    ctx.lineTo(cx + dx + 5, cy + 20)
    ctx.stroke()
  }
  ctx.restore()
}

function brow(ctx: Ctx, cx: number, cy: number, variant: 'neutral' | 'angry' | 'question' | 'surprise' | 'sad'): void {
  ctx.save()
  ctx.strokeStyle = '#3a2b5c'
  ctx.lineWidth = 9
  ctx.lineCap = 'round'
  ctx.beginPath()
  switch (variant) {
    case 'angry':
      if (cx < 160) {
        ctx.moveTo(cx - 30, cy + 12)
        ctx.quadraticCurveTo(cx, cy + 2, cx + 30, cy - 10)
      } else {
        ctx.moveTo(cx - 30, cy - 10)
        ctx.quadraticCurveTo(cx, cy + 2, cx + 30, cy + 12)
      }
      break
    case 'question':
      if (cx < 160) {
        ctx.moveTo(cx - 30, cy + 4)
        ctx.quadraticCurveTo(cx, cy - 18, cx + 30, cy - 6)
      } else {
        ctx.moveTo(cx - 30, cy + 2)
        ctx.quadraticCurveTo(cx, cy - 4, cx + 30, cy - 2)
      }
      break
    case 'surprise':
      ctx.moveTo(cx - 30, cy - 4)
      ctx.quadraticCurveTo(cx, cy - 24, cx + 30, cy - 4)
      break
    case 'sad':
      if (cx < 160) {
        ctx.moveTo(cx - 30, cy - 12)
        ctx.quadraticCurveTo(cx, cy - 2, cx + 30, cy + 8)
      } else {
        ctx.moveTo(cx - 30, cy + 8)
        ctx.quadraticCurveTo(cx, cy - 2, cx + 30, cy - 12)
      }
      break
    default:
      ctx.moveTo(cx - 30, cy + 4)
      ctx.quadraticCurveTo(cx, cy - 8, cx + 30, cy + 2)
  }
  ctx.stroke()
  ctx.restore()
}

const MOUTH_STYLES: Record<string, { rx: number; ry: number; open: boolean; tongue?: boolean; teeth?: boolean; flat?: boolean }> = {
  a: { rx: 30, ry: 27, open: true, tongue: true },
  i: { rx: 34, ry: 10, open: true, teeth: true, flat: true },
  u: { rx: 19, ry: 22, open: true },
  e: { rx: 27, ry: 17, open: true, tongue: true },
  o: { rx: 23, ry: 25, open: true },
  n: { rx: 20, ry: 12, open: true, tongue: true },
  closed: { rx: 26, ry: 4, open: false },
  f: { rx: 30, ry: 13, open: true, teeth: true, flat: true },
}

function mouth(ctx: Ctx, cx: number, cy: number, viseme: string): void {
  const style = MOUTH_STYLES[viseme] ?? MOUTH_STYLES.closed
  ctx.save()
  ctx.translate(cx, cy)
  if (!style.open) {
    ctx.strokeStyle = '#b0646d'
    ctx.lineWidth = 4
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(-24, 0)
    ctx.quadraticCurveTo(0, 9, 24, 0)
    ctx.stroke()
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.moveTo(-12, 7)
    ctx.quadraticCurveTo(0, 11, 12, 7)
    ctx.stroke()
  } else {
    ctx.beginPath()
    ctx.ellipse(0, 0, style.rx, style.ry, 0, 0, Math.PI * 2)
    ctx.fillStyle = '#762b3a'
    ctx.fill()
    ctx.strokeStyle = '#a85563'
    ctx.lineWidth = 3.5
    ctx.stroke()
    if (style.teeth) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.92)'
      ctx.beginPath()
      ctx.ellipse(0, -style.ry * 0.42, style.rx * 0.78, style.ry * 0.3, 0, 0, Math.PI * 2)
      ctx.fill()
    }
    if (style.tongue) {
      ctx.fillStyle = '#de7487'
      ctx.beginPath()
      ctx.ellipse(0, style.ry * 0.45, style.rx * 0.55, style.ry * 0.34, 0, 0, Math.PI * 2)
      ctx.fill()
    }
  }
  ctx.restore()
}

function cheek(ctx: Ctx, cx: number, cy: number, strength: number): void {
  if (strength <= 0) return
  ctx.save()
  ctx.fillStyle = radial(ctx, cx, cy, 2, 46, [
    [0, `rgba(255, 122, 156, ${strength})`],
    [1, 'rgba(255, 122, 156, 0)'],
  ])
  ctx.beginPath()
  ctx.ellipse(cx, cy, 44, 30, 0, 0, Math.PI * 2)
  ctx.fill()
  if (strength > 0.25) {
    ctx.strokeStyle = `rgba(255, 138, 166, ${strength * 0.9})`
    ctx.lineWidth = 2.4
    ctx.lineCap = 'round'
    for (const dy of [-8, 0, 8]) {
      ctx.beginPath()
      ctx.moveTo(cx - 16, cy + dy)
      ctx.lineTo(cx + 10, cy + dy - 6)
      ctx.stroke()
    }
  }
  ctx.restore()
}

function renderPatch(
  width: number,
  height: number,
  paint: (ctx: Ctx) => void,
): string {
  const { canvas, ctx } = makeCanvas(width, height)
  paint(ctx)
  return canvas.toDataURL('image/png')
}

function mouthUrl(viseme: string): string {
  return renderPatch(180, 100, (ctx) => mouth(ctx, 90, 50, viseme))
}

function eyesUrl(blink: boolean): string {
  return renderPatch(300, 90, (ctx) => {
    if (blink) {
      eyeBlink(ctx, 90, 45)
      eyeBlink(ctx, 210, 45)
    } else {
      eyeOpen(ctx, 90, 45)
      eyeOpen(ctx, 210, 45)
    }
  })
}

function browUrl(variant: string): string {
  const safe = (['neutral', 'angry', 'question', 'surprise', 'sad'].includes(variant) ? variant : 'neutral') as
    | 'neutral'
    | 'angry'
    | 'question'
    | 'surprise'
    | 'sad'
  return renderPatch(300, 70, (ctx) => {
    brow(ctx, 90, 32, safe)
    brow(ctx, 210, 32, safe)
  })
}

let cachedManifest: BakeManifest | null = null
let cachedBase: string | null = null

/** Mock bake: renders the base + every patch and returns a CONTRACT-shaped manifest. */
export async function buildMockManifest(assetId: string): Promise<BakeManifest> {
  if (cachedManifest && cachedManifest.assetId === assetId) return cachedManifest
  cachedBase = cachedBase ?? drawBase().toDataURL('image/png')

  const patch = (url: string, offset: [number, number], width: number, height: number): PatchManifest => ({
    url,
    offset,
    width,
    height,
  })

  const patches: Record<string, PatchManifest> = {
    'mouth.a': patch(mouthUrl('a'), [270, 455], 180, 100),
    'mouth.i': patch(mouthUrl('i'), [270, 455], 180, 100),
    'mouth.u': patch(mouthUrl('u'), [270, 455], 180, 100),
    'mouth.e': patch(mouthUrl('e'), [270, 455], 180, 100),
    'mouth.o': patch(mouthUrl('o'), [270, 455], 180, 100),
    'mouth.n': patch(mouthUrl('n'), [270, 455], 180, 100),
    'mouth.closed': patch(mouthUrl('closed'), [270, 455], 180, 100),
    'eyes.open': patch(eyesUrl(false), [210, 370], 300, 90),
    'eyes.blink': patch(eyesUrl(true), [210, 370], 300, 90),
    'brow.neutral': patch(browUrl('neutral'), [210, 330], 300, 70),
    'brow.angry': patch(browUrl('angry'), [210, 330], 300, 70),
    'brow.question': patch(browUrl('question'), [210, 330], 300, 70),
    'brow.surprise': patch(browUrl('surprise'), [210, 330], 300, 70),
    'brow.sad': patch(browUrl('sad'), [210, 330], 300, 70),
    'cheek.normal': patch(renderPatch(360, 90, (ctx) => cheek(ctx, 75, 50, 0.10)), [180, 420], 360, 90),
    'cheek.blush': patch(renderPatch(360, 90, (ctx) => cheek(ctx, 75, 50, 0.34)), [180, 420], 360, 90),
    'cheek.deep': patch(renderPatch(360, 90, (ctx) => cheek(ctx, 75, 50, 0.52)), [180, 420], 360, 90),
  }

  cachedManifest = {
    assetId,
    width: MOCK_CANVAS[0],
    height: MOCK_CANVAS[1],
    base: { url: cachedBase },
    patches,
    zorder: ['cheek', 'mouth', 'eyes', 'brow'],
    profileVersion: 'mock-v1',
    bakedAt: new Date().toISOString(),
  }
  return cachedManifest
}

// ---------------------------------------------------------------------------
// mock layer thumbnails
// ---------------------------------------------------------------------------

const thumbCache = new Map<string, string>()

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

export function mockThumb(layerId: string, size = 40): string {
  const key = `${layerId}:${size}`
  const cached = thumbCache.get(key)
  if (cached) return cached
  const { canvas, ctx } = makeCanvas(size, size)
  const hue = hashString(layerId) % 360
  ctx.fillStyle = '#161a24'
  ctx.fillRect(0, 0, size, size)
  ctx.fillStyle = `hsla(${hue}, 62%, 56%, 0.95)`
  const seed = hashString(layerId + 'shape')
  const rx = 6 + (seed % 6)
  const cx = size / 2 + ((seed >> 3) % 6) - 3
  const cy = size / 2 + ((seed >> 6) % 6) - 3
  ctx.beginPath()
  ctx.ellipse(cx, cy, rx, rx * 0.86, ((seed >> 9) % 6) * 0.4, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = 'rgba(255,255,255,0.35)'
  ctx.beginPath()
  ctx.arc(cx - rx * 0.3, cy - rx * 0.3, rx * 0.28, 0, Math.PI * 2)
  ctx.fill()
  const url = canvas.toDataURL('image/png')
  thumbCache.set(key, url)
  return url
}
