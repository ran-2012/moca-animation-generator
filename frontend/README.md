# MocaDiff Studio — Frontend

React 19 + TypeScript + Vite 8 single-page studio UI for the MocaDiff PSD
differential / SVP lip-sync workflow. Dark studio layout: top bar, layer tree +
mapping (left), canvas stage (center), timeline / SVP / audio / state (right),
status bar (bottom).

## 运行

```powershell
# 依赖（本机 npm 缓存被沙箱拒绝写 %LOCALAPPDATA%，必须先改到工作区）
$env:npm_config_cache = "C:\Users\ran\Desktop\images\moca\.npm-cache"
New-Item -ItemType Directory -Force $env:npm_config_cache | Out-Null
cd C:\Users\ran\Desktop\images\moca\moca-diff\frontend
npm install --ignore-scripts --no-audit --no-fund

# 开发（http://127.0.0.1:5173，Vite 代理 /api、/media → 127.0.0.1:8787）
npm run dev

# 构建（输出 frontend/dist，FastAPI 在存在 dist 时会挂载到 /）
npm run build
npm run preview

# 无浏览器冒烟测试（jsdom 内挂载真实 App，走完整 mock 流程）
npm run smoke

# 对真实后端跑完整流程（PSD→automap→bake→舞台、SVP track5 时间轴、音频 peaks/BPM/播放）
# 需要一段测试音频（任意 wav）：默认读 .tmp-audio/test.wav，可用 MOCADIFF_AUDIO 指到别处
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=20" -ar 44100 -ac 1 .tmp-audio/test.wav
$env:MOCADIFF_REAL="1"; $env:MOCADIFF_BACKEND="http://127.0.0.1:8787"; npm run smoke
```

真实后端冒烟会额外校验：manifest 19 patches、`/media` 的 base.png/patch PNG 可访问、
SVP 14359 帧 / 239.32s / 67 blinks、色块合并段数与二分查找耗时、`PUT bpm`、播放时钟推进，
以及**真实导出**（提交 `POST /api/render` → 轮询 → 下载 PNG zip 并校验 content-type/大小）。
最近一次（2026-10-20，8787 真实后端）全部通过。

后端联调：

```powershell
cd C:\Users\ran\Desktop\images\moca\moca-diff\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

## 沙箱适配（重要）

本机沙箱禁止 Node 用管道 stdio `spawn` 子进程（`spawn EPERM`），esbuild 的
service 进程因此无法启动。为了在这台机器上 `npm run build` / `npm run dev`
可用，前端使用 **Vite 8**（rolldown/oxc，进程内完成 TS/JSX 转换，不依赖
esbuild），并通过 `scripts/child-process-shim.cjs` 拦截 Vite 仅用于探测
Windows 网络盘的 `exec("net use")`（非必要调用）。npm scripts 已经用
`node --require ./scripts/child-process-shim.cjs .../vite.js` 包装，无需手动处理。
在正常环境（无该限制）中，这个 shim 也是无副作用的。

如果 `npm install` 触发包的 lifecycle 脚本（正常环境不需要），同样加
`--ignore-scripts` 即可：依赖里没有必须在安装期编译的包。

## Mock 数据源

顶栏右侧的 `MOCK / LIVE` 开关一键切换数据源，切换会重置当前素材：

- **MOCK**（默认，无需后端）：`src/mock/` 内置整套 CONTRACT §5 响应 + 用
  canvas 现场绘制的立绘 base/patch（真正的 manifest + `Image` 加载路径，不是
  假预览）、6 条 SVP 轨道（track 5 = `未命名音轨 5`，435 音符）、28 秒口型
  时间轴 + 眨眼、可播放的 WAV（BPM 76）与波形。
- **LIVE**：真实 fetch，路径仍为相对 `/api`、`/media`，由 Vite 代理或
  FastAPI 同源提供。启动时 `GET /api/health` 探测：探测失败自动进入 MOCK，
  用户选择会记在 `localStorage.mocadiff.mock`。

## 使用流程

1. **导入 PSD** → 左侧图层树（可折叠 / 过滤 / 眼睛图标写入
   `base.hiddenGroups`、`base.hiddenLayers`）→ 图层缩略图来自
   `/api/psd/{id}/thumb/{layerId}`。
2. **自动识别** → `POST /api/psd/{id}/automap`，显示口型 / 眼睛 / 眉毛 /
   脸颊四组共 19 个槽位（嘴型 7 个必需），每槽位显示当前层名并可下拉改成任意
   像素层；可改默认状态 `base.defaultState`。
3. **保存映射** → `PUT /api/psd/{id}/profile`；脏标记会在按钮上提示。
4. **烘焙** → `POST /api/psd/{id}/bake`，显示耗时进度（首次约 10–30s），成功
   后按 `BakeManifest` 加载 base + patches 到舞台（`drawImage` 按 offset /
   尺寸缩放，zorder 顺序：cheek → mouth → eyes → brow）。
5. **导入 SVP** → 轨道列表（名称 / 音符数 / 时间范围 / 人声或伴奏）→ 单选轨道
   （伴奏轨生成会得到可读的 400）→ **生成时间轴**
   （`POST /api/svp/{id}/timeline`）→ 时间轴画布显示按 frames 合并的口型色块、
   眨眼标记、BPM 节拍网格、播放头，点击/拖拽 seek。
6. **导入音频** → `POST /api/audio/upload` + `GET /api/audio/{id}/peaks` 波形、
   BPM / 偏移可编辑并 `PUT /api/audio/{id}/bpm` 保存；播放以
   `HTMLAudioElement.currentTime` 为时钟（无音频时 `performance.now()`）。
7. **播放**：顶栏或右侧播放按钮，`requestAnimationFrame` 驱动；空格
   播放/暂停，←/→ 逐秒 seek（Shift 5s），Home 回零。当前 viseme 用二分查找，
   眨眼事件命中时绘制 `eyes.blink`。
8. **导出** → 顶栏「导出」打开面板 → 选格式 / 范围 / fps / 宽度 → 提交
   `POST /api/render` → 轮询 `GET /api/render/{jobId}` 显示进度 → 完成后下载
   `fileUrl`（`GET /api/render/{jobId}/download`）。

## 导出 / Render（CONTRACT §5.6）

顶栏「导出」打开模态面板，仅依赖当前会话里**已烘焙的 manifest + 已生成的时间轴**：

- **格式**：`PNG 序列 (zip)`（RGBA 透明，FilmCraft 首选）、`ProRes 4444 (MOV)`
  （带 alpha，AE / 达芬奇）、`WebM alpha`（VP9+alpha）、`MP4 (H.264)`（无 alpha，
  可设背景色）。后两者与 MP4 的 `background` 只在 MP4 生效。
- **范围**：播放头起 N 秒 / 全曲 / 自定义 start+duration。
- **帧率**：24 / 30 / 60；**宽度**：1080 / 1240 / 1920（高度按 PSD 比例自动算，
  偶数对齐，与后端 `render_service` 规则一致）。
- **表情（可选）**：整段固定 `brow` / `cheek`，默认跟随 profile 的 `defaultState`。
- **校验**：未烘焙 / 无时间轴时禁用并提示；时长 >300s、帧数 >6000、区间超出
  时间轴时给出可读错误并禁用提交（与后端 `_validate()` 一致）。
- **提交与轮询**：`POST /api/render` 返回 `{jobId,status,...}`，前端每 600ms
  `GET /api/render/{jobId}` 更新进度条 / doneFrames / elapsedSec；`done` 后
  展示 `fileUrl` 下载按钮，`failed` 展示 `error`。轮询遇到 404（后端重启丢任务）
  会提示重新提交。关闭面板后轮询继续，完成时弹 toast。
- **透明验证**（本机实测 8787）：PNG zip 12 帧 1080×1524、RGBA、约 60% 全透明背景、
  6.9MB；ProRes4444 12 帧 0.42s，ffprobe `profile=4444 pix_fmt=yuva444p12le`。
- **Mock 模式**：任务为本地模拟（约 0.6–3.2s 走完进度），下载内容是合成好的预览
  PNG（data URL），不代表所选格式；真实格式由后端渲染。

## 目录

```
src/
  api.ts                 # 统一 fetch 封装 + 统一错误 + mock 开关
  types.ts               # CONTRACT §4 数据模型（camelCase）
  App.tsx                # 状态、流程、播放时钟、布局
  components/            # TopBar / LayerTree / MappingPanel / Stage / Timeline /
                         # SvpPanel / AudioPanel / AudioWave / StatePanel / StatusBar /
                         # ExportPanel（渲染导出面板）/ Icons
  lib/                   # 时间码、viseme 查找与色块合并、波形绘制、导出格式/尺寸规则
  mock/                  # mockBackend（§5 响应 + 模拟 render job）/ mockImages（canvas 立绘）
scripts/
  child-process-shim.cjs # 沙箱兼容（见上）
  dom-smoke.mjs          # jsdom 全流程冒烟测试（mock / 真实后端两种模式）
```

## 已知限制（本期范围）

- 导出任务在后端是内存中的线程任务：后端重启后旧 jobId 会 404（前端已提示重新提交）；
  任务列表/历史未做持久化 UI。
- 项目保存/打开未接 `projects` API（新建 = 清空工作区），AI 面板未接。
- Mock 时间轴固定 28 秒、音频为合成 WAV，仅用于无后端时演示；LIVE 模式下
  以真实 SVP/音频时长为准。
- 舞台为 canvas 2D 静态合成 + 每帧 patch 切换；未做 transform 编辑、多人物。
- 沙箱内无法启动浏览器（Chrome 的 mojo 命名管道被拒绝），因此视觉像素级
  回归依赖真实浏览器人工验收；逻辑/流程已由 `npm run smoke` 覆盖。
