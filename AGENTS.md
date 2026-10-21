# AGENTS.md

MocaDiff Studio 的 AI / 编码代理开发指引。开始改代码前先读：

1. [`README.md`](README.md)：项目状态、运行方式、导出格式、已知限制；
2. [`CONTRACT.md`](CONTRACT.md)：前后端接口与数据契约（跨模块改动必须同步）；
3. 本文件：环境坑、不能破坏的不变量、验证命令。

---

## 1. 项目是什么

本地单用户工具：导入 PSD 人物立绘 + Synthesizer V 工程 + 音频，自动生成口型 / 眨眼 / 表情 / 节奏效果，在浏览器预览并导出透明素材（PNG 序列 / ProRes 4444 / WebM alpha / MP4），最终在 FilmCraft 等剪辑软件合成。

架构：

- **前端**：React 19 + TypeScript + Vite 8，单页应用，`frontend/src/App.tsx` 是主要状态中心。
- **后端**：FastAPI + Python 3.13，`backend/app/main.py` 是入口；`routers/` 传输层，`services/` 业务层，`models/` Pydantic schema。
- **素材**：运行时上传，存放在 `data/assets/{psd,svp,audio}/<assetId>/`，**不纳入 Git**。
- **仓库根目录**：`moca-diff/`（不是外面的素材工作区）。

---

## 2. 快速命令

```powershell
# 仓库根目录
cd moca-diff

# 开发模式：后端 8787 + 前端 5173
.\start.ps1

# 后端测试（优先用本地 vendor，否则用已安装 pytest）
cd backend
.\run_tests.ps1

# 前端类型检查 + 生产构建
cd frontend
npm run build

# UI 冒烟（jsdom，无需真实浏览器）
npm run smoke

# 真实后端 + Session 恢复冒烟
$env:MOCADIFF_REAL="1"; $env:MOCADIFF_RESTORE_ONLY="1"; npm run smoke
```

正常 clone 后如果没有 `backend/vendor/`：

```powershell
python -m pip install -r backend/requirements-dev.txt
cd frontend; npm install; cd ..
```

---

## 3. 每个任务的工作流

1. `git status` 确认工作区干净；不要覆盖用户未提交的改动。
2. 读相关模块 + `CONTRACT.md` 对应章节；涉及 API 形状时先确认契约。
3. 先写最小改动，再补测试/冒烟。
4. 后端行为改动跑 `backend/run_tests.ps1`；前端 UI 改动跑 `npm run build` 和 `npm run smoke`。
5. 修改 API、Session、导出、数据字段时同步更新 `README.md` / `CONTRACT.md`。
6. 只提交代码/文档；不要 `git add ../`（外层是素材工作区）。

提交前检查：

```powershell
cd moca-diff
git status --short
git diff --check
# 确认没有 data/、node_modules/、vendor/、素材或预览图被加入
```

---

## 4. 目录地图

```text
moca-diff/
  AGENTS.md
  README.md / CONTRACT.md
  backend/
    app/
      main.py                 FastAPI 入口、路由注册、静态文件挂载
      config.py               路径、vendor 注入、端口、上传/导出限制
      storage.py              asset id / 目录 / JSON / media URL
      routers/                psd, svp, audio, projects, ai, render, session
      services/               对应业务逻辑
      models/                 Pydantic 请求/响应模型
      ai/                     DeepSeek / Jev / 离线规则
    tests/                    73 个后端测试
    requirements.txt
    requirements-dev.txt
    run_tests.ps1
    vendor/                   本地沙箱兜底依赖（git 忽略）
  frontend/
    src/
      App.tsx                 工作区状态、播放、Session、布局
      api.ts / types.ts       API 封装与共享类型
      components/             TopBar, LayerTree, Stage, Timeline, AudioPanel, ExportPanel...
      lib/                    timeline / waveform / export / format 工具
      mock/                   MOCK 数据源（含合成音频）
    scripts/dom-smoke.mjs     jsdom 冒烟
    scripts/child-process-shim.cjs
  docs/                       技术方案、需求、预研报告（无素材图片）
  scripts/                    e2e_smoke.py / render_smoke.py
  data/                       运行时数据（git 忽略）
```

### 后端入口约定

- 路由统一加 `/api` 前缀；
- `main.py` 中的路由列表是自动 include：新增 `routers/foo.py` 后，把 `"foo"` 加进模块元组；
- 缺失 router 被容忍，但不要依赖这个行为；
- `/media` 映射 `data/assets`，前端静态资源映射 `frontend/dist`（存在时）。

---

## 5. 数据与业务不变量

### PSD

- 烘焙流程：PSD 合成一次 → `base.png` + 每个 slot 的 patch PNG；之后前端合成只做 `drawImage`，**禁止每帧调用 psd-tools composite**。
- `psd.composite()` 必须带 `ignore_preview=True`，否则拿到的是预览图。
- `psd-tools` 的 layer bbox 顺序是 `(left, top, right, bottom)`，与原始 PSD 字段顺序不同。
- 自动映射结果是 `MappingProfile`；moca.psd 的默认槽位见 README。
- 烘焙缓存位于 `data/assets/psd/<assetId>/cache/`，Session 只存 assetId/profile，不存大图。

### SVP

- 时间单位：绝对 tick = `note.onset + groupRef.blickOffset`；705600000 ticks/quarter。
- 每首歌的 BPM 可能不同；`流沙.svp` 当前是 76 BPM 单 tempo。
- 本期只处理**单条轨道**，不做多轨自动合并；`selectedTrack` 为空时不能生成时间轴。
- `notes[].phonemes` 可能为空，按项目实际音素/歌词数据降级处理。

### 音频 / 时间轴

- `offset` / `offsetSec` 表示**音频起点在时间轴上的位置**，可为负：
  - `audioTime = timelineTime - offset`；
  - 负值：音频从 0 秒之前开始（前段被裁掉）；
  - 正值：音频延后进入。
- 播放时：音频活跃区间为 `[offset, offset + audioDuration]`；区间外使用性能时钟，不要每帧写 `currentTime`/反复 `play()`（会造成某些浏览器咔哒/抖动）。
- 时间轴支持滚轮缩放、Shift+滚轮平移、拖音频波形调整起点；这些交互不要被后续布局改动破坏。
- 导出范围以时间轴为准，缩放只影响显示，不影响导出。

### Session

- `data/session.json` 保存引用 + UI 状态；大对象（tree / manifest / timeline）每次重新拉取。
- 写入是原子写；每次写入前如果旧项目将被空快照或另一种 `mockMode` 覆盖，旧项目会备份到 `data/session.prev.json`。
- 前端启动时：当前 Session 为空会尝试 `/api/session/previous` 自动恢复。
- LIVE/MOCK 各自在 `localStorage` 保留快照；切换时通过 `mocadiff.pendingRestore` 恢复目标模式，**不要直接清空并覆盖用户项目**。
- 修改 Session 字段必须同步 `backend/app/models/session.py`、`frontend/src/types.ts`、`App.tsx` 的 build/restore。

### 渲染 / AI

- 导出格式：PNG 序列（RGBA）、ProRes 4444、WebM VP9 alpha、MP4 H.264。
- 上限：300 秒 / 6000 帧；前端与后端都校验。
- AI 后端使用标准库 `urllib`（本机 httpx/openai 不可用）；无 Key 时必须降级到规则结果，返回 200 + warnings，不能阻断主流程。
- Key 只存本地 `data/settings.json`，接口只返回 `hasKey`，不要回传明文 Key。

---

## 6. 本机 / 沙箱环境坑（很重要）

- **npm cache**：沙箱禁止写用户级 npm cache，已把 cache 放到仓库内 `.npm-cache/`（git 忽略）。不要删；`start.ps1` / `build.ps1` 会自动设置。
- **Vite 8 + child-process-shim**：沙箱禁止 Node 管道 spawn，所以 `npm` 脚本用 `scripts/child-process-shim.cjs` 加载 Vite。不要降级到 Vite 6/esbuild，也不要移除 shim。
- **无法启动 Chrome/Playwright**：Mojo named pipe 被拒绝。UI 验证用 `frontend/scripts/dom-smoke.mjs`（jsdom + canvas/ResizeObserver/media stub）。像素级视觉效果需要真实浏览器；如果能用本机浏览器，请打开 5173/8787 验证。
- **禁止 `tempfile.mkdtemp` / pytest `tmp_path`**：Windows 沙箱会生成 mode 0700 的 ACL 锁定目录。临时文件放 `_work/`（已忽略）或 `data/tmp/`。
- **pip 不可用**：原沙箱无法安装 PyPI 包，`backend/vendor/` 是本地兜底；**不要提交 vendor**。正常环境用 requirements。
- **librosa / numba**：import 可能死锁；BPM 检测用「短命子进程 + 6 秒超时 + numpy 自相关兜底」。不要改成在主进程直接 import librosa。
- **httpx**：0.13.3 在 Python 3.13 下无法 import；后端 HTTP 客户端用标准库 `urllib`，不要为了 TestClient 强行升级。
- **ACL 遗留目录**：`backend/tests/plainmode*`、`probe*`、`mode700test*`、`_work/ai-test-*` 是沙箱测试留下的不可读目录，已在 `.gitignore`/`pytest.ini` 排除。不要手工改 ACL，除非用户明确要求。
- **ffmpeg**：在 PATH，包含 libx264 / prores_ks / libvpx-vp9。渲染测试会实际调用它。

---

## 7. 前端注意事项

- `App.tsx` 很大，改状态逻辑前先定位：数据源、Session、播放、布局、素材 handlers。
- 布局用 CSS grid + 可拖动 split handle；timeline 在底部，左右面板可调宽高。相关 localStorage key：`mocadiff.layout.v1`。
- 舞台是 canvas 2D，合成 base + patch；不要引入 WebGL/组件库。
- 时间轴绘制在 `components/Timeline.tsx`；缩放/拖音频/播放头都依赖同一个 view 映射，改动时一起验证。
- 音频面板：音频起点输入、`-0.1/+0.1`、对齐播放头、归零、原始音频来源标签。
- `api.ts` 负责 mock/live 切换；Session API 始终走真实后端。
- TypeScript 是 strict；新增类型放 `types.ts`，不要用 `any` 绕过。
- 新增 UI 文案保持中文；错误用 `notify`，状态栏用 `setStatusText`。

---

## 8. 后端注意事项

- 所有文件路径通过 `config.py` 的 `DATA_DIR` / `ASSETS_DIR` 派生，不要硬编码绝对路径。
- 上传接口限制 200MB；文件名/assetId 必须经过存储层校验，禁止路径穿越。
- PSD/SVP 的耗时段落不要在 async handler 里阻塞事件循环；现有实现使用线程池/子进程，保持这个模式。
- 新增 API 必须补 Pydantic response model（或明确的 dict 契约）并更新 CONTRACT。
- 测试不要删除用户的 `data/session.json`；`tests/test_session.py` 会备份/恢复 Session 文件，保持这个习惯。
- 渲染任务有 `job.json` 持久化；前端轮询任务状态，不要改成同步阻塞请求。

---

## 9. Git / 分发规则

仓库根是 `moca-diff/`，**外层素材目录不属于仓库**。

不要提交：

- `data/`（PSD / SVP / 音频 / 渲染 / Session / settings）；
- `backend/vendor/`、`frontend/node_modules/`、`frontend/dist/`；
- 角色素材、导出帧预览图、demo 视频；
- `docs/preview_*`（角色素材渲染图，已加入 `.gitignore`）；
- `.env`、任何 API Key。

允许提交：`backend/app`、`backend/tests`、`frontend/src`、`frontend/scripts`、构建配置、`docs/*.md`、`scripts/*.py`、README/CONTRACT。

提交前：

```powershell
git diff --check
git status --short
# 确认没有 data/、vendor/、node_modules/、素材或预览图
```

---

## 10. 当前已知未完成项

- 时间轴手动关键帧编辑；
- AI 效果实际进入渲染（当前只产出建议数据）；
- 多人物同屏 UI（数据结构已支持）；
- 图层级变换动画（头发/身体摆动）；
- DeepSeek/Jev 的完整 UI 面板（后端接口已就绪）。

不要在没有明确需求时顺手实现这些大模块；先确认当前任务范围。

---

## 11. 验证清单

```powershell
# 后端
cd backend
.\run_tests.ps1                  # 期望 73 passed

# 前端
cd ..\frontend
npm run build                    # tsc -b + vite build
npm run smoke                    # jsdom 全流程

# 真实后端恢复
$env:MOCADIFF_REAL="1"
$env:MOCADIFF_RESTORE_ONLY="1"
npm run smoke                    # 期望 SESSION RESTORE OK
```

如果测试涉及 Session，先备份 `data/session.json` / `data/session.prev.json`，测试后再确认未被清空；不要为了方便测试直接 `DELETE /api/session` 覆盖用户项目。
