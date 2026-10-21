# 映射模式与多轨时间轴计划

> 状态：第一期已实施  
> 日期：2026-10-21  
> 相关契约：[`../CONTRACT.md`](../CONTRACT.md)  
> 当前实现：`backend/app/services/psd_service.py`、`backend/app/services/svp_service.py`、`frontend/src/components/MappingPanel.tsx`、`frontend/src/components/Timeline.tsx`

## 1. 目标

本阶段扩展 PSD 语义映射、动画生成和底部时间轴：

- 同一 PSD 支持多套素材映射方案；
- 生成时间轴时可选择不同动画模式；
- 一个音素可使用多张口型图完成预备、辅音、起势、稳态和收势；
- 口型生成考虑辅音、音符长度、音高和相邻音素；
- 映射范围扩展到眼睛、眉毛、脸颊、汗和眼部效果；
- 底部时间轴显示 SVP 原始数据轨和生成动画轨；
- 时间轴支持面板拉伸、纵向滚动、轨道高度缩放和分组折叠；
- 浏览器预览与导出使用同一状态解析规则。

## 2. 现状

### 2.1 口型

时间轴定义了 `closed/n/f/a/i/u/e/o` 八类 viseme。当前《酔いどれ知らず》轨道的输出只有 `closed/a/i/u/e/o` 六类，识别出的 `k/s/t/m/n/cl` 等辅音没有形成独立可见状态。

`frames[].openness` 只作为元数据返回。前端舞台和后端导出按 `viseme` 精确选择一张 patch，开度不参与选图。

当前音符平均约 16 帧，最短 5 帧。生成算法适合按音符长度安排 2～4 次状态变化，不适合给所有音符使用固定长度的完整序列。

### 2.2 PSD 素材

`moca.psd` 的口部组包含五元音以外的可用图层：

| 图层 | 建议状态 | 用途 |
|---|---|---|
| `ω` | `closed` | 自然闭口、停顿 |
| `ん` | `narrow` | 鼻音和弱收口 |
| `ぉ` | `roundSmall` | `u/o/w` 起势 |
| `むむ` | `pressed` | `m/b/p/cl` 双唇闭合 |
| `あー` | `aSoft` | `a` 的起势、弱音和收势 |
| `あ/い/う/え/お` | `a/i/u/e/o` | 元音稳态 |
| `わー` | `wide` | 强 `a/wa`、长音 |
| `□` | `openLarge` | 高音、强音 |
| `□大` | `openXLarge` | 峰值强调 |
| `ぎゃー` | `scream` | 极端表达，由情绪模式触发 |

`ωしわ`、`にこ`、`ﾆﾁｬ笑み`、`わはは`、`はは`、`ひひ`、`猫わ`、`蟹`、`ボール` 带有明确表情或道具语义，不进入普通发音映射。

眼睛和效果素材包括：

- 眼型：`通常`、`ーー`、`にっこり`、`＞＜`、`きょとん`、`うるうる`；
- 汗：`汗`、`汗汗`、`首汗`；
- 眼部效果：`涙`、`泣き`。

汗和眼部效果可与眼型同时显示，必须使用独立叠加通道。

### 2.3 时间轴

底部时间轴使用单个 Canvas 和固定 Y 坐标绘制口型、眨眼标记和音频波形。普通滚轮用于横向缩放，`Shift+滚轮` 用于横向平移。面板上边缘已支持拖动调整整体高度。

多轨加入后需要分离三类纵向操作：

1. 拖动分隔条调整面板高度；
2. 滚轮浏览轨道；
3. 调整单轨显示高度。

## 3. 分层

素材和动画分为两个独立概念：

```text
PSD 图层
  → Mapping Set：状态与图层的对应关系
  → Animation Mode：输入数据到状态序列的生成规则
  → 多通道时间轴
  → 舞台预览 / 导出
```

### 3.1 Mapping Set

Mapping Set 定义某个 PSD 提供哪些语义状态，以及每个状态绑定哪个图层。一个 PSD 可保存多套 Mapping Set，例如“标准”和“夸张”。

### 3.2 Animation Mode

Animation Mode 定义如何根据音素、音高、音符长度、节奏和情绪生成状态。模式不保存 PSD 图层 ID，可复用于其他素材。

### 3.3 Timeline

Timeline 同时保存输入参考轨和生成动画轨：

- `sourceTracks`：SVP 音符、音素、音高；
- `tracks`：口型、眨眼、眼睛、眉毛、脸颊、汗、眼部效果；
- 音频波形由音频资产和 offset 派生，不复制进时间轴响应。

## 4. 映射模型

### 4.1 Profile

```json
{
  "psdAssetId": "2b293dbaa9cd",
  "canvas": [2480, 3500],
  "mappingSets": {
    "standard": {
      "label": "标准",
      "channels": {
        "mouth": {
          "closed": "44",
          "narrow": "42",
          "pressed": "49",
          "roundSmall": "43",
          "aSoft": "58",
          "a": "63",
          "i": "62",
          "u": "61",
          "e": "60",
          "o": "59",
          "wide": "41",
          "openLarge": "193",
          "openXLarge": "192"
        },
        "eyes": {
          "open": "119",
          "blink": "137",
          "smile": "136",
          "squeeze": "135",
          "surprise": "129"
        },
        "brow": {
          "neutral": "140",
          "angry": "141",
          "question": "142",
          "surprise": "143",
          "sad": "144"
        },
        "cheek": {
          "normal": "32",
          "blush": "33",
          "deep": "34"
        },
        "sweat": {
          "off": null,
          "single": "38",
          "double": "36",
          "neck": "37"
        },
        "eyeEffect": {
          "off": null,
          "tear": "124",
          "cry": "125"
        }
      }
    }
  },
  "defaultMappingSetId": "standard",
  "channelDefinitions": {
    "mouth": { "behavior": "exclusive", "defaultState": "closed" },
    "eyes": { "behavior": "exclusive", "defaultState": "open" },
    "brow": { "behavior": "exclusive", "defaultState": "neutral" },
    "cheek": { "behavior": "exclusive", "defaultState": "normal" },
    "sweat": { "behavior": "overlay", "defaultState": "off" },
    "eyeEffect": { "behavior": "overlay", "defaultState": "off" }
  },
  "zorder": ["cheek", "mouth", "eyes", "brow", "eyeEffect", "sweat"]
}
```

### 4.2 通道行为

| 行为 | 含义 | 通道 |
|---|---|---|
| `exclusive` | 同一时刻选择一个状态 | `mouth/eyes/brow/cheek` |
| `overlay` | 支持 `off`，打开时叠加一张图 | `sweat/eyeEffect` |

`off` 表示不绘制。解析器不能把缺失的 `off` 回退成任意可用图层。

第一期不支持同一通道同时叠加多张图。后续需要时增加 `multiOverlay`，不改变现有两种行为。

### 4.3 兼容

旧 `profile.channels` 在加载时包装为 `mappingSets.standard.channels`。旧字段在迁移期保留读取能力，保存时写入新结构。

前端归一化逻辑必须保留未知通道，不能再按四类固定通道过滤后端响应。通道编辑 UI 由共享的通道定义表驱动。

## 5. 动画模式

第一期提供四个内置模式：

| 模式 | 口型 | 音高影响 | 辅音 | 眼睛和效果 |
|---|---|---:|---:|---|
| `classic` | 原五元音单图 | 关闭 | 基础 | 普通随机眨眼 |
| `clear` | 辅音起势 + 元音 | 低 | 强 | 普通眨眼 |
| `natural` | 多图协同过渡 | 标准 | 标准 | 乐句感知眨眼 |
| `expressive` | 大开度、多阶段 | 强 | 标准 | 可使用强调眼型和情绪效果 |

默认使用 `natural`。`classic` 保持当前行为，作为兼容与对照模式。

```json
{
  "id": "natural",
  "version": 1,
  "mouth": {
    "strategy": "coarticulated",
    "pitchInfluence": 0.6,
    "consonantStrength": 0.55,
    "minPoseFrames": 2,
    "maxTransitionsPerNote": 4
  },
  "eyes": {
    "blinkStrategy": "phraseAware",
    "allowExpression": true
  },
  "effects": {
    "allowSweat": false,
    "allowTears": false
  }
}
```

第一期只提供内置模式。自定义模式在生成器稳定后增加，避免先构建复杂配置 UI。

## 6. 口型生成

### 6.1 动作阶段

一个非延音音符可生成五个阶段：

```text
prepare → onset → attack → sustain → release
```

- `prepare`：根据下一辅音预备；
- `onset`：辅音可见姿态；
- `attack`：元音弱开度或过渡姿态；
- `sustain`：元音主形；
- `release`：向下一音素或闭口收势。

示例：

```text
/ba/  pressed → closed → aSoft → a → aSoft
/ma/  pressed → narrow  → aSoft → a → closed
/ta/  narrow  → aSoft   → a     → aSoft
/ku/  roundSmall → u → roundSmall
/o/   roundSmall → o → roundSmall
```

### 6.2 短音符压缩

| 长度 | 状态数 |
|---|---|
| 2～5 帧 | 主形；有关键辅音时使用“辅音 → 主形” |
| 6～9 帧 | “辅音或起势 → 主形 → 收势” |
| 10～20 帧 | 完整阶段，最多 4 次切换 |
| 20 帧以上 | 延长稳态，可加入一次受控强弱变化 |

单个姿态至少保持 2 帧。相邻音符优先从前一姿态过渡到下一音素的起势，不在每个音符边界强制闭口。

### 6.3 辅音

| 音素族 | 姿态 |
|---|---|
| `m/b/p/cl` | `pressed → closed` |
| `n`、鼻音尾 | `narrow` |
| `w` | `roundSmall` |
| `f/v` | 使用唇齿专用图；缺失时降级到 `i` |
| `s/z/sh/h` | 短暂 `i/narrow`，随后进入元音 |
| `t/d/r/l/k/g/y` | 不伪造双唇闭合，直接协同到下一元音 |

### 6.4 音高

音高调整开度等级，不改变元音类别。第一期使用音符级 `pitchMidi`，按轨道音域分位数归一化：

$$
p=\operatorname{clamp}\left(\frac{\text{pitch}-P_{20}}{P_{85}-P_{20}},0,1\right)
$$

- $p < 0.35$：弱开度，如 `aSoft/roundSmall`；
- $0.35 \le p < 0.75$：标准元音；
- $p \ge 0.75$：音符不少于 8 帧时可使用 `wide/openLarge`；
- $p \ge 0.92$：音符不少于 12 帧时允许 2～4 帧 `openXLarge`；
- `scream` 不由音高单独触发。

相邻帧最多跨一个开度档。连续 pitch curve 和 vibrato 留到后续阶段，避免嘴型随颤音高频抖动。

## 7. 多通道时间轴

### 7.1 数据契约

```json
{
  "timeline": {
    "fps": 60,
    "duration": 130.93,
    "mode": {
      "mappingSetId": "standard",
      "animationModeId": "natural",
      "animationModeVersion": 1
    },
    "sourceTracks": {
      "notes": [
        {
          "index": 0,
          "start": 8.87,
          "end": 9.12,
          "lyric": "こ",
          "pitchMidi": 66
        }
      ],
      "phonemes": [
        {
          "start": 8.87,
          "end": 8.92,
          "symbol": "k",
          "kind": "stop",
          "timing": "estimated",
          "noteIndex": 0
        },
        {
          "start": 8.92,
          "end": 9.12,
          "symbol": "o",
          "kind": "vowel",
          "timing": "estimated",
          "noteIndex": 0
        }
      ],
      "pitch": [
        {
          "start": 8.87,
          "end": 9.12,
          "midi": 66,
          "source": "note"
        }
      ]
    },
    "tracks": {
      "mouth": [
        {
          "t": 8.87,
          "state": "roundSmall",
          "viseme": "o",
          "phase": "onset",
          "openness": 0.25,
          "noteIndex": 0
        }
      ],
      "blink": [
        { "t": 10.2, "duration": 0.15 }
      ],
      "eyes": [
        { "t": 10.2, "state": "blink" },
        { "t": 10.35, "state": "open" }
      ],
      "brow": [],
      "cheek": [],
      "sweat": [],
      "eyeEffect": []
    }
  }
}
```

`sourceTracks` 是只读输入；切换 Animation Mode 不改变它。`tracks` 是生成结果，切换模式时重新生成。

音素尚无真实时间戳时，根据音符区间和口型规划结果分配区间，并写入 `timing: "estimated"`。解析到 SVP 的音素时长后改为 `timing: "source"`。

### 7.2 兼容字段

迁移期继续返回：

- `frames`：由 `tracks.mouth` 派生，供旧前端和旧导出读取；
- `blinks`：由 `tracks.blink` 派生。

旧时间轴缺少 `tracks` 时，前端和导出继续读取 `frames/blinks`。

### 7.3 状态降级

互斥通道：

```text
目标 state → 同 viseme 标准 state → 通道默认 state → 不绘制
```

叠加通道：

```text
目标 state → off
```

缺失状态不能回退到按字母排序的任意 patch。前端 Stage 与后端 FrameSource 必须共享相同规则和测试样例。

## 8. 轨道界面

### 8.1 布局

```text
时间标尺                              固定
──────────────────────────────────────────────
▾ SVP 原始数据
  音符      歌词块和音符区间
  音素      k | o | n | n | i
  音高      音符阶梯，后续升级为连续曲线
▾ 生成动画
  口型      pressed | roundSmall | o
  眨眼      有持续时间的事件块
  眼睛      open | blink | smile
  眉毛      neutral | surprise
  脸颊      normal | blush
  汗        off | single | off
  眼部效果  off | tear
▾ 音频
  波形      保留 offset 拖动
```

左侧轨道头固定，右侧轨道内容共享时间坐标。标尺固定在顶部，播放头贯穿所有可见轨道。

### 8.2 组件

```text
TimelinePanel
├─ TimelineToolbar
├─ TimelineRuler
└─ TimelineViewport
   ├─ TrackHeaders
   └─ TrackCanvas
```

轨道由定义表驱动：

```typescript
interface TrackDefinition {
  id: string
  group: 'source' | 'animation' | 'audio'
  label: string
  kind: 'blocks' | 'events' | 'pitch' | 'waveform'
  height: number
  visible: boolean
  collapsed: boolean
}
```

各 renderer 共享 `timeToX`、网格、播放头、hover、seek 和横向视图状态。只绘制纵向可见轨道。

### 8.3 交互

| 操作 | 行为 |
|---|---|
| 滚轮 | 纵向滚动轨道 |
| `Ctrl+滚轮` | 以鼠标位置为中心横向缩放 |
| `Shift+滚轮` | 横向平移 |
| `Alt+滚轮` | 纵向缩放轨道高度 |
| 拖动顶部边缘 | 调整整个时间轴面板高度 |

工具栏提供：

- 横向放大、缩小、全览；
- 轨道高度“紧凑 / 标准 / 展开”；
- 全部分组折叠或展开；
- 单个分组折叠或展开。

触控板双指上下用于纵向滚动，`Shift` 修饰后横向平移。普通滚轮不再直接缩放时间。

### 8.4 尺寸

| 元素 | 紧凑 | 标准 | 展开 |
|---|---:|---:|---:|
| 普通轨道 | 24px | 36px | 56px |
| 音高轨 | 48px | 72px | 120px |
| 波形轨 | 44px | 64px | 100px |

- 面板高度：220px 到视口高度的 70%；
- 轨道头宽度：约 116px；
- 折叠状态、轨道高度档位和纵向滚动位置写入布局 localStorage；
- 音频拖动仅在波形轨命中，不能影响其他轨道的 seek。

### 8.5 轨道内容

- 音符轨显示歌词、起止和音高名称；
- 音素轨用不同色系区分辅音与元音，并标记推定时间；
- 音高轨按可见音域自适应，至少显示一个八度，`C` 音使用较强分隔线；
- 口型轨显示实际 `mouthPose`，附带 viseme；
- 眨眼轨显示带宽度的持续事件，不再使用单点三角标记；
- 眨眼轨表示生成事件，眼睛轨表示最终渲染状态；
- 不存在素材的可选通道默认隐藏，用户可手动显示。

## 9. API 与缓存

时间轴请求增加模式参数：

```json
{
  "trackIndex": 0,
  "fps": 60,
  "psdAssetId": "2b293dbaa9cd",
  "mappingSetId": "standard",
  "animationModeId": "natural"
}
```

生成器读取 Mapping Set 的可用状态，避免输出素材无法显示的姿态。

缓存键包含：

```text
SVP source hash
+ track index
+ fps
+ PSD asset id
+ profile version
+ mapping set id
+ animation mode id
+ animation mode version
```

缓存文件使用版本前缀，例如 `timeline-v2-track0-60-<hash>.json`，不能复用旧版 `timeline-track0-60.json`。

## 10. Session

Session 和 Project 保存当前选择：

```json
{
  "mappingSetId": "standard",
  "animationModeId": "natural"
}
```

Mapping Set 内容保存在 PSD profile，不复制进 Session。

恢复顺序：

1. 恢复 PSD 和 profile；
2. 校验 `mappingSetId`，缺失时使用 `defaultMappingSetId`；
3. 校验 `animationModeId`，缺失时使用 `classic` 或 `natural`；
4. 恢复 SVP 和轨道；
5. 按两个模式 ID 重新生成时间轴；
6. 恢复时间轴布局和折叠状态。

Session schema 版本升级。旧 Session 未保存模式 ID 时保持可恢复。

## 11. UI

### 11.1 素材映射

语义映射面板增加：

- Mapping Set 选择器：标准、夸张、新建副本；
- 通道 Tab：口型、眼睛、眉毛、脸颊、汗、眼部效果；
- 图层选择和缩略图；
- 单状态清空；
- 自动识别只填写高置信状态，特殊表情由用户确认；
- `sweat.off` 和 `eyeEffect.off` 不绑定图层。

### 11.2 生成设置

在“生成时间轴”操作附近增加：

- 素材方案；
- 动画模式；
- 重新生成按钮；
- 生成统计：实际嘴型数、辅音覆盖率、各通道事件数。

生成模式不放在烘焙操作旁。烘焙属于素材处理，Animation Mode 属于时间轴生成。

## 12. 通道驱动

| 通道 | 输入 |
|---|---|
| 口型 | 音素、音符长度、音高、相邻音素 |
| 眨眼 | 乐句间隙、音符起点避让、固定随机种子 |
| 特殊眼型 | 情绪段、强调词、手动关键帧 |
| 眉毛 | 情绪分析、手动关键帧 |
| 脸颊 | 情绪分析、手动关键帧 |
| 汗 | 紧张或尴尬事件、手动关键帧 |
| 眼部效果 | 悲伤事件、手动关键帧 |

汗和眼泪不由音高直接触发。相同输入、Mapping Set 和 Animation Mode 必须产生相同结果；随机事件使用项目和轨道派生的固定 seed。

## 13. 实施状态

已完成：

- Mapping Set 数据模型、切换与当前 `channels` 投影；
- 扩展口型、汗和眼部效果映射，叠加通道支持 `off`；
- `classic / clear / natural / expressive` 四种口型模式；
- 音符、推定音素、音符级音高和七类动画轨；
- 多轨 Canvas、固定标尺、纵向滚动、轨高档位和分组折叠；
- 预览与导出消费 `mouthPose` 和动画轨，并兼容旧 `frames/blinks`；
- Session 保存 Mapping Set、动画模式和时间轴视图；
- Mock 与真实后端使用同一响应结构。

保留项：

- 新建、复制、重命名 Mapping Set 的 UI；
- 连续 pitch curve 和 vibrato；
- AI 自动生成眉毛、脸颊、汗和眼部效果事件；
- 手动关键帧编辑和轨道显隐管理；
- 轨道纵向滚动位置持久化。

以下阶段记录保留为实现依据。

### 阶段 1：契约与兼容

- 定义 Mapping Set、通道行为、Animation Mode、`sourceTracks/tracks`；
- 升级后端 Pydantic 和前端 TypeScript 类型；
- 实现旧 profile、旧 timeline 和旧 Session 的兼容读取；
- 更新 `CONTRACT.md`。

验证：模型序列化测试、旧 Session 恢复测试、旧时间轴读取测试。

### 阶段 2：动态素材映射

- 扩展口型、眼睛、汗和眼部效果状态；
- 修改 automap 别名与父级提示；
- 前端保留动态通道，不再丢弃未知字段；
- MappingPanel 改为定义表驱动；
- bake 和 manifest 支持动态 z-order 与 overlay `off`。

验证：automap、profile roundtrip、bake patch 集、缺失可选通道降级。

### 阶段 3：多轨时间轴框架

- 将固定坐标 Canvas 重构为标尺、轨道头和可滚动轨道区；
- 先接入原口型、眨眼和波形；
- 保留音频 offset 拖动；
- 增加纵向滚动、轨道高度缩放和分组折叠；
- 持久化布局状态。

验证：现有横向缩放、平移、seek、播放头和音频拖动不回归；多轨溢出时可滚动。

### 阶段 4：SVP 来源轨

- 增加音符轨；
- 增加推定音素轨；
- 增加音符级音高轨；
- 标记音素时间来源。

验证：音符边界与 SVP 一致，音素区间不越过所属音符，音高值与 notes 一致。

### 阶段 5：模式化口型

- 实现 `classic/clear/natural/expressive`；
- 增加辅音映射、多图阶段和协同发音；
- 增加音符级相对音高分档；
- 输出 `tracks.mouth` 并派生旧 `frames`；
- 缓存键加入模式与 profile 版本。

验证：短音符压缩、辅音覆盖、音高分档、确定性输出、classic 回归。

### 阶段 6：眼睛与效果

- 将眨眼迁入 `tracks.blink` 和 `tracks.eyes`；
- 实现乐句感知眨眼；
- 增加眉毛、脸颊、汗和眼部效果轨；
- 第一版从规则情绪事件或手动事件读取汗和眼泪。

验证：事件可叠加、`off` 不绘制、缺素材不报错、固定 seed 可复现。

### 阶段 7：预览与导出

- Stage 和 FrameSource 读取统一轨道；
- 实现通道行为和降级规则；
- 导出请求携带完整多轨时间轴；
- 校验预览与输出逐帧一致。

验证：前端 build、DOM smoke、后端 render 测试、短片导出 smoke。

### 阶段 8：Session 与文档

- 保存两个模式 ID；
- 保存时间轴显示偏好；
- 更新 README、CONTRACT 和恢复 smoke；
- 补充模式统计与错误提示。

验证：LIVE/MOCK 切换、刷新恢复、previous Session 恢复。

## 14. 验收

### 映射与模式

- 同一 PSD 可保存并切换多套 Mapping Set；
- 同一 SVP 可用四种 Animation Mode 生成稳定、可解释的不同结果；
- 切换 Mapping Set 不修改生成算法；
- `classic` 与旧行为兼容；
- `natural` 在 moca.psd 上使用至少 9 种有效口部姿态；
- 5 帧短音符最多切换两次，不出现单帧闪烁；
- 高音扩大开度，但不改变 `i/u/e/o` 的元音类别。

### 多通道

- 眼睛、眉毛、脸颊、汗和眼部效果可独立映射；
- 口型、眼睛和 overlay 可同时显示；
- `off` 不绘制任何 overlay；
- 缺失汗或眼泪素材时不报错；
- 同一输入和模式重复生成结果一致。

### 多轨时间轴

- 音符、音素、音高、口型、眨眼、眼睛和波形均为独立轨道；
- 来源轨与生成轨分组显示；
- 所有轨道共享横向缩放、平移、播放头和 seek；
- 面板可拉高或压低；
- 轨道区可纵向滚动；
- 轨道高度可切换紧凑、标准和展开；
- 分组可折叠，刷新后恢复布局；
- 音素轨区分推定时间和来源时间；
- 拖动波形只修改音频 offset；
- 不可见轨道不持续绘制，播放时无明显掉帧。

### 输出

- 浏览器预览与 PNG/视频导出状态逐帧一致；
- 旧 profile、旧 Session 和旧 timeline 可读取；
- 切换模式不会错误复用其他模式的缓存。

## 15. 后续

以下内容不进入第一期：

- SVP 连续 pitch curve 和 vibrato；
- 音素真实时长的完整解析；
- 图片像素插值或形变混合；
- 同一 overlay 通道同时显示多张图；
- 完整自定义 Animation Mode 编辑器；
- 时间轴手动关键帧编辑。

多轨框架需要为手动关键帧预留选择和命中接口，但本阶段不实现编辑行为。