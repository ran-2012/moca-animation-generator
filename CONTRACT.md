# MocaDiff Studio — 接口与协作契约（v0.1）

> 本文件是前端、后端、AI 三方并行开发的唯一契约。**先读本文件再写代码。**
> 需求源：`requirement.md`（上一轮）；已确认决策：本地访问、先支持 DeepSeek、先单人物、SVP 导入时选择单条轨道、
> 透明导出优先 PNG 序列（FilmCraft 可导入）。

## 0. 范围（MVP）

- 单人物（数据结构支持多人物，但 UI 先做一个）。
- 导入：PSD、音频（wav/mp3/flac/m4a）、SVP。
- PSD：图层树、自动语义映射、手动修正、烘焙 base + patch。
- SVP：选择**单条轨道**生成口型时间轴 + 眨眼事件。
- 音频：波形、BPM（自动检测失败可手填）、音频起点（可负，支持音频从时间轴 0 之前开始）。
- 预览：canvas 2D 合成，音频/动画同步播放。
- 时间轴：口型块 + 眨眼标记 + 播放头；手动调整后续迭代。
- AI：DeepSeek 歌词→情绪/效果初稿；Jev 决策模型→图层/表情选择（先做接口，密钥可选，失败降级）。
- 导出：PNG 序列（alpha）优先，后续 MOV/WebM。

## 1. 技术栈与运行

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | React 19 + TypeScript + Vite | 纯 canvas 2D 预览，不引入重型渲染库 |
| 后端 | FastAPI + Uvicorn | Python 3.13，已装 fastapi 0.129 / uvicorn / pydantic 2 / numpy / Pillow / librosa / httpx / openai |
| PSD | psd-tools 1.25.0（vendored） | `backend/vendor/`，已在 `config.py` 注入 sys.path |
| 编码 | ffmpeg 7.0 | 音频转码/波形/导出 |
| 数据 | 本地 JSON + 文件 | 单用户，无数据库 |

**端口**：后端 `127.0.0.1:8787`，前端 dev `127.0.0.1:5173`（Vite 代理 `/api`、`/media`）。
**只允许本机访问**：后端默认绑定 127.0.0.1，不做鉴权（本地单用户）。
**npm 特殊要求**：本机用户级 npm cache 被沙箱拒绝写入，所有 npm 命令建议先把 cache 指到工作区 `.npm-cache`：

```powershell
$env:npm_config_cache = "<workspace>\.npm-cache"
New-Item -ItemType Directory -Force $env:npm_config_cache | Out-Null
```

## 2. 目录

```
moca-diff/
  CONTRACT.md
  README.md
  backend/
    app/
      main.py            # 由 Lead 维护：CORS、静态挂载、include routers
      config.py          # 由 Lead 维护：路径、端口、vendor
      storage.py         # 由 Lead 维护：目录/JSON/ID/上传落盘
      routers/           # 每个领域一个文件，各自维护
        psd.py  svp.py  audio.py  projects.py  ai.py
      services/          # 业务实现
      models/            # pydantic schema（按领域拆文件）
      ai/                # AI provider 实现
    vendor/              # psd_tools + attrs（不要改）
    tests/
    requirements.txt
  frontend/
    src/ ...
  data/                  # 运行时生成（assets / projects / settings.json / cache）
```

**写作边界（重要，避免冲突）**
- `main.py` / `config.py` / `storage.py` / `CONTRACT.md`：Lead 维护，其他人不要改；需要新路由/挂载先发消息。
- `routers/<domain>.py` + `services/<domain>_service.py` + `models/<domain>.py`：对应负责人维护。
- 所有人只写自己任务里列的路径。

## 3. 通用约定

- 所有 API 前缀 `/api`，JSON 字段 `camelCase`（Pydantic alias 或直接 camel 命名）。
- 失败返回 `{"detail": "人类可读错误"}`，HTTP 4xx/5xx。
- 资产 ID：`uuid4().hex[:12]`，由 `storage.new_id()` 生成。
- 上传：`multipart/form-data`，字段名 `file`；限制 200MB。
- 图片：PNG、RGBA、`Cache-Control: no-store`。
- 时间：秒为 float，帧为整数；timeline JSON 用秒。
- 路径：所有落盘路径必须经 `storage` 的根目录，禁止绝对路径注入。

## 4. 数据模型

### 4.1 LayerNode（PSD 图层树节点）

```json
{
  "id": "63",
  "path": "0.3.1.19.4",
  "name": "あ",
  "kind": "pixel",            // "group" | "pixel"
  "visible": true,             // PSD 自带默认可见性，仅参考
  "bbox": [1171, 727, 1324, 859], // [left, top, right, bottom]，画布坐标
  "width": 153, "height": 132,
  "opacity": 255,
  "blendMode": "normal",
  "children": []               // 仅 group
}
```

根节点 `id="root"`，`children` 为顶层。`layerId` 在同一个 PSD 内稳定（psd-tools `layer.layer_id` 或路径哈希）。

### 4.2 MappingProfile（语义映射，前端可编辑）

```json
{
  "psdAssetId": "a1b2c3d4e5f6",
  "canvas": [2480, 3500],
  "base": {
    "hiddenGroups": ["0.3.1", "0.3.2.0.2", "0.3.3"],
    "hiddenLayers": [],
    "defaultState": { "mouth": "closed", "eyes": "open", "brow": "neutral", "cheek": "normal", "sweat": "off", "eyeEffect": "off" }
  },
  "channels": {
    "mouth": { "a": "63", "i": "62", "u": "61", "e": "60", "o": "59", "n": "42", "closed": "44" },
    "eyes":  { "open": "119", "blink": "?,", "smile": "?", "cry": "?" },
    "brow":  { "neutral": "?", "angry": "?", "question": "?", "surprise": "?", "sad": "?" },
    "cheek": { "normal": "?", "blush": "?", "deep": "?" },
    "sweat": { "single": "?", "double": "?", "neck": "?" },
    "eyeEffect": { "tear": "?", "cry": "?" }
  },
  "mappingSets": { "standard": { "label": "标准", "channels": { "...": "同 channels" } } },
  "defaultMappingSetId": "standard",
  "channelDefinitions": {
    "mouth": { "behavior": "exclusive", "defaultState": "closed" },
    "sweat": { "behavior": "overlay", "defaultState": "off" }
  },
  "zorder": ["cheek", "mouth", "eyes", "brow", "eyeEffect", "sweat"],
  "meta": { "auto": true, "confidence": {"mouth": 0.9}, "warnings": [] }
}
```

`channels` 是当前 Mapping Set 的兼容投影。`mappingSets` 保存方案；切换方案时同步更新 `channels`。`mouth.a/i/u/e/o/n/closed` 与 `eyes.open/blink` 必需，其余可选。`overlay` 通道的 `off` 表示不绘制，不能回退到任意 patch。

### 4.3 BakeManifest（烘焙结果，前端预览直接消费）

```json
{
  "assetId": "a1b2c3d4e5f6",
  "width": 2480, "height": 3500,
  "base": { "url": "/media/psd/a1b2c3d4e5f6/cache/base.png" },
  "patches": {
    "mouth.a": { "url": "/media/psd/.../cache/patch_mouth_a.png", "offset": [1171, 727], "width": 153, "height": 132 },
    "mouth.closed": { ... },
    "eyes.open": { ... },
    "eyes.blink": { ... },
    "brow.neutral": { ... },
    "cheek.normal": { ... }
  },
  "zorder": ["cheek", "mouth", "eyes", "brow"],
  "profileVersion": "sha1...",
  "bakedAt": "ISO8601"
}
```

### 4.4 时间轴

```json
{
  "fps": 60,
  "duration": 239.316,
  "mode": { "mappingSetId": "standard", "animationModeId": "natural", "animationModeVersion": 1 },
  "frames": [ { "t": 27.6, "viseme": "a", "openness": 0.95, "mouthPose": "openLarge", "phase": "sustain" } ],
  "sourceTracks": { "notes": [], "phonemes": [], "pitch": [] },
  "tracks": { "mouth": [], "blink": [], "eyes": [], "brow": [], "cheek": [], "sweat": [], "eyeEffect": [] },
  "source": { "kind": "svp", "assetId": "...", "trackIndex": 5 }
}
```

```json
{
  "blinks": [ { "t": 2.0, "duration": 0.15 } ],
  "emotions": [ { "start": 27.6, "end": 32.0, "mood": "bright", "intensity": 0.7 } ]
}
```

viseme 枚举：`closed | n | f | a | i | u | e | o`。

动画模式：`classic | clear | natural | expressive`。`classic` 保留旧 `frames` 形状；其他模式用 `mouthPose` 表示辅音、起势、音高开度和收势姿态。`frames` / `blinks` 是兼容字段，预览和导出优先消费 `mouthPose` / `tracks`，缺失时回退到旧字段。

### 4.5 Project

```json
{
  "id": "p_xxx", "name": "未命名项目",
  "fps": 24, "width": 1080, "height": 1524,
  "createdAt": "ISO8601", "updatedAt": "ISO8601",
  "audio": { "assetId": "...", "bpm": 76.0, "offsetSec": 0.0, "durationSec": 242.6 },
  "characters": [{
    "id": "c_1", "name": "moca",
    "psdAssetId": "...", "profile": { "…MappingProfile…" },
    "transform": { "x": 0, "y": 0, "scale": 1.0, "rotation": 0.0, "opacity": 1.0 },
    "zIndex": 0
  }],
  "timeline": {
    "characterId": "c_1",
    "mouth": { "assetId": null, "trackIndex": null, "fps": 60, "frames": [] },
    "blinks": [],
    "emotions": [],
    "effects": []
  }
}
```

## 5. API

### 5.1 健康

`GET /api/health` → `{ "ok": true, "version": "0.1.0" }`

### 5.2 PSD（负责人：backend-psd）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/psd/upload` | multipart `file` | `{assetId, filename, width, height, dpi, layerCount, groupCount}` |
| GET | `/api/psd/{assetId}/tree` | — | `LayerNode`（root） |
| GET | `/api/psd/{assetId}/thumb/{layerId}?size=160` | — | PNG（RGBA，等比缩到 size 内） |
| GET | `/api/psd/{assetId}/preview?width=900` | — | PNG（当前/自动映射的基准合成预览） |
| POST | `/api/psd/{assetId}/automap` | — | `{ "profile": MappingProfile, "warnings": [...] }` |
| PUT | `/api/psd/{assetId}/profile` | MappingProfile | `{ "ok": true }`（持久化，供 bake 使用） |
| POST | `/api/psd/{assetId}/bake` | `{ "profile": MappingProfile? }` | `BakeManifest`；同步执行，10–30s，前端显示 loading |
| GET | `/api/psd/{assetId}/manifest` | — | 已缓存的 `BakeManifest` 或 404 |

烘焙产物写到 `data/assets/psd/<assetId>/cache/`，通过 `/media` 静态访问。

### 5.3 SVP / 音频（负责人：backend-svp）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/svp/upload` | multipart `file` | `{assetId, filename, version, tracks:[TrackInfo], warnings}` |
| POST | `/api/svp/{assetId}/timeline` | `{trackIndex, fps=60, psdAssetId?, mappingSetId="standard", animationModeId="natural"}` | `{timeline, blinks, stats, warnings}` |
| POST | `/api/audio/upload` | multipart `file` | `AudioSummary` |
| GET | `/api/audio/{assetId}/peaks?points=2000` | — | `{points, peaks:[0..1]}` |
| PUT | `/api/audio/{assetId}/bpm` | `{bpm:float, offsetSec:float=0}` | `{ok:true}` |
| GET | `/api/audio/{assetId}/file` | — | 音频流（支持 Range） |

**音频位置语义（2026-10 更新）**：`offsetSec` / 前端 `offset` 表示**音频起点在时间轴上的位置**（秒，可为负）。

- `audioTime = timelineTime - offsetSec`；
- `offsetSec = -2.5`：音频从时间轴 0 秒之前 2.5 秒开始（前 2.5 秒在时间轴之外被裁掉）；
- `offsetSec = +3.0`：音频从时间轴 3 秒处开始，前 3 秒静音（无音频）；
- 时间轴长度 = `max(SVP/时间轴时长, offsetSec + audioDuration)`；
- 时间轴与紧凑波形都按该位置绘制，BPM 节拍网格以音频起点对齐；
- 负数完全合法，后端 `BpmUpdate.offset_sec` 不做非负限制。

`TrackInfo`：
```json
{ "index": 4, "name": "未命名音轨 5", "isInstrumental": false,
  "noteCount": 435, "rangeStartSec": 15.79, "rangeEndSec": 238.82,
  "groups": [{"name": "Vocal-Chorus_R", "noteCount": 12}] }
```
**SVP 只允许单轨**：`trackIndex` 必填，后端不得自动合并多轨（这是本期明确需求）。

### 5.4 项目（负责人：backend-psd）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/projects` | `{name}` | `Project` |
| GET | `/api/projects` | — | `[{id,name,updatedAt}]` |
| GET | `/api/projects/{id}` | — | `Project` |
| PUT | `/api/projects/{id}` | `Project` | `Project` |
| DELETE | `/api/projects/{id}` | — | `{ok:true}` |

### 5.5 AI（负责人：ai）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/settings` | — | `{deepseek:{baseUrl,model,hasKey}, openrouter:{model,hasKey}}` |
| PUT | `/api/settings` | `{deepseek?:{baseUrl?,model?,apiKey?}, openrouter?:{apiKey?,model?}}` | 脱敏后的设置 |
| POST | `/api/ai/analyze-lyrics` | `{lines:[{text,start,end}], bpm?, style?}` | `{segments:[{start,end,mood,intensity,effects:[{type,params}]}]}` |
| POST | `/api/ai/decide-layers` | `{state:object, candidates:{eyes:[],brow:[],mouth:[]}}` | `{choices:{eyes?,brow?,mouth?}, confidence:{...}, raw?}` |

DeepSeek：OpenAI 兼容 `https://api.deepseek.com`，模型默认 `deepseek-chat`；Jev：OpenRouter `POST /api/v1/systemone`，模型 `typesafe/jev-1.13`。**无密钥时不要报 400/500**：`analyze-lyrics` 返回 `provider:"rule"` 的规则结果（200），`decide-layers` 返回规则选择（200），并附 `warnings`。只有显式要求且配置异常时才返回可读 4xx。后端 HTTP 调用使用 Python 标准库 `urllib`（本机 httpx/openai 版本与 Python 3.13 不兼容，不要依赖）。

### 5.6 渲染 / 导出（负责人：render-export）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/api/render` | `RenderRequest`（见下） | `RenderJobInfo` |
| GET | `/api/render/{jobId}` | — | `RenderJobInfo`（含 progress/fileUrl） |
| GET | `/api/render/{jobId}/download` | — | 文件（zip/mov/webm/mp4） |

```json
{
  "psdAssetId": "a1b2c3d4e5f6",
  "timeline": {
    "fps": 60, "duration": 239.3,
    "frames": [{"t": 0.016, "viseme": "a", "mouthPose": "openLarge"}],
    "tracks": {"sweat": [{"t": 8.0, "state": "single"}, {"t": 9.0, "state": "off"}]}
  },
  "blinks": [{"t": 2.0, "duration": 0.15}],
  "startSec": 27.6, "durationSec": 10.0,
  "outFps": 24, "width": 1080,
  "format": "png_zip",           // png_zip | prores4444 | webm_alpha | mp4
  "background": "#101010",       // 仅 mp4
  "brow": "neutral", "cheek": "normal",
  "sway": {"enabled": true, "amplitude": 0.35, "frequency": 0.5, "offset": 0.0, "bpm": 76.0, "audioStart": 0.0}
}
```

- 依赖已 bake 的 PSD manifest（base + patches）；未 bake 返回 400 可读提示。
- 限制：宽度 200–2480、单次 ≤6000 帧、时长 ≤300s。
- `png_zip` 为 RGBA PNG 序列（FilmCraft 首选）；`prores4444` 为带 alpha 的 MOV；`webm_alpha` 为 VP9 alpha；`mp4` 铺背景色。
- 后台线程渲染，同一时间 1 个任务；`GET` 轮询进度。
- 导出按 `mouthPose → viseme → defaultState` 选择口型，并按时间采样动画轨。叠加通道状态为 `off` 时不绘制。
- `sway` 为可选节奏变换：`amplitude` 为 `0..1` 强度（最大约 4° 左右倾角、2% 纵向拉伸），`frequency` 为每拍循环次数，`offset` 为节拍偏移，`bpm` 与 `audioStart` 用于预览、时间轴和导出采用同一相位公式。启用后围绕立绘底部中心变换，透明画布尺寸不变。

### 5.7 音频 BPM 说明（补充）

- 本机 `librosa` 的 numba 依赖在 Python 3.13 下 import 可能死锁，实现采用「短命子进程 + 6s 超时」，失败时用 numpy onset 自相关兜底，字段 `bpmSource` 标明来源；短音频（<20s）可返回 `bpm:null`（`skipped-short-audio`），前端允许手填。

### 5.8 Session 持久化（负责人：Lead）

页面刷新后恢复上次工作区。后端把前端快照落到 `data/session.json`（原子写），前端在关键状态变化后 debounce 700ms 保存、页面隐藏/关闭时用 `keepalive` 补存一次；同时写一份 `localStorage` 镜像作为后端离线兜底。

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/session` | — | `{session: SessionState \| null, savedAt}` |
| GET | `/api/session/previous` | — | `{session: SessionState \| null, savedAt}` 切换数据源前的项目备份 |
| PUT | `/api/session` | `SessionState`（camelCase） | `{ok:true, savedAt}` |
| DELETE | `/api/session` | — | `{ok:true}` |

**LIVE/MOCK 切换保护**：每次 `PUT` 前，若已保存的项目即将被空快照或另一种 `mockMode` 的快照覆盖，后端先把它写进 `data/session.prev.json`；`DELETE` 会同时清掉备份。前端切换数据源时还会把两种模式各自的最新快照存入 `localStorage`，切换后通过 `mocadiff.pendingRestore` 恢复目标模式的项目。若启动时当前会话为空，前端会尝试 `/api/session/previous` 自动恢复上一项目。

`SessionState` 只存**引用与 UI 状态**，不重复存大对象：

```json
{
  "version": 1, "projectName": "未命名项目", "mockMode": false, "time": 27.6,
  "psd": {"assetId": "...", "filename": "moca.psd", "width": 2480, "height": 3500, "...": "..."},
  "profile": {"...MappingProfile...": "..."},
  "hiddenGroups": ["0.3.1"], "hiddenLayers": [], "selectedLayerId": "63",
  "svp": {"assetId": "...", "tracks": ["..."]}, "selectedTrack": 5, "fps": 60,
  "mappingSetId": "standard", "animationModeId": "natural",
  "timelineView": {"start": 0.25, "span": 0.5},
  "audio": {"assetId": "...", "durationSec": 242.6}, "bpm": 76.0, "offset": 0.0,
  "sway": {"enabled": true, "amplitude": 0.35, "frequency": 0.5, "offset": 0.0}
}
```

恢复流程：读取 session → 用 `psd.assetId` 重新拉 tree/manifest → 用 `svp.assetId + selectedTrack + fps` 重新生成（命中磁盘缓存）时间轴/眨眼 → 用 `audio.assetId` 重新拉 peaks → 恢复时间/BPM/偏移。因此不把 1.7MB 时间轴和图层树塞进 session 文件。

## 6. 前端

- 路由：单页（暂不引入 react-router）。
- 状态：`useState/useReducer` + 一个 `api.ts`；不引入状态库。
- 布局：顶部工具栏 / 左侧图层与映射 / 中间舞台 / 右侧时间轴与属性 / 底部状态栏。
- 舞台：`<canvas>`，2D 合成：
  1. 按 `BakeManifest` 加载 base 与 patches（`Image`）；
  2. 计算 `t` 的 viseme / blink / brow / cheek；
  3. 按 zorder 绘制 base + patch（`drawImage`，offset 按预览缩放）；
  4. 支持 fit 缩放、背景棋盘格。
- 播放：`requestAnimationFrame` + `performance.now`；有音频且当前时间落在 `[offset, offset+audioDuration]` 内时以音频时钟为准（`audio.currentTime + offset`），否则用性能时钟；音频可延迟进入或在负时间开始。
- 时间轴：固定标尺 + 可纵向滚动的多轨 Canvas；分组显示 SVP 音符/音素/音高、口型/眨眼/眼睛/眉毛/脸颊/汗/眼部效果/摇摆和音频波形。
- 时间轴交互：`Ctrl+滚轮` 横向缩放、`Shift+滚轮` 横向平移、`Alt+滚轮` 调整轨高；工具栏提供紧凑/标准/展开；分组可折叠。音频波形可拖动调整音频起点。
- 空状态处理：未导入 PSD/音频/SVP 时界面仍可用，给出下一步引导。
- 视觉：深色工作室风；CSS 变量；不使用组件库（减少网络依赖）。
- 必须支持：PSD 自动映射结果展示/修改/保存；SVP 轨道下拉（显示名称/音符数/时长）+ 生成；BPM 输入。
- 构建：`npm run build` 输出 `frontend/dist`，FastAPI 会在存在时挂载。

## 7. 测试与验收（本期）

- 后端 `pytest`：PSD 树解析（moca.psd）、automap 检出 a/i/u/e/o/n/blink、bake 产物存在、SVP 单轨时间轴生成、音频 peaks/BPM、项目 CRUD、渲染 4 种格式。
- 前端手工验收：导入 `moca.psd` → 自动映射 → 烘焙 → 舞台出现立绘；导入 `流沙.svp` → 选一条轨道 → 时间轴出现口型；导入音频 → 波形/BPM；播放同步；导出 PNG 序列/ProRes 4444。
- 已实现：导入、映射、烘焙、单轨 SVP、音频、同步预览、AI 后端、透明导出。
- 下一阶段：时间轴手动关键帧编辑、AI 效果实际渲染（推拉/节拍/呼吸）、多人物 UI、图层级变换动画、DeepSeek/Jev 的 UI 面板。

## 8. 关键实现提示

- PSD：`psd_tools` 的 `layer.topil()` 返回裁剪图；贴图用 `layer.offset`。组可见性不级联，切换前先开父组。
- 烘焙性能：`psd.composite(ignore_preview=True)` 大图约 8–11s，只做一次；不要逐帧 composite。
- SVP：`绝对tick = note.onset + groupRef.blickOffset`；tick/705600000 = 四分音符；优先复用 `_work/svp/svp2viseme.py`。
- 音频：librosa 检测 BPM 可能慢，放在请求里需控制时长（先试 `librosa.beat.beat_track`），失败返回 null；前端允许手填。
- 所有生成 JSON 使用 UTF-8、`ensure_ascii=False`。
