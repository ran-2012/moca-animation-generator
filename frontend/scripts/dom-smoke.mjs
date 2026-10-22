// In-process smoke test for the MocaDiff frontend.
//
// A real browser cannot start in this sandbox (Chrome's mojo named pipes are
// denied) and browser drivers are unavailable, so this script mounts the actual
// React app in jsdom, stubs only pixel APIs (2D canvas / Image / ResizeObserver /
// media), and walks the acceptance flow.
//
// Mock mode (default) — no backend required:
//   node --require ./scripts/child-process-shim.cjs ./scripts/dom-smoke.mjs
//   PSD upload -> tree -> automap -> save -> bake -> stage manifest
//   SVP upload -> select track 5 -> generate timeline -> viseme blocks
//   audio upload -> peaks/BPM -> play (window clock) -> mock/live toggle
//
// Real-backend mode — needs uvicorn (8787 by default):
//   $env:MOCADIFF_REAL="1"; $env:MOCADIFF_BACKEND="http://127.0.0.1:8787"; npm run smoke
//   PSD upload -> tree -> automap -> save -> bake against the real API, then
//   verify that not-yet-implemented SVP/audio endpoints surface readable errors.
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { JSDOM } from 'jsdom'

const REAL = process.env.MOCADIFF_REAL === '1'
const BACKEND = process.env.MOCADIFF_BACKEND ?? 'http://127.0.0.1:8787'
const WORKSPACE = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const PSD_PATH = process.env.MOCADIFF_PSD ?? resolve(WORKSPACE, 'moca.psd')
const SVP_PATH = process.env.MOCADIFF_SVP ?? resolve(WORKSPACE, '流沙.svp')
const AUDIO_PATH = process.env.MOCADIFF_AUDIO ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '.tmp-audio', 'test.wav')

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://127.0.0.1:5199/',
  pretendToBeVisual: true,
})

const { window } = dom
const errors = []
const originalConsoleError = console.error
console.error = (...args) => {
  const message = args.map(String).join(' ')
  if (message.includes('Maximum update depth exceeded')) {
    errors.push(`${message}\n${new Error('React update loop').stack}`)
  }
  originalConsoleError(...args)
}
const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms))

Object.assign(globalThis, {
  window,
  document: window.document,
  HTMLElement: window.HTMLElement,
  HTMLCanvasElement: window.HTMLCanvasElement,
  HTMLMediaElement: window.HTMLMediaElement,
  Element: window.Element,
  Node: window.Node,
  Event: window.Event,
  localStorage: window.localStorage,
  getComputedStyle: window.getComputedStyle.bind(window),
  requestAnimationFrame: window.requestAnimationFrame.bind(window),
  cancelAnimationFrame: window.cancelAnimationFrame.bind(window),
})
try {
  globalThis.navigator = window.navigator
} catch {
  /* Node's navigator is a read-only getter; the app only reads userAgent */
}
if (!REAL) globalThis.File = window.File

window.addEventListener('error', (event) => errors.push(String(event.error ?? event.message)))
window.addEventListener('unhandledrejection', (event) => errors.push(`unhandled: ${event.reason}`))
window.localStorage.setItem('mocadiff.mock', REAL ? '0' : '1')

// ---- pixel/media API stubs (do not change app logic) -----------------------
const gradient = () => ({ addColorStop() {} })
const fakeContext = () => {
  const base = {
    createLinearGradient: gradient,
    createRadialGradient: gradient,
    createPattern: gradient,
    measureText: () => ({ width: 12 }),
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    createImageData: () => ({ data: new Uint8ClampedArray(4) }),
  }
  return new Proxy(base, {
    get: (target, prop) => (prop in target ? target[prop] : () => undefined),
    set: () => true,
  })
}
window.HTMLCanvasElement.prototype.getContext = () => fakeContext()
window.HTMLCanvasElement.prototype.toDataURL = () => 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
window.HTMLCanvasElement.prototype.setPointerCapture = () => {}
window.HTMLCanvasElement.prototype.hasPointerCapture = () => true
window.HTMLCanvasElement.prototype.releasePointerCapture = () => {}

class FakeImage {
  naturalWidth = 160
  naturalHeight = 160
  decoding = 'async'
  onload = null
  onerror = null
  set src(value) {
    this._src = value
    setTimeout(() => this.onload && this.onload(), 0)
  }
  get src() {
    return this._src
  }
}
globalThis.Image = FakeImage
window.Image = FakeImage

class FakeResizeObserver {
  constructor(callback) {
    this.callback = callback
  }
  observe() {
    setTimeout(() => this.callback([{ contentRect: { width: 900, height: 620 } }], this), 0)
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = FakeResizeObserver

const mediaPrototype = window.HTMLMediaElement.prototype
mediaPrototype.play = () => Promise.resolve()
mediaPrototype.pause = () => {}
Object.defineProperty(mediaPrototype, 'currentTime', {
  configurable: true,
  get() {
    return 0
  },
  set() {},
})
Object.defineProperty(mediaPrototype, 'paused', {
  configurable: true,
  get() {
    return true
  },
})

// ---- transport -------------------------------------------------------------
const nodeFetch = globalThis.fetch.bind(globalThis)
globalThis.fetch = async (input, init) => {
  const url = typeof input === 'string' ? input : input?.url ?? ''
  if (REAL) {
    // jsdom's AbortSignal is not accepted by Node's fetch; drop it for the test
    const { signal: _signal, ...rest } = init ?? {}
    if (url.startsWith('/')) return nodeFetch(BACKEND + url, rest)
    return nodeFetch(input, rest)
  }
  if (url.includes('/api/health')) {
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true, version: '0.1.0' }),
      text: async () => '',
    }
  }
  return {
    ok: false,
    status: 404,
    statusText: 'Not Found',
    json: async () => ({ detail: 'mock transport disabled in smoke test' }),
    text: async () => '',
  }
}

// ---- helpers ---------------------------------------------------------------
const step = (label) => console.log(`\n▶ ${label}`)
const waitFor = async (label, predicate, timeout = REAL ? 90000 : 20000) => {
  const start = Date.now()
  while (Date.now() - start < timeout) {
    try {
      const value = predicate()
      if (value) return value
    } catch {
      /* still rendering */
    }
    await sleep(80)
  }
  throw new Error(`等待超时：${label}`)
}
const bodyText = () => document.body.textContent ?? ''
const findButton = (label) =>
  [...document.querySelectorAll('button')].find((button) => button.textContent.includes(label) && !button.disabled)
const clickButton = (label) => {
  const button = findButton(label)
  if (!button) {
    throw new Error(
      `找不到可点击按钮「${label}」。当前按钮：${[...document.querySelectorAll('button')]
        .map((item) => item.textContent.trim())
        .join(' | ')}`,
    )
  }
  button.click()
}
const setNativeInput = (input, value) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  setter.call(input, value)
  input.dispatchEvent(new window.Event('input', { bubbles: true }))
}
const readAssetId = (prefix) => {
  const text = [...document.querySelectorAll('.status-id')].map((element) => element.textContent ?? '').join(' ')
  const match = new RegExp(`${prefix}\\s+([0-9a-f]{6,})`).exec(text)
  return match ? match[1] : null
}
const fetchJson = async (path) => {
  const response = await globalThis.fetch(path)
  if (!response.ok) throw new Error(`${path} → HTTP ${response.status}`)
  return response.json()
}
const byTestId = (id) => document.querySelector(`[data-testid="${id}"]`)
const clickSegmented = (label) => {
  const button = [...document.querySelectorAll('.segmented button')].find((item) => item.textContent.trim() === label)
  if (!button) throw new Error(`找不到分段按钮「${label}」`)
  button.click()
}
const makeFile = (name, type, bytes) => {
  const payload = bytes ?? new Uint8Array([1, 2, 3, 4])
  if (REAL) return new globalThis.File([payload], name, { type })
  return new window.File([payload], name, { type })
}
const readFileBytes = (path) => (existsSync(path) ? readFileSync(path) : null)
const setFile = (selector, file) => {
  const input = document.querySelector(selector)
  if (!input) throw new Error(`找不到文件输入：${selector}`)
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  input.dispatchEvent(new window.Event('change', { bubbles: true }))
}
const assert = (condition, message) => {
  if (!condition) throw new Error(`断言失败：${message}`)
  console.log(`  ✓ ${message}`)
}

/** Shared export-panel flow used by both the mock and real-backend runs. */
async function runExportFlow({ label, durationSeconds, expectMock }) {
  step(`导出/渲染流程（${label}）`)
  clickButton('导出')
  await waitFor('导出面板打开', () => document.querySelector('.modal-overlay.open'))
  assert(Boolean(byTestId('export-format-png_zip')), '四种输出格式渲染')
  byTestId('export-format-mp4').click()
  await waitFor('mp4 背景色选项', () => byTestId('export-background'))
  assert(true, 'MP4 显示背景色设置')
  byTestId('export-format-png_zip').click()
  await sleep(90)
  assert(byTestId('export-format-png_zip').classList.contains('selected'), '默认选中 PNG 序列（透明）')

  clickSegmented('自定义')
  await sleep(90)
  setNativeInput(byTestId('export-start'), '0')
  setNativeInput(byTestId('export-duration'), '400')
  await waitFor('超限提示', () => (document.querySelector('.export-problems')?.textContent ?? '').includes('300'))
  assert(byTestId('export-submit').disabled, '超过 300s / 6000 帧上限时禁用提交')

  clickSegmented('播放头起')
  await sleep(90)
  setNativeInput(byTestId('export-seconds'), String(durationSeconds))
  await sleep(140)
  const metrics = document.querySelector('.export-metrics').textContent.replace(/\s+/g, ' ')
  const expectedFrames = Math.ceil(durationSeconds * 24)
  assert(metrics.includes(String(expectedFrames)), `按 24fps 估算 ${expectedFrames} 帧`)

  byTestId('export-submit').click()
  await waitFor('导出任务进度', () => byTestId('export-progress'), 20000)
  await waitFor('导出完成', () => byTestId('export-done'), expectMock ? 30000 : 150000)
  assert(true, '轮询任务并显示进度条')
  const download = byTestId('export-download')
  const href = download?.getAttribute('href') ?? ''
  const successText = document.querySelector('.export-success')?.textContent ?? ''
  if (expectMock) {
    assert(href.startsWith('data:image/png'), 'Mock 下载为预览 PNG（data URL）')
    assert(successText.includes(`${expectedFrames} 帧`), '完成信息显示帧数')
  } else {
    assert(/^\/api\/render\/[^/]+\/download$/.test(href), `真实下载地址 ${href}`)
    const response = await globalThis.fetch(href)
    assert(response.ok, `下载接口 HTTP ${response.status}`)
    assert((response.headers.get('content-type') ?? '').includes('zip'), '下载内容为 zip')
    const bytes = (await response.arrayBuffer()).byteLength
    assert(bytes > 10000, `zip ${Math.round(bytes / 1024)} KB`)
    assert(successText.includes(`${expectedFrames} 帧`), '完成信息显示帧数')
  }
  document.querySelector('.modal-head .icon-btn').click()
  await waitFor('导出面板关闭', () => !document.querySelector('.modal-overlay.open'))
}

// ---- mount the real app ----------------------------------------------------
const { createServer } = await import('vite')
const { createElement } = await import('react')
const { createRoot } = await import('react-dom/client')

const server = await createServer({
  configFile: './vite.config.ts',
  appType: 'custom',
  logLevel: 'error',
  server: { middlewareMode: true, hmr: false },
})

let exitCode = 0
try {
  step('核心工具函数自检')
  const tl = await server.ssrLoadModule('/src/lib/timeline.ts')
  const fmt = await server.ssrLoadModule('/src/lib/format.ts')
  const sway = await server.ssrLoadModule('/src/lib/sway.ts')
  const dense = Array.from({ length: 600 }, (_, index) => ({
    t: index / 60,
    viseme: index < 30 ? 'closed' : index < 120 ? 'a' : index < 180 ? 'i' : 'closed',
  }))
  assert(tl.findFrameIndex(dense, 0) === 0, '二分查找：首帧')
  assert(tl.visemeAt(dense, 30 / 60) === 'a', '二分查找：dense 60fps 帧切换')
  const blocks = tl.buildVisemeBlocks(dense, 10)
  assert(blocks.length === 4, `dense 帧合并为 ${blocks.length} 个色块`)
  assert(Math.abs(blocks[0].end - 0.5) < 1e-6, '色块边界连续')
  assert(Math.abs(blocks[blocks.length - 1].end - 10) < 1e-6, '末色块延伸到 duration')
  assert(tl.isBlinkActive([{ t: 1, duration: 0.12 }], 1.05) === true, '眨眼事件命中')
  assert(tl.isBlinkActive([{ t: 1, duration: 0.12 }], 1.3) === false, '眨眼事件不越界')
  assert(fmt.formatTimecode(61.5) === '01:01.50', '时间码 mm:ss.cs')
  assert(fmt.formatTimecode(61.5, true, 60) === '01:01:30', '时间码含帧号')
  assert(sway.swayTransform(1, 120, sway.DEFAULT_SWAY).angle === 0, '摇摆关闭时不改变立绘')
  const quarterSway = sway.swayTransform(0.25, 120, { enabled: true, amplitude: 1, frequency: 0.5, offset: 0 })
  assert(Math.abs(quarterSway.angle - Math.PI / 45) < 1e-9, '摇摆按 BPM、频率和幅度计算倾角')
  assert(sway.swayEvents(2, 120, { enabled: true, amplitude: 1, frequency: 0.5, offset: 0 }).length === 3, '摇摆轨按实际周期生成事件')
  assert(sway.swayEvents(2, 120, { enabled: true, amplitude: 1, frequency: 2, offset: 0 }).length === 9, '摇摆轨反映频率倍率')
  assert(Math.abs(sway.swayEvents(2, 120, { enabled: true, amplitude: 1, frequency: 0.5, offset: 0 }, 0.25)[0].t - 0.25) < 1e-9, '摇摆轨跟随音频起点')
  assert(sway.normalizeSway({ enabled: true, amplitude: 4, frequency: 8, offset: 100 }).amplitude === 1, '摇摆参数统一限制到导出范围')

  const appModule = await server.ssrLoadModule('/src/App.tsx')
  const App = appModule.default
  const root = createRoot(document.getElementById('root'))
  root.render(createElement(App))

  // Fast path used to validate backend session restore without a full flow:
  //   $env:MOCADIFF_RESTORE_ONLY="1"; npm run smoke
  if (process.env.MOCADIFF_RESTORE_ONLY === '1') {
    step(`Session 恢复模式（真实后端 ${BACKEND}）`)
    let restoreCode = 0
    try {
      await waitFor(
        '恢复完成',
        () =>
          bodyText().includes('已恢复上次会话') ||
          bodyText().includes('已恢复切换数据源前的项目'),
        60000,
      )
      await waitFor('图层树恢复', () => document.querySelectorAll('.layer-row').length > 4, 30000)
      assert(!!document.querySelector('.multi-timeline-viewport'), '多轨时间轴恢复')
      assert(bodyText().includes('LIVE') || bodyText().includes('真实后端'), '恢复后为真实后端模式')
      assert((document.querySelector('.asset-card')?.textContent ?? '').includes('moca.psd'), 'PSD 资产恢复')
      console.log('\n===== SESSION RESTORE OK =====')
    } catch (error) {
      console.error(error)
      restoreCode = 1
    }
    await server.close()
    process.exit(restoreCode)
  }

  step(`挂载应用 + 空状态 (${REAL ? `真实后端 ${BACKEND}` : 'Mock 数据源'})`)
  await waitFor('app-shell', () => document.querySelector('.app-shell'))
  await waitFor('空状态引导', () => bodyText().includes('舞台等待素材'))
  if (REAL) await waitFor('真实后端模式', () => bodyText().includes('真实后端'))
  assert(bodyText().includes('导入 PSD'), '空状态显示导入引导')
  assert(
    bodyText().includes(REAL ? '真实后端' : 'Mock 数据源'),
    `状态栏显示${REAL ? '真实后端' : 'Mock 数据源'}`,
  )

  step('导出面板前置校验')
  clickButton('导出')
  await waitFor('导出面板打开', () => document.querySelector('.modal-overlay.open'))
  await waitFor(
    '导出禁用提示',
    () => (document.querySelector('.export-banner')?.textContent ?? '').includes('烘焙'),
  )
  assert(byTestId('export-submit').disabled, '未烘焙 / 无时间轴时导出按钮禁用')
  assert(
    document.querySelector('.export-banner').textContent.includes('时间轴') ||
      document.querySelector('.export-problems'),
    '显示可读的导出前置条件提示',
  )
  document.querySelector('.modal-head .icon-btn').click()
  await waitFor('导出面板关闭', () => !document.querySelector('.modal-overlay.open'))

  step('导入 PSD → 图层树')
  const psdBytes = readFileBytes(PSD_PATH)
  setFile('input[accept=".psd"]', makeFile('moca.psd', 'image/vnd.adobe.photoshop', psdBytes))
  await waitFor(
    '图层树加载',
    () => document.querySelector('.asset-card') && document.querySelectorAll('.layer-row').length > 4,
    REAL ? 120000 : 20000,
  )
  assert(document.querySelector('.asset-card').textContent.includes('moca.psd'), '素材卡显示 moca.psd')
  const layerRows = document.querySelectorAll('.layer-row').length
  assert(layerRows > 10, `图层树渲染 ${layerRows} 行（懒展开）`)

  step('自动识别 → 语义槽位')
  clickButton('自动识别')
  await waitFor('映射槽位填充', () => [...document.querySelectorAll('.slot-row select')].filter((select) => select.value).length >= 16)
  const filled = [...document.querySelectorAll('.slot-row select')].filter((select) => select.value).length
  const slotCount = document.querySelectorAll('.slot-row').length
  const channelCount = document.querySelectorAll('.channel-group').length
  assert(slotCount >= 19, `语义槽位已扩展且保留原 19 项（共 ${slotCount} 项）`)
  assert(channelCount >= 6, `基础及叠加通道渲染完成（共 ${channelCount} 组）`)
  assert(bodyText().includes('汗 sweat') && bodyText().includes('眼部效果 eyeEffect'), '显示汗和眼部效果映射')
  assert(filled >= (REAL ? 18 : 16), `自动填充 ${filled} 个槽位`)
  assert(document.body.textContent.includes('置信') || REAL, '显示自动识别置信度')

  step('保存映射')
  clickButton('保存映射')
  await waitFor('保存完成', () => !findButton('保存映射') && bodyText().includes('映射已保存'))
  assert(true, 'PUT 保存完成，脏标记清除')

  step('烘焙 → 舞台 manifest')
  clickButton('烘焙')
  await waitFor('烘焙完成', () => bodyText().includes('烘焙完成'), REAL ? 120000 : 30000)
  assert(document.querySelector('.stage-hud'), '舞台显示 HUD（时间码 / patch 统计）')
  const patchMatch = /(\d+)\s*patches/.exec(document.querySelector('.stage-hud').textContent)
  assert(Boolean(patchMatch) && Number(patchMatch[1]) >= 15, `舞台 HUD 加载 ${patchMatch?.[1]} 个 patch`)
  assert(!document.querySelector('.stage-empty'), '空状态卡片消失，舞台出现立绘')
  const stageCanvas = document.querySelector('.stage-canvas')
  const zoomBefore = document.querySelector('.zoom-label').textContent
  await waitFor('舞台滚轮监听就绪', () => {
    const stageWheel = new window.WheelEvent('wheel', {
      bubbles: true,
      cancelable: true,
      clientX: 450,
      clientY: 310,
      deltaY: -120,
    })
    stageCanvas.dispatchEvent(stageWheel)
    return stageWheel.defaultPrevented
  })
  assert(true, '舞台滚轮缩放由预览接管')
  await sleep(100)
  assert(document.querySelector('.zoom-label').textContent !== zoomBefore, '舞台滚轮更新缩放比例')
  const pointerEvent = (type, x, y) => {
    const event = new window.MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: y })
    Object.defineProperty(event, 'pointerId', { value: 1 })
    return event
  }
  stageCanvas.dispatchEvent(pointerEvent('pointerdown', 450, 310))
  stageCanvas.dispatchEvent(pointerEvent('pointermove', 510, 350))
  await sleep(100)
  assert(stageCanvas.classList.contains('panning'), '舞台按下拖拽进入平移状态')
  assert(stageCanvas.dataset.panX !== '0' || stageCanvas.dataset.panY !== '0', '舞台拖拽更新平移位置')
  stageCanvas.dispatchEvent(pointerEvent('pointerup', 510, 350))
  await sleep(100)
  assert(!stageCanvas.classList.contains('panning'), '舞台松开后结束平移')
  stageCanvas.dispatchEvent(new window.MouseEvent('dblclick', { bubbles: true }))
  await sleep(100)
  assert(
    document.querySelector('.zoom-label').textContent === '100%' && stageCanvas.dataset.panX === '0' && stageCanvas.dataset.panY === '0',
    '舞台双击复位缩放和平移',
  )

  if (!REAL) {
    step('导入 SVP → 选择 track5 → 生成时间轴')
    const svpBytes = readFileBytes(SVP_PATH)
    setFile('input[accept=".svp"]', makeFile('流沙.svp', 'application/octet-stream', svpBytes))
    await waitFor('轨道列表', () => document.querySelectorAll('.track-row').length === 6)
    assert(document.querySelector('.svp-panel').textContent.includes('未命名音轨 5'), '轨道列表包含 track 5')
    const trackFive = [...document.querySelectorAll('.track-row')].find((row) => row.textContent.includes('未命名音轨 5'))
    trackFive.click()
    await waitFor('track 5 选中', () => trackFive.getAttribute('aria-checked') === 'true')
    assert(true, 'track 5 单选选中')
    clickButton('生成时间轴')
    await waitFor('时间轴生成', () => document.querySelector('.timeline-summary'), 20000)
    assert(bodyText().includes('眨眼'), '时间轴摘要显示眨眼标记数')
    assert(document.querySelector('.multi-timeline-viewport canvas'), '多轨时间轴 canvas 渲染')
    assert(document.querySelector('.timeline-ruler'), '时间标尺独立渲染')
    assert(
      document.querySelector('.multi-timeline-viewport')?.getAttribute('aria-label')?.includes('SVP 原始数据'),
      '来源轨与动画轨分组显示',
    )
    const ctrlWheel = new window.WheelEvent('wheel', {
      bubbles: true,
      cancelable: true,
      ctrlKey: true,
      clientX: 500,
      deltaY: -120,
    })
    document.querySelector('.multi-timeline-viewport').dispatchEvent(ctrlWheel)
    assert(ctrlWheel.defaultPrevented, 'Ctrl+滚轮由时间轴接管，不触发页面缩放')
    const densityGroup = document.querySelector('.timeline-head-actions .segmented')
    assert(densityGroup?.textContent.includes('紧凑'), '轨道高度与全览同排')
    densityGroup.querySelectorAll('button')[2].click()
    await sleep(120)
    assert(densityGroup.querySelectorAll('button')[2].classList.contains('active'), '轨道高度切换生效')

    step('导入音频 → 波形 / BPM')
    setFile('input[accept*="audio"]', makeFile('流沙.wav', 'audio/wav'))
    await waitFor('音频面板', () => bodyText().includes('流沙.wav') && document.querySelector('.audio-wave canvas'))
    const bpmInput = [...document.querySelectorAll('.audio-controls input[type="number"]')][0]
    assert(bpmInput && bpmInput.value === '76', `BPM 自动填入 ${bpmInput?.value}`)
    const offsetInput = [...document.querySelectorAll('.audio-controls input[type="number"]')][1]
    assert(offsetInput, '音频起点输入框存在')
    setNativeInput(offsetInput, '-2.5')
    await sleep(150)
    assert(offsetInput.value === '-2.5', '音频起点支持负值（-2.5s）')
    setNativeInput(offsetInput, '0')
    await sleep(100)
    assert(bodyText().includes('音频起点'), '显示音频起点说明')
    const swayControls = document.querySelector('.sway-controls')
    const swayToggle = swayControls?.querySelector('input[type="checkbox"]')
    assert(swayControls && swayToggle && !swayToggle.checked, '显示独立摇摆控制且默认关闭')
    swayToggle.click()
    await sleep(100)
    assert(swayToggle.checked && bodyText().includes('频率 (次/拍)') && bodyText().includes('偏移 (拍)'), '摇摆支持幅度、频率和偏移调节')
    assert(document.querySelector('.multi-timeline-viewport canvas'), '启用摇摆后独立时间轴轨保持渲染')

    step('播放 → 时间轴时钟推进')
    const before = document.querySelector('.transport-tc').textContent
    document.querySelector('.play-btn').click()
    await sleep(1400)
    const after = document.querySelector('.transport-tc').textContent
    assert(after !== before && after !== '00:00:00', `播放头推进 ${before} → ${after}`)
    document.querySelector('.play-btn').click()

    await runExportFlow({ label: 'Mock', durationSeconds: 1, expectMock: true })

    step('图层可见性 → 即切即显 / 冻结与互斥')
    const frozenRow = document.querySelector('.layer-row.frozen')
    assert(frozenRow && frozenRow.querySelector('.layer-lock') && !frozenRow.querySelector('.layer-eye'), '自动驱动图层在树中冻结')
    const rowCount = document.querySelectorAll('.layer-row').length
    document.querySelector('.layer-row:not(.frozen) .layer-eye').click()
    await sleep(150)
    assert(document.querySelector('.stage-hud'), '切换静态图层后预览仍在')
    assert(!document.querySelector('.stage-stale'), '静态图层切换不再需要重新烘焙')
    assert(document.querySelectorAll('.layer-row').length === rowCount, '切换可见性不折叠图层树')

    const groupRow = [...document.querySelectorAll('.layer-row')].find((row) => row.querySelector('.layer-exclusive'))
    assert(Boolean(groupRow), '组内互斥开关可用')
    const exclusive = groupRow.querySelector('.layer-exclusive')
    exclusive.click()
    await sleep(80)
    assert(exclusive.classList.contains('on'), '组内互斥已开启')
    const wrapper = groupRow.parentElement
    const childRows = [...wrapper.children]
      .slice(1)
      .map((child) => child.querySelector(':scope > .layer-row'))
      .filter((row) => row && row.querySelector('.layer-eye'))
    assert(childRows.length >= 2, '互斥组内至少有两个可切换图层')
    const [first, second] = childRows
    if (!second.querySelector('.layer-eye').classList.contains('off')) {
      second.querySelector('.layer-eye').click()
      await sleep(80)
    }
    second.querySelector('.layer-eye').click()
    await sleep(120)
    assert(first.querySelector('.layer-eye').classList.contains('off'), '互斥显示时自动隐藏同组其它图层')

    step('映射修改 → 贴图待更新并拦截导出')
    const defaultSelect = document.querySelector('.default-grid .select')
    const alternative = defaultSelect ? [...defaultSelect.options].find((option) => option.value !== defaultSelect.value) : null
    assert(Boolean(alternative), '默认状态可选值存在')
    defaultSelect.value = alternative.value
    defaultSelect.dispatchEvent(new window.Event('change', { bubbles: true }))
    await waitFor('贴图待更新标记', () => Boolean(document.querySelector('.stage-stale')))
    assert(Boolean(document.querySelector('.stage-hud')), '映射修改后预览仍在')
    clickButton('导出')
    await waitFor('过期导出拦截', () => (document.querySelector('.export-problems')?.textContent ?? '').includes('过期'))
    assert(true, '贴图过期时禁止导出')
    document.querySelector('.modal-head .icon-btn').click()
    await waitFor('导出面板关闭', () => !document.querySelector('.modal-overlay.open'))

    step('Mock / 真实后端一键切换')
    document.querySelector('.mock-switch').click()
    await waitFor('切换回真实后端', () => bodyText().includes('真实后端') && !document.querySelector('.asset-card'))
    assert(true, '切换数据源并重置素材')
    document.querySelector('.mock-switch').click()
    await waitFor('切换回 mock', () => bodyText().includes('Mock 数据源'))
  } else {
    step('真实 PSD 资产 / media 校验')
    const psdId = readAssetId('PSD')
    assert(psdId, `状态栏解析 PSD assetId=${psdId}`)
    const manifest = await fetchJson(`/api/psd/${psdId}/manifest`)
    const patchKeys = Object.keys(manifest.patches ?? {})
    assert(patchKeys.length === 19, `manifest 含 ${patchKeys.length} 个 patch`)
    const baseResponse = await globalThis.fetch(manifest.base.url)
    assert(
      baseResponse.ok && (baseResponse.headers.get('content-type') ?? '').includes('image/png'),
      'base.png 可访问（image/png）',
    )
    const baseBytes = (await baseResponse.arrayBuffer()).byteLength
    assert(baseBytes > 200000, `base.png ${Math.round(baseBytes / 1024)} KB`)
    const firstPatch = await globalThis.fetch(manifest.patches[patchKeys[0]].url)
    assert(firstPatch.ok, `patch ${patchKeys[0]} 可访问`)

    step('真实 SVP → 选 track5 → 生成时间轴')
    const svpBytes = readFileBytes(SVP_PATH)
    setFile('input[accept=".svp"]', makeFile('流沙.svp', 'application/octet-stream', svpBytes))
    await waitFor('轨道列表', () => document.querySelectorAll('.track-row').length === 6, 120000)
    const trackRows = [...document.querySelectorAll('.track-row')]
    assert(trackRows.length === 6, '后端返回 6 条轨道')
    const trackFiveRow = trackRows.find((row) => /未命名音轨\s*5/.test(row.textContent)) ?? trackRows[4]
    trackFiveRow.click()
    await waitFor('track5 选中', () => trackFiveRow.getAttribute('aria-checked') === 'true')
    assert(true, '选中 track5（未命名音轨 5）')
    clickButton('生成时间轴')
    await waitFor('时间轴生成', () => document.querySelector('.timeline-summary'), 180000)
    const timelineSummary = document.querySelector('.timeline-summary').textContent.replace(/\s+/g, ' ')
    const frameMatch = /(\d+)\s*帧/.exec(timelineSummary)
    assert(frameMatch && Number(frameMatch[1]) > 10000, `时间轴 ${frameMatch?.[1]} 帧`)
    assert(/眨眼/.test(timelineSummary), '时间轴显示眨眼事件')
    assert(document.querySelector('.multi-timeline-viewport canvas'), '多轨时间轴 canvas 渲染')
    assert(document.querySelector('.timeline-ruler'), '时间标尺独立渲染')

    step('真实时间轴数据 / 渲染性能')
    const svpId = readAssetId('SVP')
    assert(svpId, `状态栏解析 SVP assetId=${svpId}`)
    const svpInfo = await fetchJson(`/api/svp/${svpId}`)
    const trackInfo = svpInfo.tracks.find((track) => track.index === 4) ?? svpInfo.tracks[4]
    const timelineResponse = await (
      await globalThis.fetch(`/api/svp/${svpId}/timeline`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trackIndex: trackInfo.index, fps: 60 }),
      })
    ).json()
    const realTimeline = timelineResponse.timeline
    assert(
      realTimeline.frames.length > 14000,
      `后端时间轴 ${realTimeline.frames.length} 帧 / ${realTimeline.duration.toFixed(2)}s`,
    )
    assert(realTimeline.duration > 230 && realTimeline.duration < 250, `duration=${realTimeline.duration}`)
    const mergeStart = performance.now()
    const mergedBlocks = tl.buildVisemeBlocks(realTimeline.frames, realTimeline.duration)
    const mergeMs = performance.now() - mergeStart
    assert(
      mergedBlocks.length > 50 && mergedBlocks.length < 1500,
      `口型色块合并为 ${mergedBlocks.length} 段（${mergeMs.toFixed(2)}ms）`,
    )
    const lookupStart = performance.now()
    for (let i = 0; i < 2000; i += 1) tl.visemeAt(realTimeline.frames, (i / 2000) * realTimeline.duration)
    const lookupMs = performance.now() - lookupStart
    assert(lookupMs < 20, `2000 次 viseme 二分查找 ${lookupMs.toFixed(2)}ms`)
    const sampledVisemes = new Set(
      [0.05, 0.2, 0.4, 0.6, 0.8].map((ratio) => tl.visemeAt(realTimeline.frames, ratio * realTimeline.duration)),
    )
    assert(sampledVisemes.size >= 2, `全曲抽样存在口型变化：${[...sampledVisemes].join('/')}`)
    assert(timelineResponse.blinks.length > 30, `眨眼事件 ${timelineResponse.blinks.length} 个`)

    step('真实音频 → peaks / BPM 保存')
    const audioBytes = readFileBytes(AUDIO_PATH)
    assert(audioBytes, `测试音频存在：${AUDIO_PATH}`)
    setFile('input[accept*="audio"]', makeFile('test.wav', 'audio/wav', audioBytes))
    await waitFor('音频面板', () => bodyText().includes('test.wav') && document.querySelector('.audio-wave canvas'), 120000)
    const audioId = readAssetId('AUD')
    assert(audioId, `状态栏解析 audio assetId=${audioId}`)
    const peaksResponse = await fetchJson(`/api/audio/${audioId}/peaks?points=1200`)
    assert(Array.isArray(peaksResponse.peaks) && peaksResponse.peaks.length === 1200, `peaks ${peaksResponse.peaks.length} 点`)
    const bpmInput = [...document.querySelectorAll('.audio-controls input[type="number"]')][0]
    assert(bpmInput && bpmInput.value !== '', `BPM 自动检测填入 ${bpmInput?.value}`)
    setNativeInput(bpmInput, '76')
    await sleep(120)
    const saveButton = [...document.querySelectorAll('button')].find(
      (button) => button.textContent.trim() === '保存' && !button.disabled,
    )
    assert(saveButton, 'BPM 保存按钮可用')
    saveButton.click()
    await waitFor('BPM 保存完成', () => bodyText().includes('BPM 已保存'), 30000)
    assert(true, 'PUT /api/audio/{id}/bpm 成功')

    step('真实播放 → 时钟推进 / UI 同步')
    const beforeTime = document.querySelector('.transport-tc').textContent
    document.querySelector('.play-btn').click()
    await sleep(1600)
    const afterTime = document.querySelector('.transport-tc').textContent
    assert(afterTime !== beforeTime && afterTime !== '00:00:00', `播放头推进 ${beforeTime} → ${afterTime}`)
    const frameLabel = document.querySelector('.state-hero-time em')?.textContent ?? ''
    assert(Number(frameLabel.replace(/\D/g, '')) > 0, `当前状态面板帧号推进（${frameLabel.trim()}）`)
    document.querySelector('.play-btn').click()
    assert(true, '暂停成功')

    await runExportFlow({ label: '真实后端', durationSeconds: 0.5, expectMock: false })
  }

  await sleep(300)
  assert(errors.length === 0, `运行期间无未捕获异常${errors.length ? `：${errors.slice(0, 3).join(' || ')}` : ''}`)
  console.log(`\n===== SMOKE TEST PASSED (${REAL ? 'real backend' : 'mock'}) =====`)
} catch (error) {
  exitCode = 1
  console.error('\n===== SMOKE TEST FAILED =====')
  console.error(error)
  if (errors.length > 0) console.error('runtime errors:', errors.slice(0, 5))
  console.error('body snippet:', bodyText().slice(0, 800))
} finally {
  await server.close()
  process.exit(exitCode)
}
