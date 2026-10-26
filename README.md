# MocaDiff Studio

自动人物立绘差分动画工具：导入 PSD 立绘、Synthesizer V 工程和音频，自动生成口型 / 眨眼 / 表情 / 节奏效果，在本地预览并导出透明序列帧（PNG / MOV 等），用于在 FilmCraft / 剪辑软件中合成。

> 本地单用户工具，默认只监听 `127.0.0.1`，不上传任何素材到云端（AI 功能可选，需自己填 API Key）。
> 素材授权提醒：`moca.psd` 的 `readme.txt` 限制非商用 / 禁止二次配布，本工具不会打包或分发素材。

---

## 当前状态（v0.1，2026-10-21）

| 模块 | 状态 |
|---|---|
| PSD 上传 / 图层树 / 多方案语义映射 / 烘焙 | ✅ 已完成（扩展口型、眼睛、眉毛、脸颊、汗、眼部效果；bake 缓存） |
| SVP 单轨模式化口型 + 多轨时间轴 | ✅ 已完成（classic / clear / natural / expressive；音符、音素、音高、口型、眨眼等独立轨道） |
| 音频波形 / BPM / 音频起点（可负） | ✅ 已完成（BPM 自动检测 + 手填兜底；支持从负时间开始） |
| 随节奏立绘摇摆 | ✅ 已完成（左右轻摆 + 纵向轻微拉伸；幅度、频率、毫秒级相位偏移可调；独立轨道） |
| React 单页 UI（导入 / 图层映射 / 舞台 / 多轨时间轴 / 音频同步） | ✅ 已完成（纵向滚动、轨高切换、分组折叠、LIVE/MOCK 切换） |
| 透明导出：PNG 序列 / ProRes 4444 / WebM alpha / MP4 | ✅ 已完成（与预览共用 mouthPose 和动画轨状态降级规则） |
| 导出记录管理 | ✅ 已完成（导出面板内列出历史导出，可下载 / 单条删除 / 批量清理） |
| 刷新恢复工作区（Session 持久化） | ✅ 已完成（保存 Mapping Set、动画模式、时间轴视图及分模式快照） |
| 打开历史项目 | ✅ 已完成（顶栏「打开项目」，按素材组合自动记录，最多 50 条） |
| 图层自由调整 | ✅ 已完成（非语义图层烘焙后仍可即时显隐；自动驱动图层冻结；组内互斥） |
| DeepSeek 歌词分析 / Jev 图层决策 | ✅ 后端已完成（无 Key 时规则兜底；UI 面板下一阶段） |
| 时间轴手动调整（关键帧编辑） | ⏳ 下一阶段 |
| AI 效果渲染（镜头推拉 / 节拍弹跳等） | ⏳ 下一阶段（AI 只产出建议数据，尚未进渲染） |
| 多人物同屏 | ⏳ 数据结构已支持，UI 下一阶段 |
| 图层级变换动画（头发/身体摆动） | ⏳ 下一阶段 |

> 当前可用闭环：**导入 PSD → 自动识别并确认映射 → 烘焙 → 导入 SVP 单轨 → 选择映射方案和动画模式 → 生成多轨动画 → 导入音频 → 同步预览 → 导出透明素材**。

## 环境

- Windows 10/11
- Python 3.13（Miniconda，`F:\Program Files\Miniconda\python.exe`）
- Node.js 22 / npm 11
- ffmpeg 7.x（在 PATH，需包含 libx264 / prores_ks / libvpx-vp9）
- Python 依赖：`fastapi`、`uvicorn`、`pydantic`、`numpy`、`Pillow`、`librosa`
  （本机 httpx 0.13.3 / openai 与 Python 3.13 不兼容，后端 AI 改用标准库 `urllib`）
- PSD 解析：`psd_tools 1.25.0`（正常环境 `pip install -r backend/requirements.txt`；原沙箱无法 pip，故本地另有 `backend/vendor/` 兜底，该目录**不纳入 git**，删除不影响已安装依赖的环境）
- 测试：`pytest 9.0.2`；`backend/vendor/` 存在时 `backend\run_tests.ps1` 自动使用它，否则先 `pip install -r backend/requirements-dev.txt`

## 快速开始

```powershell
# 在仓库根目录（本 README 所在目录）执行
.\start.ps1

# 浏览器打开 http://127.0.0.1:5173
```

首次运行会自动：
1. 设置 npm cache 到本目录 `.npm-cache`（绕过沙箱权限问题）；
2. `npm install`（frontend）；
3. 启动 FastAPI `127.0.0.1:8787` 与 Vite `127.0.0.1:5173`。

### 手动启动

```powershell
# 后端
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --reload

# 前端（另一个终端）
cd frontend
npm run dev
```

### VS Code 运行/调试

仓库自带 `.vscode/launch.json` 和 `.vscode/tasks.json`，打开仓库根目录后按 `F5` 选择：

| 配置 | 作用 |
|---|---|
| `Full stack (API + UI)` | 起后端 8787（debugpy）+ Vite 5173，并打开 Chrome，可同时断前/后端 |
| `Backend: API (uvicorn 8787)` | 只调后端（`--reload` 版本另有一项，带 `subProcess` 支持） |
| `Backend: pytest (current file / all)` | 用 debugpy 跑测试 |
| `Frontend: Chrome / Edge (5173)` | 只调前端，会自动先执行 `frontend: vite dev` 任务 |
| `Frontend: smoke (jsdom)` | 直接调试 jsdom 冒烟脚本 |

`Terminal → Run Task` 还可单独运行 `backend: uvicorn`、`frontend: vite dev`、`backend: tests`、`frontend: build`、`frontend: smoke`、`dev: start.ps1`。任务已把 `npm_config_cache` 指到仓库内 `.npm-cache/`。注意 `.vscode/` 整体被忽略，只放行这三个配置文件。

### 生产构建（单端口 8787）

```powershell
.\build.ps1
# 然后只启动后端，FastAPI 会自动托管 frontend/dist：
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
```

## 使用流程（当前可用）

1. 导入 `moca.psd` → 自动识别口型 / 眼睛 / 眉毛 / 脸颊 / 汗 / 眼部效果 → 确认 Mapping Set → 烘焙纹理；烘焙后仍可在图层树中即时切换装饰/备选图层，带锁的自动图层不可手改，组内可开启「互斥」实现单选切换；
2. 导入 `流沙.svp` → 选择一条人声轨道和 `classic / clear / natural / expressive` 模式 → 生成音符、音素、音高与动画轨；
3. 导入音频 → 波形 / BPM / **音频起点（可负）** → 拖动波形或用「对齐播放头」/ ±0.1s 微调 → 可启用“随节奏摇摆”并调整幅度、每拍频率和毫秒偏移（输入框可鼠标左右拖动调节，单击可直接输入） → 播放同步预览；预览舞台支持拖拽平移、光标锚定滚轮缩放和双击复位；时间轴支持独立摇摆轨、纵向滚动、轨高切换、分组折叠、`Ctrl+滚轮` 缩放和 `Shift+滚轮` 平移；
4. （可选）配置 DeepSeek / OpenRouter Key → AI 歌词分析 / Jev 选层建议（后端接口已就绪，UI 面板下一阶段）；
5. 导出 PNG 序列 / ProRes 4444 / WebM alpha / MP4 → 在 FilmCraft 等软件中合成背景视频；导出面板底部「历史导出」可查看 `data/renders/` 里的所有成品，支持下载、单条删除和批量清理（已完成 / 失败 / 全部）。

### 导出格式与 FilmCraft 兼容性

经查 [FilmCraft（openhausfun/filmcraft，MIT/Apache-2.0）](https://github.com/openhausfun/filmcraft) 的格式支持：

| 方向 | 支持的格式 |
|---|---|
| 导入 | PNG / JPEG / GIF / WebP / TIFF / BMP 静帧与图片序列；MP4 / MOV（H.264、HEVC、ProRes 422 Proxy–4444 XQ、DNxHD/DNxHR、MJPEG、VP9、AV1）；MKV/WebM；MXF；TS/PS |
| 导出 | H.264 MP4（AAC）、ProRes 422 HQ MOV、DNxHR MOV、MJPEG MOV、MXF、PNG/TIFF/BMP 图片序列、GIF、WAV |

**结论**：
- FilmCraft 自身导出的 ProRes 是 **422 HQ（无 alpha）**，不能用来做透明素材；
- 本工具导出的 **PNG 序列（RGBA）** 是 FilmCraft 最稳的透明输入（图片序列导入）；
- **ProRes 4444 MOV（带 alpha）** 适合 AE / 达芬奇等；FilmCraft 能解码 4444 XQ，但能否保留 alpha 建议用 1 帧实测；
- WebM VP9 alpha 在本工具导出为 `alpha_mode=1`（ffprobe 可见），适合网页/预览，不一定所有 NLE 支持。

> 导出后端实测：1080×1524 PNG 序列 2s@24fps 48 帧 2.66s（约 28MB）；ProRes 4444 1s 0.63s，`pix_fmt=yuva444p12le`、`profile=4444`；WebM VP9 `alpha_mode=1`；MP4 H.264 正常。
>
> PNG 序列逐帧「合成 + 编码」在线程池里并发（默认用满**全部 CPU 核心**，`MOCADIFF_RENDER_WORKERS` 可覆盖；设为 `1` 退回单线程）。1080p、开启摇摆的 96 帧导出：单线程 25.5s → 现在 ~3.2s（同机 32 核）；关闭摇摆时因为表情状态缓存，96 帧 <1s。
>
> 视频格式（ProRes 4444 / WebM / MP4）同样并发合成帧，再按顺序写入 ffmpeg 管道：1080p + 摇摆的 48 帧 ProRes 从 5.9s 降到 ~2.9s。
> 实际渲染帧预览**不随仓库分发**（角色素材版权限制）；本地运行导出后查看 `data/renders/`，或运行 `python scripts/render_smoke.py`。

### AI：DeepSeek 与 Jev

- **DeepSeek**（`https://api.deepseek.com`，`deepseek-chat`）：分析歌词 → 情绪段落 + 效果建议（`beat_bounce` / `pull` / `shake` / `breath` / `eye_style` / `blush`）。
- **Jev**（TypeSafe 的决策模型，OpenRouter `typesafe/jev-1.13`）：不是聊天模型，而是「给定状态 + 候选选项 → 返回带概率的 choice/score/noul」，适合**自动选择图层/表情**（如给定当前情绪和候选眼型，选一个）。请求走 `POST https://openrouter.ai/api/v1/systemone`。
- 无 Key 时两者都自动降级为**离线规则**，不影响主流程；Key 只存本地 `data/settings.json`，接口只返回 `hasKey`。

## 目录

```
moca-diff/                  ← git 仓库根目录
├─ backend/                 FastAPI 后端
│  ├─ app/                  routers / services / models / ai
│  ├─ tests/                pytest（73 个）
│  ├─ requirements.txt      运行时依赖
│  ├─ requirements-dev.txt  测试依赖
│  ├─ run_tests.ps1
│  └─ vendor/               本地沙箱兜底依赖（git 忽略）
├─ frontend/                React 19 + TS + Vite 8
│  ├─ src/                  UI / 舞台 / 时间轴
│  ├─ scripts/              jsdom 冒烟脚本 + child-process shim
│  ├─ package.json
│  └─ dist/                 构建产物（git 忽略）
├─ docs/                    设计文档、预研报告、导出预览图
│  ├─ technical-plan.md
│  ├─ requirement.md
│  └─ research/
├─ scripts/                 后端端到端 / 渲染验证脚本
├─ data/                    运行时生成：assets / renders / settings.json（git 忽略）
├─ CONTRACT.md              前后端接口与数据契约（开发必读）
├─ build.ps1                前端构建
├─ start.ps1                开发模式一键启动
├─ .gitignore
├─ .gitattributes
└─ .editorconfig
```

## 版本库（Git）

推荐**以 `moca-diff/` 为仓库根目录**，而不是整个素材工作区：

```powershell
cd moca-diff
# 当前目录已经初始化过时跳过这一行；从零创建用：
git init -b main
git add .
git status --short
git commit -m "Initial commit: MocaDiff Studio v0.1"
```

仓库**不包含**：

- `data/`：上传的 PSD/SVP/音频、烘焙缓存、导出视频、Session、API Key；
- `backend/vendor/`：仅为本地沙箱准备的 psd-tools/pytest 副本；
- `frontend/node_modules/`、`frontend/dist/`；
- 角色素材（`moca.psd`、`流沙.svp`、立绘/音频等）——版权归原作者，放在仓库外；
- `_work/`、`pytest-cache-files-*` 等沙箱临时目录。

克隆后：

```powershell
python -m pip install -r backend/requirements.txt
python -m pip install -r backend/requirements-dev.txt
cd frontend; npm install; cd ..
.\start.ps1
```

## AI 设置（可选）

界面右上角“设置”或直接编辑 `data/settings.json`：

```json
{
  "deepseek": { "baseUrl": "https://api.deepseek.com", "model": "deepseek-chat", "apiKey": "sk-..." },
  "openrouter": { "model": "typesafe/jev-1.13", "apiKey": "sk-or-..." }
}
```

- **DeepSeek**：歌词 → 情绪 / 效果初稿；
- **Jev**（OpenRouter `typesafe/jev-1.13`）：在候选图层 / 表情之间做选择（决策模型，不是聊天模型）；
- 不填 Key 时全部走离线规则，功能可用但效果较基础。

## 导出格式说明

目标优先级：

1. **PNG 序列（RGBA）** —— 兼容性最好，FilmCraft 可导入图片序列；
2. **MOV ProRes 4444（alpha）** —— 给 AE / 达芬奇 / 其他后期软件；
3. **WebM VP9 alpha** —— 小体积预览；
4. MP4 H.264 —— 直接带背景的成片。

> 注：FilmCraft 自身导出 ProRes 为 422 HQ（无 alpha），所以透明工程建议从本工具导出 PNG 序列或 ProRes 4444，再交给 FilmCraft 合成。

## 开发

- 契约：`CONTRACT.md`
- 代理开发指引：`AGENTS.md`（环境坑、不变量、验证命令）
- 后端：`backend/app/main.py`（Lead 维护），各领域 router/service 由对应模块负责；
- 前端：`frontend/src/`
- 测试（pytest 已 vendored，直接跑）：

```powershell
cd backend
.\run_tests.ps1
# 或： $env:PYTHONPATH="$PWD\vendor"; python -m pytest tests -q
```

测试数量以 `backend\run_tests.ps1` 的实时输出为准；前端使用 `npm run build` 和 `npm run smoke` 验证。

### 已知限制（本机沙箱环境）

- 本机 `httpx 0.13.3` 与 `openai` 在 Python 3.13 下不可用 → AI 模块用标准库 `urllib`；
- `librosa` 的 numba 依赖可能 import 死锁 → BPM 用「子进程 6s 超时 + numpy 自相关兜底」；
- 沙箱禁止 Node 管道 spawn → 前端使用 Vite 8（rolldown/oxc，无需 esbuild）+ `scripts/child-process-shim.cjs`；不要换回 Vite 6/esbuild；
- 沙箱内无法启动浏览器 → UI 逻辑用 jsdom 冒烟验证，像素级视觉请在真实浏览器打开 5173 / 8787 确认；
- 不要用 `tempfile.mkdtemp` / pytest `tmp_path`（Windows 沙箱 mode 0700 ACL 问题，会生成不可写目录）。

## License

工具代码采用 [MIT License](LICENSE)。

素材不包含在 MIT 授权范围内；请遵循原作者 `readme.txt`，仅限个人非商用使用，禁止二次配布。
