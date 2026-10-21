# 自动人物立绘差分选择工具：开源预研结论与可落地技术方案

> 针对素材：`moca.psd`（2480×3500，190 层）× `流沙.svp`（Synthesizer V 工程，v196）
> 预研日期：2026-10-19 ｜ 结论基于本机实测 + 可运行原型，不是纸面推演
> 配套产物：`prototype/`（可跑代码 + demo 视频）、`报告附件/`（四份详细分析报告与视频）
>
> **2026-10-20 更新：v0.1 已进入实现，见 [`../README.md`](../README.md)。**
> 已完成：PSD 自动映射 + 烘焙、SVP 单轨口型、音频/BPM、React 单页预览、透明导出（PNG/ProRes 4444/WebM alpha/MP4）、DeepSeek/Jev 后端。
> 仍在下一阶段：时间轴手动关键帧、AI 效果实际渲染、多人物 UI、图层级变换动画。

---

## 0. 三分钟结论（先回答你最关心的三个问题）

### Q1：有没有类似的开源项目可以直接用？
**没有端到端能用的。** 截止 2026-10，没有找到任何开源项目能同时做到：
「读 Synthesizer V 工程 → 自动得到音素/时间轴 → 映射为口型 viseme → 直接控制 PSD 差分图层 → 离线批量出帧」。

最接近的是两组「**闭源免费宿主 + 开源插件**」：

| 方案 | 能做到 | 为什么不能直接用 |
|---|---|---|
| **YMM4（免费闭源）+ KuchiPaku（MIT）** | PSD 立ち絵、口パク（あいうえお）、まばたき、表情差分 | 不读 `.svp`；需要 `.lab` 音素标注；工程格式 `.ymmp` 不公开；不能作为库嵌进你的工具 |
| **AviUtl / AviUtl2 + PSDToolKit（MIT）** | PSD 直接渲染、目パチ、口パク、Lua 可编程 | 绑定 AviUtl 宿主；不能离线批处理成独立工具；不读 `.svp` |

真正可复用的是「零件」：**psd-tools（MIT）** 做 PSD 合成、**pypinyin（MIT）** 做中文 G2P、**ffmpeg** 出片、**Rhubarb / MFA（MIT）** 做音频兜底校验。详见 §2。

### Q2：这些零件能拼出满足你要求的工具吗？
**能，而且本次已经把最关键的链路完整跑通并出了 demo。**
你的 8 项要求里：**5 项本次已用真实素材验证可行**，2 项部分完成（情绪/表情需要标注机制；背景合成需要封装），1 项待开发（GUI/易用性）。

| 你的要求 | 结论 | 说明 |
|---|---|---|
| 按人声轨自动出口型 | ✅ 已验证 | `.svp` 解析 + 拼音/X-SAMPA→viseme，工程内 **227 个 token 100% 覆盖** |
| 自动眨眼 | ✅ 已验证 | 规则生成 92 次眨眼（可调频率/幅度/触发条件） |
| 自动表情（眼睛） | ⚠️ 部分 | 「什么时候眨眼/换眼型」可自动；「表达什么情绪」`.svp` 里没有，需要人工标注或 LLM 从歌词推断 |
| 直接使用 PSD 差分层 | ✅ 已验证 | 像素级 1:1 还原，无 clipping/蒙版/智能对象 |
| 输出视频背景素材 | ⚠️ 部分 | 渲染内核与 ffmpeg 管道已验证；背景视频叠加/透明 MOV 需封装 |
| 中文+音素串混合歌词 | ✅ 已验证 | 本工程实际就是普通话拼音 + X-SAMPA 音素串 + 英文 token |
| 多轨/多分组 | ✅ 已验证 | 本工程两条人声轨有 92.96s 重叠，合并策略已定 |
| 简单易用的 GUI | ❌ 待开发 | 原型是命令行；GUI 是 v1 的主要工作量 |

### Q3：还需要补全哪些技术？
**没有「卡脖子」的未知技术，缺的是 5 个工程模块的打磨**（详见 §5）：

1. `.svp` 语义解析器（本次已写原型，需产品化）；
2. 中文/拼音 + X-SAMPA + 英文混合歌词 → viseme 映射（本次已 100% 覆盖当前工程，需泛化）；
3. 口型/眨眼/情绪的调度规则（眨眼已有；情绪需要标注机制）；
4. PSD 差分层的「语义映射配置 + 自动发现」（当前 PSD 手写映射可用，换 PSD 需要配置/启发式）；
5. 渲染器与工具外壳（渲染内核本次已验证：**992×1400 单帧 1.2ms，5.3× 实时**；缺背景合成与 GUI）。

> **一句话**：不用等任何技术突破，按本方案 3–5 天可出可用 MVP，2–3 周可出带 GUI 的 v1。

---

## 1. 需求拆解与验收标准

把「自动人物立绘差分选择工具」拆成可验收的能力：

| # | 能力 | 输入 | 输出 | 验收标准 |
|---|---|---|---|---|
| 1 | 读取工程 | `.svp` | 轨道/分组/音符/歌词/时间 | 音符起止与 SynthV 一致（±1 帧） |
| 2 | 歌词→口型 | 歌词、音素串 | 每帧 viseme | 人工抽查 20 个音符，口型类别正确 |
| 3 | 口型时序 | 音符时长 | 逐帧/逐事件 | 与音符边界对齐；休止闭口；延音保持 |
| 4 | 眨眼 | 乐句/休止 | 眨眼事件 | 频率合理（15–25 次/分），不打断咬字 |
| 5 | 情绪/眼型 | 歌词/人工标注 | 表情事件 | 可选择「自动弱提示 / 人工标注 / 关闭」 |
| 6 | PSD 差分渲染 | `.psd` + 事件 | 帧序列/视频 | 与 Photoshop 合成像素级一致（≤±1） |
| 7 | 视频输出 | 帧序列 | MP4/透明 MOV | 24/30/60fps；支持背景视频/透明通道 |
| 8 | 可迁移 | 新 PSD/新工程 | 配置 | 换素材不改代码，只改映射配置 |
| 9 | 易用性 | — | GUI/CLI | GUI 选文件→预览→导出三步内完成 |

---

## 2. 开源预研结论（完整证据见 `报告附件/01_开源项目预研.md`）

### 2.1 端到端结论

**没有端到端开源项目。** 现有生态分成四段，每段各有一批成熟件，但没有「SynthV → PSD 差分」的桥：

```
Synthesizer V 工程  ──[ 缺口①：.svp 语义 + 音素 ]──  音素/时间轴
音素/时间轴        ──[ 缺口②：中日混合 G2P→viseme ]──  口型/表情事件
口型/表情事件      ──[ 缺口③：事件→PSD 图层可见性 ]──  差分帧
差分帧            ──[ 缺口④：批量渲染 + 合成 ]──      视频
```

### 2.2 可直接复用的轮子（已核 license / 维护状态）

| 用途 | 依赖 | License | 说明 |
|---|---|---|---|
| PSD 解析/合成 | **psd-tools 1.25.0** | MIT | 逐层可见性 + composite；本 PSD 1:1 可靠 |
| 中文 G2P | **pypinyin 0.55.0** | MIT | 汉字→拼音/声母/韵母；多音字可覆盖 |
| 音素→口型参考 | **KuchiPaku** | MIT | `.lab`→あいうえお 的算法可借鉴（不嵌入） |
| SynthV 音素导出（高精度模式） | **svstudio-scripts** + **GroupPhonemes.lua** | Apache-2.0 / CC0 | 在 SynthV Studio 2 Pro 里跑脚本，拿内部 T2P 音素 |
| 音频兜底对齐 | **Montreal Forced Aligner** | MIT | 中/日 phone 级时间，用于交叉校验 |
| 音频口型第二意见 | **Rhubarb Lip Sync 1.14.x** | MIT | 语言无关 phonetic 模式，日语近似可用 |
| 视频编码 | **ffmpeg 7.0** | LGPL/GPL（构建相关） | 管道 rawvideo→H.264 |
| 浏览器预览（可选） | **ag-psd** | MIT | 前端可视化 PSD 差分 |

### 2.3 现有近似方案对照

| 方案 | 驱动方式 | 能力 | 关键限制 |
|---|---|---|---|
| YMM4 + KuchiPaku | `.lab` 音素文件 | PSD 立ち絵 + あいうえお口パク + 眨眼 | 闭源宿主；不读 `.svp`；`.ymmp` 不公开 |
| AviUtl + PSDToolKit | 音频 / Lua 脚本 | PSD 直接渲染 + 目パチ + 口パク | 绑定宿主；不能做独立离线工具 |
| Rhubarb / uLipSync | 音频 | 9 种英语口型 / 实时权重 | 音频驱动，不是文本/音素驱动；中文日语音素精度「近似」 |
| MFA | 音频+文本 | phone 级对齐 | 歌唱对齐难；输出是音素边界不是 viseme |
| **psd-tools + 自研调度** | `.svp` / 音频 | 覆盖 7/8 项（情绪需标注） | **需要自研，但本次已验证可行** |

### 2.4 结论矩阵（针对本需求的 8 个硬指标）

图例：✅ 满足 / △ 部分 / ❌ 不满足

| 方案 | 按音素口型 | 自动表情 | PSD 直接渲染 | 自动眨眼 | 中文+音素混合 | 多轨/多组 | 离线批量 | 可嵌入 |
|---|---|---|---|---|---|---|---|---|
| YMM4 + KuchiPaku | △ 需 `.lab` | △ 手工 | ✅ | ✅ | ❌ 日语为主 | △ | ✅ GUI | ❌ |
| AviUtl + PSDToolKit | ✅ | ✅ 可编程 | ✅ | ✅ | ? 自写 Lua | △ | △ GUI | ❌ |
| Rhubarb | △ 音频近似 | ❌ | ❌ | ❌ | △ | ✅ | ✅ | ✅ |
| MFA | △ phone 级 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **psd-tools + 自研** | ✅ | △ 需标注 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### 2.5 最关键认知：为什么 `.svp` 里没有音素？

这是整个预研里最容易踩坑、也最影响方案设计的一点：

- SynthV 的 note 有两个音素概念：
  - `Note.getPhonemes()` / `.svp` 的 `notes[].phonemes` —— **只存用户手动覆盖的音素**。你的工程里该字段全为空，是**正常现象**，不是文件损坏。
  - 默认发音由 SynthV 内部「歌词→音素转换器（T2P）」按音库词典生成，**只在宿主里存在**。
- 所以离线读取 `.svp` 拿不到「默认音素」，只有三条路：

| 路线 | 做法 | 精度 | 依赖 | 适合 |
|---|---|---|---|---|
| **A 高精度** | 在 SynthV Studio 2 Pro 里跑 Lua/JS 脚本，用 `getComputedAttributesForGroup()` / `getPhonemesForGroup()` 导出 | 最高（用 SynthV 自己的 T2P） | 用户有 SynthV Pro、打开工程 | 你本机有 SynthV，最推荐作为「精确模式」 |
| **B 纯离线** | 自建 G2P：中文拼音 + X-SAMPA 音素串解析 + 英文规则 | 中高（本工程 100% 覆盖） | 无 | 批量、无人值守、换机器 |
| **C 音频兜底** | 拿渲染后的人声 wav，用 MFA / Rhubarb 对齐 | 中 | 需音频 | A/B 的交叉校验 |

> 本原型走的是 **B（离线）**，并保留 A/C 的接口（同一份 `viseme_timeline.json` 中间格式，三种来源可互换）。

### 2.6 License 红线（重要）

- 可进分发物：MIT / Apache-2.0 / BSD-2 / CC0 —— psd-tools、ag-psd、pypinyin、Rhubarb、MFA、KuchiPaku、PSDToolKit、svstudio-scripts、UtaFormatix3、PNGAL、Inochi2D。
- **不可**作为依赖分发：`svp2lab-Converter`（无 license，默认保留所有权利）、Live2D Cubism（专有+发布许可）、`psd2live`（GPL-3.0 传染）、YMM4/AviUtl/Syncroh2（闭源免费，只能用不能打包）。
- 你的素材 `moca.psd` 自带 `readme.txt`：**非商用、禁止二次配布、加工改変需良识范围** → **工具本身可以开源分发，但绝不能打包 PSD/生成的立绘素材**。

---

## 3. 素材实测：你的文件到底有什么

### 3.1 moca.psd（详见 `报告附件/02_PSD结构分析.md`）

| 项 | 结果 |
|---|---|
| 画布 | 2480×3500 @350dpi，8bit RGB，PSD v1 |
| 图层 | **190 = 159 像素层 + 31 组** |
| 复杂特性 | **0 clipping mask、0 图层蒙版、0 智能对象、0 文字/形状/调整层、0 Layer Comps** |
| 混合模式 | 仅 1 个 MULTIPLY（`闇`，默认隐藏）；其余 NORMAL，opacity 全 255 |
| 结论 | **纯像素层，psd-tools 可 1:1 合成，不需要 Photoshop** |

**口型差分（真实存在，坐标 `本体>顔パーツ>口`）：**

| viseme | PSD 层名（原文） | 路径 | 尺寸 |
|---|---|---|---|
| a | **あ** | `0.3.1.19.4` | 153×132 |
| i | **い** | `0.3.1.19.3` | 168×69 |
| u | **う** | `0.3.1.19.2` | 31×26（偏小） |
| e | **え** | `0.3.1.19.1` | 178×78 |
| o | **お** | `0.3.1.19.0` | 89×96 |
| n / 闭口 | **ん** | `0.3.1.1` | 34×11 |
| 默认猫嘴 | **ω** | `0.3.1.3` | 159×23 |

> 另有 16 个口部表情（`わー / ぉ / ωしわ / 蟹 / ボール / ﾆﾁｬ笑み / むむ / わはは / はは / ひひ / □ / □大 / ぎゃー / 猫わ / にこ / あー`），可用于强调、笑、惊讶等「表情口型」。
> 注意：`あいうえお` 子组默认隐藏，切换时必须**先开组再开层**。

**眼睛差分：**
- 睁眼 2 套扁平变体（各 12/10 层）：`通常 / 猫目 / しいたけ / うるうる / 病み / ぐるぐる / 三白眼 / 黒ぐる / 下向き / 昇天 / 上ぐる`；
- 闭眼 10 种（`0.3.2.1`）：**`ーー`（中性眨眼）**、`にっこり`（笑眼）、`＞＜`、`○○`、`きょとん`、`発光`、`じと`、`じとぐる`、`ぐるぐる`、`うるうる`；
- 瞳孔细拆 11 种（`0.3.2.0.0`，适合只换瞳）；
- 眉毛 5 种：`通常 / 怒り / 疑問 / 驚き / 悲しみ`（**默认是怒り，做中性唱歌表情必须显式切回通常**）；
- 脸颊 3 种（`通常 / 赤面 / 真っ赤`）、汗、泪、黑眼圈等。

**性能实测（关键，决定架构）：**

| 渲染方式 | 单帧 | 5800 帧（242s@24fps） | 结论 |
|---|---|---|---|
| 每帧 `psd.composite()` 真合成 | **8.1 s/帧** | ≈13 小时 | ❌ 不可行 |
| 每帧 `composite(viewport=脸区)` | 0.47–0.62 s | ≈48 分钟 | ⚠️ 兜底 |
| **预导出 base + numpy/PIL 贴图 + ffmpeg 管道** | **0.028 s/帧（1080p）** | **≈2.7 分钟** | ⭐ 推荐 |

> 坑：`psd.composite()` 有快路径——没改过任何图层属性时直接返回 PSD 内嵌的合并预览图（1.3 s），改过 `visible` 后才是真合成（8 s）。强制真合成要传 `ignore_preview=True`。

### 3.2 流沙.svp（详见 `报告附件/03_SVP解析与转换器.md`）

| 项 | 结果 |
|---|---|
| 轨道 | 6 条：4 条伴奏/音频轨（`renderEnabled=false`）+ **2 条人声轨** |
| 人声轨 | track4「未命名音轨 5」435 音符（15.79–238.82s，Vocal-Chorus_*）；track5「未命名音轨」220 音符（84.47–238.62s，Vocal-Main_*） |
| 合并后 | **655 个音符**，覆盖 **15.789–238.816s** |
| 重叠 | 两轨同时发声 **92.96s** → 需要「主唱优先、副唱补空」的合并策略 |
| 时间基准 | `705600000 tick = 1 四分音符`；`绝对tick = note.onset + groupRef.blickOffset`；`秒 = startTimeSeconds + tick/705600000×60/BPM` |
| 校验 | 655/655 onset 落在 1/16 拍网格；末音符 238.816s vs 音频 242.603s（尾 3.79s）；BPM 误差 2.19e-5 |
| `notes[].phonemes` | **全为空**（正常，见 §2.5） |
| 参数自动化 | 9 个参数 × 16 组 = **0 个 point** → 无法从 `mouthOpening/loudness` 推口型，必须从歌词/音素推导 |
| 歌词语言 | 16 个人声组全部 `languageOverride=mandarin, phonesetOverride=xsampa` → **罗马字是拼音，不是日文 romaji** |
| Token | **227 个 distinct token，100% 映射**（645 规则 + 10 启发式，0 未映射） |
| 时间轴 | 60fps / 239.316s / 14359 帧 / 8 类 viseme（`closed,n,f,a,i,u,e,o`） |
| 合理性 | 有声帧 83.03%、闭口 20.76%、viseme 切换 1.51 次/秒、主唱音符边界对齐 100% |

### 3.3 端到端原型结果（真实 PSD + 真实 SVP 时间轴）

原型代码：`prototype/`（命令与细节见 `prototype/README.md`）。

```
moca.psd ──psd_diff.py（一次性 ~20s）──► cache/
   base.png（隐藏口/目/眉/颊的底板，1.5MB）
   mouth_a/i/u/e/o/n/ω/...（25 个 RGBA 补丁，0.54MB）
   manifest.json（图层路径/offset/像素校验）
                                            │
viseme_timeline.json ──render_demo.py──► DiffComposer（纯 PIL，1.2ms/帧）
   （60fps，可换 mock/音频来源）              │ + 眨眼/表情事件
                                            ▼
                                       ffmpeg 管道 → demo.mp4
```

**实测数据：**

| 项 | 结果 |
|---|---|
| 无损性校验 | 底板+补丁重建 vs `psd.composite()`：**diff_max=1，>8 差异像素 0.00% → IDENTICAL** |
| 缓存导出（大图） | 打开 0.18s + 导层 0.10s + 底板 composite 10.72s + 校验 8.96s ≈ **20.5s（一次性）** |
| 单帧合成 | 992×1400：**1.14–1.23ms（≈870fps）**；2480×3500：7.86ms（127fps） |
| 24.4s demo 渲染 | **4.59s（127.7fps ≈5.3× 实时）**，586 帧，0.42MB |
| 全曲外推 | 3 分钟歌曲（4320 帧 @992×1400）≈ **30s 出片** |

**可看的产物：**
- `prototype/demo.mp4` —— 24.4s，真实时间轴窗口 27.6–52.0s，真实眨眼事件；
- `prototype/demo_with_lyrics.mp4` —— 同上，底部烧录当前歌词 + `[viseme]`，用于核对同步；
- `prototype/preview/timeline/contact_sheet_face.png` —— 8 个真实时间点关键帧；
- `prototype/preview/contact_sheet_face.png` —— 固定 a/i/u/e/o/眨眼/笑眼 差分验收图。

> 限制：demo 是无声的（工作目录里没有渲染后的 wav；`.svp` 引用的音频路径在本机不存在）。正式出片时把 wav 与 demo 用 ffmpeg 合流即可。

### 3.4 需求逐条对照

| 要求 | 状态 | 证据/说明 |
|---|---|---|
| 从声轨自动选择口型 | ✅ 已实现 | 655 音符、14359 帧时间轴；demo |
| 从声轨自动选择眼睛（眨眼） | ✅ 已实现 | 92 次眨眼事件 + demo |
| 情绪表情 | ⚠️ 部分 | 启发式 29 段（弱）；准确演技需标注 |
| PSD 差分层直接使用 | ✅ 已实现 | 25 层缓存 + 像素级校验 |
| 中文+音素混合 | ✅ 已实现 | 100% token 覆盖 |
| 多轨/多分组 | ✅ 已实现 | 主唱优先 + 副唱补空 |
| 背景视频合成 | ⚠️ 待接 | 渲染内核支持，缺背景/透明通道封装 |
| GUI | ❌ 未做 | 当前是命令行 |

---

## 4. 技术方案（要补全的完整架构）

### 4.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│ 输入层                                                           │
│  .svp 工程（可选：人声 wav / 歌词 txt / 情绪标注 yaml）           │
└───────────────┬─────────────────────────────────────────────────┘
                ▼
┌───────────────────────────┐   ┌───────────────────────────────┐
│ A. SVP 解析器              │   │ D. PSD 差分层解析/缓存         │
│  - track/group/note       │   │  - 图层树/可见性               │
│  - tempo map → 秒          │   │  - 语义映射配置 diff_map.yaml  │
│  - 歌词/音素/重叠/延音     │   │  - 导出 base + patch PNG       │
└───────────────┬───────────┘   └───────────────┬───────────────┘
                ▼                               │
┌───────────────────────────┐                   │
│ B. 歌词→viseme             │                   │
│  - 中文拼音 / X-SAMPA / 英文│                   │
│  - onset/main/coda         │                   │
│  - 协同发音/休止/延音      │                   │
└───────────────┬───────────┘                   │
                ▼                               │
┌───────────────────────────┐                   │
│ C. 表情/眨眼调度           │                   │
│  - 规则（乐句/标点/休止）   │                   │
│  - 人工标注 yaml / LLM     │                   │
│  - 优先级与冲突解决         │                   │
└───────────────┬───────────┘                   │
                ▼                               ▼
        ┌────────────────────────────────────────────┐
        │ E. 渲染器（DiffComposer）                    │
        │  base + patch 贴图 → ffmpeg → MP4/MOV/PNG   │
        │  （可选：背景视频/透明通道/AE 工程导出）      │
        └───────────────────┬────────────────────────┘
                            ▼
                 ┌──────────────────────┐
                 │ F. CLI / GUI / 插件   │
                 └──────────────────────┘
```

### 4.2 中间格式（三个契约，来源可互换）

**1) `viseme_timeline.json`（口型时间轴）**

```json
{
  "fps": 60,
  "duration": 239.316,
  "frame_count": 14359,
  "visemes": ["closed", "n", "f", "a", "i", "u", "e", "o"],
  "frames": [{"t": 27.6, "viseme": "a", "openness": 0.95, "note": 123}],
  "notes":  [{"start_sec": 27.6, "end_sec": 28.0, "lyric": "爱",
              "phoneme": "ai", "viseme": "a", "coda_viseme": null}],
  "meta": {"source": "svp|audio|manual", "primary_track": 5}
}
```

**2) `expression_events.json`（眨眼/表情）**

```json
{
  "blinks": [{"t": 2.0, "duration": 0.15, "both_eyes": true}],
  "emotions": [{"start": 3.98, "end": 6.35, "mood": "bright", "intensity": 0.65}],
  "overrides": {"eyes": [{"start": 10.0, "end": 12.0, "style": "tears"}]}
}
```

**3) `diff_map.yaml`（PSD 图层语义映射）**

```yaml
psd: moca.psd
canvas: [2480, 3500]
base_hidden_groups: ["0.3.1", "0.3.2.0.2", "0.3.3"]
mouth:
  a: "0.3.1.19.4"      # あ
  i: "0.3.1.19.3"      # い
  u: "0.3.1.19.2"      # う
  e: "0.3.1.19.1"      # え
  o: "0.3.1.19.0"      # お
  n: "0.3.1.1"         # ん
  closed: "0.3.1.3"    # ω（休止/闭口）
eyes:
  open: "0.3.2.0.2.9"        # 通常
  blink: "0.3.2.1.9"         # ーー
  smile: "0.3.2.1.8"         # にっこり
  cry: "0.3.2.1.6"           # うるうる
brows:
  neutral: "0.3.3.0"
  angry: "0.3.3.1"
cheeks:
  normal: "0.3.0.0.0"
  blush: "0.3.0.0.1"
zorder: [cheek, mouth, eye, brow]
```

### 4.3 模块 A：`.svp` 解析（已实现，需产品化）

**格式事实：**
- 顶层 `library[]` 存 group（含 notes），`tracks[].groups[].groupID` → `library[].uuid`；
- `tracks[].groups[].blickOffset` 是 group 在时间轴上的绝对偏移；
- 绝对 tick = `note.onset + ref.blickOffset`；不要用 `blickAbsoluteBegin`；
- 秒 = `startTimeSeconds + tick/705600000 × 60/BPM`（有多条 tempo 时需积分 tempo map）。

**轨道选择规则（本工程验证）：**
1. 过滤 `isInstrumental=true` 或 `renderEnabled=false` 的轨道；
2. 按「组名/轨名含 main/lead」识别主唱（track5），其余人声轨为副唱（track4）；
3. 主唱优先、副唱补空，合并成一条时间轴；重叠 92.96s 由主唱覆盖；
4. 全部可覆盖：`--primary-track 5 --secondary-track 4 --no-fill`。

**坑：**
- 负 onset（前奏 ghost note）；
- 同一 onset 冲突（3 对）、延音链在休止后开始/中断（已用确定性规则处理）；
- 53 个音符有 AI retake，但 take 只存 seed，**不要拿 seed 当时长**；
- 音频 stem 的 `blickOffset≈0.52s`，口型以工程时间轴为准，不额外补偿。

### 4.4 模块 B：歌词→音素→viseme（已实现，需泛化）

**已实现的映射链：**

```
汉字 ──pypinyin──► 声母 + 韵母 ──规则──► viseme（主元音）+ coda（n/ng）
拼音字面 ──规则──► 声母（b/p/m/f/…→closed）+ 韵母（a/i/u/e/o）
X-SAMPA 音素串（".U N cl" 等）──解析──► 音素序列 → viseme
英文 token（baby/hi/la/na）──启发式──► viseme
"-" 延音 ──继承前音符──► 保持 viseme
"br" 呼吸 ──► closed
```

**本工程实测覆盖：227 token / 100%，其中：**
- pinyin 202（如 `xiang → a + n`、`qing → i + n`、`bu → closed + u`）
- X-SAMPA 手工音素串 17（如 `.U N cl`、`.x a :\i cl`、`.t 7 cl`）
- 英文 6（baby/hi/la/na/…，启发式）
- 延音 1、呼吸 1

**时序规则（逐帧算法）：**
1. 音符主体 → `main_viseme`（持续到音符结束）；
2. `onset_viseme`（b/p/m/f→closed、z/c/s→i 等）放在音符起始的 0–2 帧，制造辅音口型；
3. `coda_viseme=n`（an/ang/en/eng/in/ing…）在音符末 2–4 帧切换；
4. 休止/间隙 → `closed`；
5. 极短音符（<0.12s）合并/丢弃，避免抖动；
6. 相邻同 viseme 合并；跨音符边界不重置。

**未知 token 策略（产品化必须）：**
- 词典（拼音）→ 规则 → 启发式 → 回退 `closed` + 记入 `unmapped.csv`；
- 提供 `--on-unknown keep|closed|a` 与人工映射表覆盖。

**高精度模式（A 路线）：**
- 在 SynthV Studio 2 Pro 跑改造版 `GroupPhonemes.lua`（CC0），导出 `{symbol, language, activity, position}`；
- 用 `position/activity` 精确放置辅音，比规则更准；本工程可直接替换中间格式来源，不改渲染器。

### 4.5 模块 C：眼睛/表情调度（需补标注机制）

`.svp` 里没有任何情绪信息（参数 0 点，只有 4 个组级 voice 先验可作弱提示），因此分三层：

| 层 | 来源 | 能力 | 建议 |
|---|---|---|---|
| 眨眼 | 规则 | 乐句间/标点/最大睁眼间隔触发 | 默认开启；频率 15–25 次/分 |
| 情绪 | 规则/LLM/人工 | 按歌词情绪提供弱提示 | 默认 **neutral**，可选开启 |
| 眼型/视线/泪/脸红 | 人工标注 | 精确演技 | 提供 `overrides.yaml` 时间轴；后续做 GUI |

**优先级：** 人工 overrides > 歌词情绪 > 规则；眨眼不打断咬字（避开音符 onset ±2 帧）。

> 本原型 `expression_events.json` 里的 92 次眨眼 + 29 段情绪是**启发式**（从乐句/标点/音高），足以驱动 demo，但不等于「正确的演技」。要准确表达悲伤/开心/惊讶，需要你在工具里标一次情绪轨，或让 LLM 按歌词生成标注再由你微调。

### 4.6 模块 D：PSD 差分语义映射（需产品化）

**当前 PSD（手写映射可用）：**
- 口型 `a/i/u/e/o/n/closed` → `0.3.1.19.x` / `0.3.1.1` / `0.3.1.3`；
- 眼 `open/blink/smile/cry` → `0.3.2.0.2.9` / `0.3.2.1.9` / `0.3.2.1.8` / `0.3.2.1.6`；
- 眉 5 种、颊 3 种、汗/泪/效果层按需。

**换 PSD 的自动发现（需要补的工程）：**
1. 名称启发式：`あ/い/う/え/お`、`a/i/u/e/o`、`mouth_a`、`.a.png`、`口_a`、`open/close/blink/eye_*`；
2. 分组启发式：`口/mouth`、`目/eye`、`眉/brow`、`頬/cheek`；
3. 视觉校验：导出每层缩略图，生成 contact sheet 让用户确认（半自动，最稳）；
4. 兜底：YAML 手配（一次 5 分钟）。

**状态机：**
- 每个语义通道（mouth/eyes/brow/cheek）是「互斥单选组」；
- 切换 = 先关旧层→开新层；组可见性要显式级联（`あいうえお`/`閉じ` 组默认隐藏）；
- 基准状态显式声明，**不要相信 PSD 自带可见性**（`moca.psd` 与 `moca_small.psd` 有 10 处不同）。

### 4.7 模块 E：渲染器（已实现，需补背景/透明通道）

**核心决策：预导出 base + patch，绝不每帧 psd-tools composite。**

- 一次性：隐藏差分组 → composite 一次（大图 8–11s）→ 导出 25 个 RGBA patch（0.1s）；
- 每帧：`base.copy()` → 按 z-order（cheek→mouth→eye→brow）贴 patch → ffmpeg stdin；
- 性能：992×1400 **1.2ms/帧**；2480×3500 **7.9ms/帧**；1080p 管道 **28ms/帧**；
- 输出：MP4（H.264）、PNG 序列、透明 MOV（prores4444/qtrle）；背景视频再叠一层。

**画质增强（可选）：**
- 口型「开合度」插值：`openness` 已带 0–0.95，可对 `う` 做纵向缩放/透明度混合出中间态（本 PSD 只有 5 个离散口型，插值可减少跳变）；
- 说话时轻微头部/身体浮动：对 base 做 1–2px 正弦位移（不要动差分贴图坐标）；
- 音频驱动 AE 抖动/呼吸：ffmpeg 表达式或后期软件做，渲染器只输出稳定画面。

### 4.8 模块 F：交互与集成（需产品化）

**CLI（原型已有）：**
```powershell
# 先生成时间轴（本仓库已附带），再渲染
python _work/svp/svp2viseme.py --fps 60
python prototype/render_demo.py --timeline _work/svp/viseme_timeline.json \
  --fps 24 --start 27.6 --seconds 24.4 --out demo.mp4
# （正式版会支持 --svp 流沙.svp 一步到位；当前原型通过 svp2viseme.py 生成中间格式）
```

**GUI（v1）：**
- 打开 `.svp` / `.psd`；
- 选择主唱/副唱轨；
- 预览：时间轴 + 当前帧 + 口型/情绪轨；
- 情绪/眨眼编辑（拖拽标记）；
- 导出：分辨率/fps/背景视频/透明通道。

**SynthV 集成（v2，可选）：**
- 提供 Lua 脚本 `.svp` 内导出 `viseme_timeline.json`（高精度模式 A）；
- 或导出 SRT/CSV 供外部工具读取。

**音频兜底（v2）：**
- 若用户只有渲染后的 wav：MFA/Rhubarb → phone 时间 → 同一中间格式；
- 用音频与工程时间轴做互相关，自动求 offset。

### 4.9 不同 PSD / 不同角色适配

| 素材约定 | 例子 | 处理 |
|---|---|---|
| 日语 5 元音 | `あ/い/う/え/お` 或 `.a/.i/.u/.e/.o` | 直接映射 |
| 英语 viseme | `AI/A/E/O/U/…` | 映射到 8 类 + 规则 |
| 只有开/闭口 | `mouth_open/mouth_close` | 退化为 2 类（开合幅度用 openness） |
| Live2D/Inochi2D | 参数化模型 | 输出参数曲线，不走 PSD 贴图 |
| 没有口型差分 | 只有表情 | **需要补画/生成口型层**（见 §7 风险） |

---

## 5. 缺口清单：还需要补全哪些技术（按优先级）

> 这是你问的核心。结论：**缺口是工程化的，不是「研究不出来」的。**

| # | 缺口 | 当前状态 | 补全方案 | 优先级 | 预估 |
|---|---|---|---|---|---|
| 1 | `.svp` 解析器产品化 | 原型脚本可跑（`svp_probe.py`/`svp2viseme.py`） | 收成库：版本探测、多 tempo、轨道选择 UI、错误提示 | **P0** | 1–2 天 |
| 2 | 中日混合 G2P 泛化 | 本工程 100% 覆盖 | 词表 + 拼音/英文规则 + 未知 token 回退 + 多音字纠正 UI | **P0** | 2–3 天 |
| 3 | PSD 语义映射与自动发现 | 本 PSD 手写映射可用 | YAML 配置 + 命名启发式 + contact sheet 半自动确认 | **P0** | 2–3 天 |
| 4 | 渲染器封装（背景/透明/音频） | 内核已验证 | 背景视频 overlay、透明 MOV、wav 合流、批量 | **P0** | 1–2 天 |
| 5 | 命令行/配置工作流 | demo 脚本可用 | 一条命令端到端；日志/进度/错误恢复 | **P0** | 1–2 天 |
| 6 | SynthV 精确音素（A 路线） | 未接 | 改造 CC0 `GroupPhonemes.lua`，导出 computed phonemes + position/activity | P1 | 2–3 天 |
| 7 | 协同发音/口型质量 | 规则版（onset/coda） | 用 `getComputedAttributesForGroup` 的 position/activity；或音频驱动微调 | P1 | 3–5 天 |
| 8 | 情绪/视线/眼型标注 | 启发式（弱） | 人工时间轴编辑器；LLM 从歌词生成初稿；默认 neutral | P1 | 3–5 天 |
| 9 | GUI | 无 | PySide6 / Tauri / 本地 Web；三步流程 | P1 | 5–7 天 |
| 10 | 音频对齐/校验 | 无 | MFA/Rhubarb；互相关求 offset；波形对照 | P2 | 2–3 天 |
| 11 | 其他输出（AE/Live2D/Inochi2D） | 无 | 导出关键帧/参数曲线；AE 脚本或 `.aep` 生成 | P2 | 1–2 周 |
| 12 | 无口型 PSD 的素材生成 | 无 | 只有表情时：按嘴部 bbox 做形变/生成口型层（或转 Live2D） | P2 | 视素材 |

**必须自己写、没有现成库的（已确认）：**
1. `.svp` 语义处理（多 take/重叠/延音/轨道合并）；
2. 中文拼音 + X-SAMPA + 英文混合 → viseme 映射与协同发音规则；
3. 「事件→PSD 图层可见性」的调度层；
4. `psd-tools` 之上的组合缓存/贴图渲染性能层。

---

## 6. 实施路线与验收

### 6.1 路线图

| 阶段 | 周期 | 内容 | 验收 |
|---|---|---|---|
| **MVP** | 3–5 天 | 本原型 + 配置化 + 背景视频 + wav 合流 + 一条命令 | 用 `流沙.svp` 出 1 段 30s 成片，口型/眨眼正常，背景正确 |
| **v1** | 2–3 周 | GUI、轨道选择、情绪/眨眼编辑、PSD 自动发现、预览 | 换一首歌/一个 PSD 不改代码能出片；人工标注后表情正确 |
| **v2** | 1–2 月 | SynthV 插件（精确音素）、MFA/Rhubarb 校验、AE/Live2D 输出、批处理 | 批量 10 首歌无人值守；口型精度接近 SynthV 原生 T2P |

### 6.2 建议的第一版功能边界

- **做**：单角色、单 PSD、口型（8 类）+ 眨眼 + 3 种情绪（neutral/happy/sad）+ 背景视频 + MP4 输出；
- **不做（v1 前）**：全身换装、Live2D、自动生成口型素材、多角色同框、实时预览 60fps 全分辨率。

### 6.3 验收清单（可直接用）

1. 随机抽 30 个音符，口型类别与歌词/音素一致 ≥ 28/30；
2. 口型边界与音符 onset 偏差 ≤ 1 帧 @30fps；
3. 休止段闭口率 ≥ 95%；
4. 眨眼不落在音符 onset ±2 帧内；
5. 差分帧与 Photoshop 导出对照，像素差异 ≤ ±1；
6. 3 分钟成片渲染 ≤ 2 分钟（1080p，本机）；
7. 换 `moca_small.psd` 无需改代码；
8. 手动标注 5 段情绪后，导出结果与标注一致。

---

## 7. 风险与替代方案

| 风险 | 影响 | 缓解 |
|---|---|---|
| SynthV 工程版本/格式变化 | 解析失败 | 版本探测 + 字段容错；保留 A 路线（脚本导出）绕过 |
| 多音字/生僻词/英文 token | 口型错 | 词典 + 人工覆盖表 + `unmapped` 报告；必要时用音频兜底 |
| `う` 只有 31×26px、无半开/微笑口型 | 表现力有限 | 用 `openness` 插值/缩放；补画口型层；或换 Live2D/Inochi2D |
| 情绪无法从 `.svp` 得到 | 「表情不贴戏」 | 默认 neutral；人工标注/LLM 初稿；先做「眨眼+眼型」也能看 |
| PSD 含智能对象/文字/调整层 | psd-tools 合成不完整 | 先做兼容性检查；必要时导出 PNG 序列或走 Photoshop 批处理 |
| 音频与工程时间轴偏移 | 口型不同步 | 自动互相关求 offset；提供手动 offset |
| 授权 | 不能分发素材 | 工具自用/开源；不分发 PSD/demo 素材（readme 明确禁二次配布） |
| 性能 | 长片渲染慢 | base+patch 已是 5× 实时；如需更快可分块/多进程/GPU 编码 |

---

## 8. 授权与分发注意

- `moca.psd` 的 `readme.txt` 明确：**非商用、禁止二次配布、加工改変需良识范围**。因此：
  - 工具本身可以开源/分发（建议 MIT/Apache-2.0）；
  - **不得把 PSD、差分图、生成的立绘序列帧或 demo 视频打包分发**；
  - 用户自己出片前请确认使用场景（B 站/YouTube 一般 OK，商业化按原 readme 判断）。
- 依赖许可：psd-tools（MIT）、pypinyin（MIT）、ffmpeg（注意构建的 GPL/LGPL）、Rhubarb/MFA（MIT）。避免把 YMM4/AviUtl/Live2D/Syncroh2/psd2live 作为分发依赖。

---

## 9. 附录：文件与复现

### 9.1 本仓库产物

| 路径 | 内容 |
|---|---|
| `自动立绘差分工具_技术方案.md` | 本文（总报告） |
| `prototype/README.md` | 原型说明、命令、性能、限制 |
| `prototype/demo.mp4` | 24.4s 真实时间轴 demo（992×1400） |
| `prototype/demo_with_lyrics.mp4` | 同上 + 歌词/viseme 字幕 |
| `prototype/preview/` | 差分验收关键帧 + contact sheet |
| `prototype/cache/moca/` | base + 25 个差分 patch（2.06MB） |
| `报告附件/01_开源项目预研.md` | 255 行，27 条 URL，license/结论矩阵 |
| `报告附件/02_PSD结构分析.md` | 303 行，190 层结构 + 性能基准 |
| `报告附件/03_SVP解析与转换器.md` | 约 700 行，时间模型/规则/17 条坑 |
| `报告附件/04_原型说明.md` | 原型 README 副本 |
| `报告附件/demo.mp4` / `demo_with_lyrics.mp4` | 成片副本（本地自用，勿分发） |
| `报告附件/关键帧_真实时间轴.png` / `差分验收_脸部.png` | 查看用关键帧 |

### 9.2 复现命令

```powershell
# 0) 环境（psd-tools 已 vendored，无需 pip）
cd <工作区根目录>

# 1) 从 PSD 导出底板 + 差分 patch（一次性 ~20s）
python prototype\psd_diff.py --psd moca.psd --save-verify

# 2) 用真实 SVP 时间轴渲染 24s demo
python prototype\render_demo.py --fps 24 --start 27.6 --seconds 24.4 --out prototype\demo.mp4

# 3) 重新生成 SVP 时间轴（可选，默认已有）
python _work\svp\svp2viseme.py --fps 60

# 4) 仅导出关键帧检查
python prototype\export_timeline_preview.py --start 27.6 --seconds 24.4 --width 992
```

### 9.3 参考链接（节选，完整见附件 01）

- Synthesizer V 脚本 API：https://resource.dreamtonics.com/scripting/ （`getPhonemesForGroup` / `getComputedAttributesForGroup`）
- 官方脚本示例（Apache-2.0）：https://github.com/Dreamtonics/svstudio-scripts
- 社区音素导出脚本（CC0）：https://avilesjf.github.io/synthv-scripts/
- psd-tools（MIT）：https://github.com/psd-tools/psd-tools
- pypinyin（MIT）：https://pypi.org/project/pypinyin/
- Rhubarb Lip Sync（MIT）：https://github.com/DanielSWolf/rhubarb-lip-sync
- MFA（MIT）：https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner
- KuchiPaku（MIT，.lab→あいうえお）：https://github.com/InuInu2022/KuchiPaku
- PSDToolKit（MIT，AviUtl PSD 渲染）：https://github.com/oov/aviutl_psdtoolkit

---

## 10. 最终判断（给决策用）

1. **这不适合「找一个开源项目直接用」**——不存在；但它非常适合「用成熟零件 + 自研 5 个模块」来组合，且风险低、可验证。
2. **最值钱的部分不是渲染，而是「把歌词变成可解释的口型/演技时间轴」**——这也是唯一没有现成轮子的地方；本次已经把这条路走通到 100% token 覆盖。
3. **建议从 MVP 开始**：用本原型 + 配置化 + 背景/音频封装，3–5 天就能出第一条成片；确认观感后再投入 GUI 和精确音素模式。
4. **情绪表情不要期待全自动**：`.svp` 里没有演技信息，正确做法是「自动眨眼/眼型 + 人工情绪轨（或用 LLM 生成初稿再改）」，这也符合行业里 PV 制作的实际流程。
