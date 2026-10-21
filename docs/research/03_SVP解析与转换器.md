# 流沙.svp → 逐帧 viseme 时间轴：格式分析 / 转换器说明 / 坑与健壮性

> 目标：把 Synthesizer V Studio 工程 **流沙.svp（project version 196）** 彻底解析，
> 生成「歌词 → 音素 → viseme」的逐帧口型时间轴，并给出眨眼/表情事件原型。
> 本目录所有脚本只读取 `.svp`，**绝不修改原始工程**；全部输出写在 `_work/svp/`。
>
> 生成/核对时间：以 `svp_probe.py`、`svp2viseme.py` 的实际运行结果为准（本文数字均来自实际数据）。

---

## 0. 交付物清单与快速使用

| 文件 | 说明 |
|---|---|
| `svp_probe.py` | 工程解析/dump/校验/主唱推荐工具；可 import（`load_project`、`SvpProject`、`TempoMap`） |
| `lyric2viseme.py` | 歌词→音素→viseme 映射核心库（拼音 / X-SAMPA / 英文 / 特殊 token）+ token 覆盖率统计 |
| `svp2viseme.py` | 时间轴生成器：轨选择、延音/辅音/鼻音规则、逐帧时间轴、CSV/JSON/PNG、眨眼与表情事件 |
| `viseme_timeline.json` | **主交付**：`fps / duration / frame_count / frames[]{t,viseme,openness,note} / notes[] / mouth_runs[] / stats / token_coverage / project_validation` |
| `viseme_events.json` | 最简逐音符事件：`{start,end,lyric,phoneme,viseme,onset_viseme,coda_viseme,pitch,track,group,sustain}` |
| `viseme_timeline.csv` | 逐帧表（Excel 友好，utf-8-sig） |
| `notes_visemes.csv` | 逐音符明细（推断音素、拼音声韵母、viseme、置信度） |
| `token_viseme_map.csv` | 本工程全部 227 个 lyric token 及映射（完整性证据） |
| `expression_events.json` | 眨眼 / 情绪事件原型（含 meta 说明哪些需要外部标注） |
| `expression_overrides.example.json` | 人工标注示例（`--expression-overrides` 的输入格式） |
| `viseme_timeline_preview.png` | 0–60s 可视化：音高 / 音符条 / 逐帧色块 / 眨眼标记 |
| `viseme_timeline_preview_duet.png` | 82.5–112.5s（两条人声轨同时发声）可视化 |
| `viseme_timeline_overview.png` | 全曲 0–239.3s 概览 |
| `pinyin_fallback.json` | 本工程 68 个汉字的拼音 fallback 表（pypinyin 不可用时自动使用） |
| `_vendor/` | 离线 vendor 的 pypinyin 0.16.1（见 §8 安装说明） |

```powershell
# 1) 工程体检（打印轨道/组/音符/重叠/主唱推荐/时间校验）
& "F:\Program Files\Miniconda\python.exe" _work\svp\svp_probe.py _work\svp\..\..\流沙.svp

# 2) 生成逐帧时间轴（默认 60fps、全曲、主唱优先 + 其他人声轨补空）
& "F:\Program Files\Miniconda\python.exe" _work\svp\svp2viseme.py

# 3) 常用变体
... svp2viseme.py --fps 30
... svp2viseme.py --primary-track 4 --no-fill        # 只用 chorus 轨
... svp2viseme.py --duration 60 --outdir _work\svp\slice60
... svp2viseme.py --preview-start 80 --preview-end 120

# 4) 工程 dump（供其它工具消费的完整 JSON）
... svp_probe.py 流沙.svp --json _work\svp\project_dump.json
```

---

## 1. 时间模型（最重要，已用数据反证）

### 1.1 单位与公式

* 时间单位是 **blick/tick**，`705_600_000 ticks = 1 个四分音符 = 1 beat(4/4)`。
  因此 1/16 拍 = `44_100_000 ticks`。
* `time.tempo[]` 是 tempo map（本工程只有 `{position:0, bpm:76.0}` 一条），
  `time.startTimeSeconds = 0.0`。
* 换算（脚本 `TempoMap` 实现了多段 tempo 的分段积分）：

```
beats(tick)  = tick / 705600000
sec(tick)    = startTimeSeconds + Σ 分段 [ (tick_i - tick_{i-1}) / 705600000 * 60 / bpm_{i-1} ]
```

本工程退化为：`sec = tick / 705600000 * 60 / 76`。

### 1.2 音符绝对位置用 `blickOffset`，不是 `blickAbsoluteBegin`

这是本项目最容易踩、也最关键的坑。

* `library[]` 里的 NoteGroup 的 `notes[].onset` 是**组内相对坐标**（甚至可能为负）；
* `tracks[].groups[]` 是 NoteGroupReference（放置实例），其 `blickOffset` 是
  **作用在该组全部音符上的时间偏移**（官方脚本 API `NoteGroupReference.getTimeOffset()`
  与 `setTimeOffset(blickOffset)` 完全对应；`getOnset() = 组内首音符 onset + timeOffset`）。

```
绝对 onset(tick) = note.onset + ref.blickOffset
```

`blickAbsoluteBegin / blickAbsoluteEnd` 是**可视 clip 边界**（可被 trim/extend，
可能与音符范围不一致，且本项目所有 `blickAbsoluteEnd = -1` 表示自动），
**不能**用来定位音符。`pitchOffset` 是整组半音移调（本工程全为 0）。

### 1.3 实测校验（`svp_probe.validate_project` 全部通过）

| 校验 | 结果 |
|---|---|
| 655/655 绝对 onset 落在 1/16 拍网格（`tick % 44100000 == 0`） | ✅ 强证据，证明 tick 基准与 `blickOffset` 公式正确 |
| 使用 `blickAbsoluteBegin` 时 | ❌ 有 3 个组（首音符为负/非整拍的组）会偏出网格 → 反证 |
| 末音符结束时间 | 238.8158 s |
| 工程内嵌音频时长（`mainRef.audio.duration`） | 242.6027 s → 尾部留白 **3.79 s**，合理 |
| 音频元数据 bpm vs tempo map | 75.9983 vs 76.0 → 相对误差 **2.19e-5**，238.8s 内漂移仅 **5 ms** |
| 绝对时间为负的音符 | 0 个（组内负 onset 已被 blickOffset 补偿） |
| 同轨重叠音符对 | 3 对（见 §5） |

> ⚠️ 曾出现过的误判：只按 `note.onset` 或 `+ blickAbsoluteBegin` 放置，会得到
> “所有组都从 0 附近开始、全曲只有 40s”的结论；正确公式下两条人声轨是
> 15.79–238.82 s 与 84.47–238.62 s。

### 1.4 音频 stem 的放置偏移

4 条伴奏/参考音轨的 `mainRef.blickOffset` 分别为 463500708 / 241751653 / 463500708 /
463500708 ticks（约 0.52s / 0.27s），即音频块在工程时间轴上不是从 0 开始。
**导出整曲音频后再做口型时，请以工程时间轴为准**（直接渲染工程即可），不要额外加/减这段偏移。

---

## 2. 工程结构（流沙.svp, version 196）

顶层键：`version, uuid, time, library, tracks, renderConfig, projectMixer`。

* `tracks`：6 条
  * 0–3：`isInstrumental=true` 的音频参考轨（`Instrumental.wav / Vocal.wav /
    Vocal-Main.wav / Vocal-Chorus.wav`，均 242.6027s；`renderEnabled=false`，
    且 mixer `mute=true`（0 号除外））→ **不是人声，跳过**。
  * 4：「未命名音轨 5」，9 个组（组名 `Vocal-Chorus_*` 与 `合并`），435 音符，
    时间 15.789–238.816 s，覆盖 187.70 s。
  * 5：「未命名音轨」，7 个组（组名 `Vocal-Main_*`），220 音符，
    时间 84.474–238.618 s，覆盖 103.62 s。
* `library`：16 个 NoteGroup，每个都恰好被引用一次（0 个组被多次引用）。
  组名有 4 对重名（如 `Vocal-Chorus_R_R_R_R`×2、`Vocal-Main_R_R_R`×2）——
  它们是**独立复制出来的组**（各自引用一次），不是同一个组的多个 take。
* 每个组都有自己的 `database`/`voice`/`takes` 引用信息：
  * **全部 16 个人声组都是 `languageOverride="mandarin"`, `phonesetOverride="xsampa"`**
    （跨语言合成）。这一点决定了 roman 化的歌词是**拼音**而不是日文罗马音；
    手工音素串是**普通话 X-SAMPA**。
  * 4 个组带有组级 voice 参数（情绪/音色先验）：
    `合并`（tension +0.10, breathiness −0.66）、`Vocal-Chorus_R_R_R_R`(38)（+0.145/−0.605,
    consonantDuration −0.21）、`Vocal-Chorus_R_R_R_R`(57)（breathiness −0.625）、
    `Vocal-Main_R`（仅 vocalModes）。可用于表情事件的弱先验（§7）。
* 音符 `pitch` 为 MIDI 音高（全曲 39–73，中位 58）；`duration` 0.25–3.0 拍
  （0.197–2.368 s），最小 1/4 拍 → 60fps 下至少 11 帧，不存在“极短到不可见”的音符。

### 2.1 多 take / 重复组怎么处理

* v196 的 `notes[].takes` 是**AI 重录（retake）seed 列表**：
  `{id, seedDuration, seedPitch, seedTimbre, liked}`，`activeTakeId` 指定当前生效的
  seed。本工程 **53 个音符带 1–3 号 retake（activeTakeId ∈ {1,2,3}）**，
  但每个 take 条目**只含 seed，不含另一套 onset/duration/lyrics** →
  对时间轴/口型没有影响（真正渲染音色/微调在 SynthV 内部用 seed 复现）。
  因此解析器以 note 的 nominal `onset/duration/lyrics` 为准，同时读取
  activeTake 的 `muted`（若存在）。
* `tracks[].groups[].takes` 在本工程全部是单 take（activeTakeId=0）；真正的多 take
  在 SynthV 里只影响渲染层，工程文件不会为每个 take 存一套音符内容。
* 若同一个 NoteGroup 被多个 reference 引用（linked group），正确做法是
  **对每个 reference 各生成一份音符**（它确实被唱了多次）；`svp_probe` 会列出被多次
  引用的组，`SvpProject` 也按 ref 展开。
* 同名组重复 = 复制而非 take；以 `groupID`(uuid) 为准，永远不要用组名去重。

---

## 3. 歌词 → 音素 → viseme

### 3.1 本项目出现的 lyric 形态（全部覆盖）

| 形态 | 例子 | 处理 |
|---|---|---|
| 汉字（简/繁） | `爱 情 好 像 流 沙`、`並 牽 願 讓 隨` | pypinyin → 无调拼音 → 声母/韵母 |
| 拼音/罗马化 | `ai qing hao xiang bu shi wu yi hui luan` | 直接按拼音音节解析（声母表 + 韵母表） |
| 手工音素串（歌词以 `.` 开头） | `.U N cl`、`.j e :\i`、`.x a :\i cl`、`.t 7 cl`、`.s\ iA` | 官方「用歌词输入音素」语法 → 按普通话 X-SAMPA 表切分 |
| `-` | 114 个音符 | 延音：继承同一轨上一个非延音音符的 viseme |
| `br` | 18 个音符 | 呼吸音（无字）→ 闭口 |
| 撇号命令 | `'ai 'yi 'wu 'an '愛 '牽 ...` | SynthV「撇号命令」：在音符头加一个气口/声门起音，**发音不变** → 去掉撇号后按正常歌词处理 |
| 英文（`languageOverride=english`） | `yeah oh baby` | 英文启发式（词表 + 首元音组） |

### 3.2 viseme 类别（8 类）

```
closed  闭口：m/b/p、清塞音闭口、cl、休止、br
n       鼻音/半闭：n、ng、N、an/en/ang/... 韵尾（仅句末)
f       唇齿：f/v
a i u e o  五个元音口型
```

每类附带 `openness`（0..1 张口度）与 `width`（0..1 横向展开度），
`viseme_timeline.json` 的 `frames[].openness` 可直接用于 PSD 差分插值/选择。

### 3.3 拼音韵母 → viseme（主元音 + 鼻韵尾）

| 韵母 | 主 viseme | 韵尾 | 韵母 | 主 viseme | 韵尾 |
|---|---|---|---|---|---|
| a/ia/ua | a | – | i | i | – |
| o/uo | o | – | in/ing | i | n |
| e/ie/üe | e | – | u/ü | u | – |
| er | e | – | un/ong/iong | u | n |
| ai/uai | a | – | ün | u | n |
| ei/ui/uei | e | – | iu/iou | o | – |
| ao/iao | a | – | ian/üan(yuan) | e | n |
| ou | o | – | an/en/ang/eng/uan/uang/… | a/e | n |

声母：`b/p/m → closed`、`f → f`，其余声母（d/t/n/l/g/k/h/j/q/x/zh/ch/sh/r/z/c/s/y/w）
不产生独立口型（直接进元音；`n` 作 onset 也不单列，避免抖动）。

### 3.4 普通话 X-SAMPA 音素 → viseme（依据官方音素表）

官方普通话音素表（X-SAMPA）：元音 `a A o @ e 7 U u i i\ i` y`，双元音
`AU @U ia iA iAU ie iE iU i@U y{ yE ua uA u@ ue uo`，韵尾 `:\i r\` :n N`，
塞音 `p ph t th k kh`，塞擦 `ts\ ts tsh ts\` ts\`h`，擦音 `f s s\` ts\h s\`、
`x`，鼻音 `m n`，边音 `l`，半元音 `z\` w j`，`cl stop`，`pau/sil` 静音，`br` 呼吸。

映射规则：

* 元音：`a A → a`；`o → o`；`e @ 7 → e`；`i i\ i\` → i`；`u U → u`；`y → u`
* 双元音取主元音：`AU iA iAU ia ua uA → a`；`ie iE y{ yE ue u@ → e`；
  `@U iU i@U uo → o`
* 韵尾 `:n N → n`；`:\i`（舌尖元音，如 shi）→ i；`r\`` 儿化 → 忽略
* 塞音：只有双唇 `p ph m` 产生可见闭口；`t th k kh` 不改变口型
* `f → f`；`cl → closed`；`br → closed`
* 手工串里以 `.` 开头只表示“这是音素串”，不是音素本身；`:`(长音)、`\`、`` ` ``
  等变音符号会被剥离后再匹配基础符号（如 `s\`=ɕ、`ts\`=tɕ、`ts\``=ʈʂ、
  `:\i`=ɨ/ɿ）

### 3.5 覆盖率（完整性证据）

* **音符级覆盖率 100.00%（655/655）**，`unmapped = 0`。
* 227 个 distinct token；方法分布：pinyin 202、xsampa 17、english 6、
  sustain 1、breath 1。
* 其中**规则映射 645 音符**，**启发式 10 音符**（`yeah/oh/baby/hi/la/na` 等
  英文/语气词，及 4 个 `languageOverride=english` 的音符）。
* 全量 token → viseme 对照见 **`token_viseme_map.csv`** 与本文附录 A。

---

## 4. 逐帧时间轴算法（`svp2viseme.py`）

1. **轨选择**：`svp_probe.recommended_roles()`
   * 命名提示优先：轨/组名含 `main/lead/主旋律/主唱/メイン` → primary
     （本工程 = track5，组名 `Vocal-Main_*`）；
   * 其余人声轨按覆盖时长排序为 secondary，默认**作为 fill**（primary 静音时补空），
     因此 15.8–84.5s（只有 chorus 轨在唱）嘴也会动；
   * 有重叠时 primary 优先；可用 `--primary-track / --harmony-track / --no-fill` 覆盖。
   * 本工程最终：**primary=5 + secondary=4 → 655 音符，15.789–238.816s**。
2. **延音 `-`**：预解析时继承同一轨前一个非延音音符的 main viseme；
   若组内出现「延音链在休止后开始 / 延音链中间断开」（本工程各 2 处，见 §5），
   仍沿用最近一次非延音的 viseme（比错误闭口更自然）。
3. **帧采样**：默认 60fps（`--fps 24/30/60` 任意整数）。帧 i 覆盖 `[i/fps,(i+1)/fps)`，
   viseme 取 i/fps 时刻。`frames[].t` 已按 i/fps 输出（网格对齐）。
4. **辅音过渡**：双唇/唇齿起音（closed/f）在音符起点后保持
   `--consonant-frames`（默认 2 帧），并可从起点前 `--pre-consonant-frames`
   （默认 1 帧）开始预闭口（协同发音）。
5. **元音持续**：音符主体保持主元音 viseme，直到音符结束/下一音符覆盖。
6. **鼻韵尾**：仅当该音符后面跟着休止（乐句结尾）时，末 `--coda-frames`（默认 2）
   帧过渡到 `n`；句中不做鼻尾，避免与下一音节起音打架。
7. **休止**：无音符覆盖 → `closed`。
8. **短间隙**：间隙 < `--gap-hold`（默认 0.08s，60fps≈5 帧）且前后都在唱时，
   用前一帧 viseme 桥接，避免单帧闪烁；更长间隙闭口。
9. **短音符**：每个音符至少 `--min-note-frames`（默认 2）帧（本工程最小 0.197s≈11 帧，
   实际不会触发）。
10. **重叠**：同一轨内同时发声音符，**更晚 onset 的音符覆盖更早的**；
    跨轨按轨优先级（primary 最后绘制、覆盖 secondary）。

### 4.1 输出合理性（本工程实测）

| 指标 | 值 |
|---|---|
| 时长 / 帧数 | 239.3158 s / 14359 帧 @60fps |
| 有声帧占比 | 83.03% |
| 闭口帧占比 | 20.76%（含前奏 15.78s 静默、`br`、闭口辅音、句间休止） |
| viseme 分布 | a 25.73% / u 15.66% / i 15.42% / e 14.52% / o 7.69% / n 0.14% / f 0.09% |
| viseme 切换 | 362 次 = 1.51 次/秒（连续/无抖动） |
| 音符边界对齐抽查 | 183/183 = **100%**（primary 轨，取 onset+consonant_frames 帧与预期 main viseme 比对） |
| 最长静默 | 15.78s（0s 起，前奏） |

---

## 5. 数据坑清单（本项目已实际遇到）

1. **`notes[].phonemes` 全为空字符串**：音素必须自己推断；手工音素保存在
   **lyrics** 里并以 `.` 开头（SynthV 官方向后兼容语法），不要去找 phonemes 字段。
2. **`parameters.*` 全部为空**：包括 `mouthOpening / pitchDelta / loudness /
   tension / breathiness / voicing / gender / toneShift / vibratoEnv`——
   16 个组、9 个参数 **0 个 points**。所以：无法直接使用 mouthOpening，
   也无法用 loudness 做表情/重音。表情只能靠歌词/音高/组级 voice 参数/外部标注。
3. **`blickAbsoluteBegin` vs `blickOffset`**（见 §1.2）：用错会整体错位且看似“合理”。
4. **库内音符 onset 可为负**（本工程最小 −533590307 ticks，约 −0.60s；
   另有 −352800000 / −21559907 等），被 `blickOffset` 补偿后绝对时间非负。
5. **轨道名没有信息量**（全是「未命名音轨 N」，dispOrder 与顺序也不等于主次）；
   角色提示藏在**组名**里（`Vocal-Main_*` vs `Vocal-Chorus_*`）。不要按轨道下标硬编码。
6. **同名组是副本不是 take**；同一 NoteGroup 若被多次引用要按引用展开。
7. **v196 的 take 是 AI retake 的渲染 seed**（本工程 53 个音符 activeTakeId≠0），
   `takes` 里没有另一套音符内容；以 nominal onset/duration/lyrics 为准，不要拿 seed 当时长。
8. **同一 onset 的重复音符**（3 对）：`hu`/`hu`（99.868s）、`-`/`-`（125.526s）、
   `nai`/`yi`（231.908s，两个不同歌词抢同一时刻）。转换器用
   「更晚 onset 优先 → 非延音优先 → 时长更长 → 音高更高」的确定性规则；
   这类数据在手工编辑/复制粘贴时容易出现。
9. **`-` 延音异常**：
   * 延音链在休止后开始（`Vocal-Chorus_R_R_R_R_R` 131.447s、`Vocal-Main_R_R` 103.421s）；
   * 同组延音链中间断开再续（`Vocal-Main_R_R` 108.75s）。
   需要 carry-forward 兜底，否则会凭空闭口。
10. **两条人声轨大量重叠**：track4 与 track5 **同时发声 92.96 s**（main 84.47–238.62
    与 chorus 15.79–238.82 重叠）。任何“两轨互斥”的假设都是错的；必须按轨优先级合并。
11. **`renderEnabled=false` 不是静音**：本工程 6 条轨全为 false，但人声仍要处理；
    真正静音看 `mixer.mute` / `ref.mute` / `note.attributes.muted`（本工程人声均未静音）。
12. **音频 stem 有 blickOffset**（0.52s 左右）→ 以工程时间轴为准（§1.4）。
13. **`mainGroup.notes` 为空**：本工程音符全在 `library[]`；但其它工程可能把音符放在
    `track.mainGroup.notes` 里 → `svp_probe` 两种都读（并按 uuid 去重）。
14. **声音库名会骗人**：`database.name="Miyamai Moca AI 2", language="japanese",
    phoneset="romaji"`，但**每个组引用覆盖为 mandarin/xsampa**。判断语言必须看
    **NoteGroupReference 的 `database.languageOverride/phonesetOverride`**（以及
    音符 `attributes` 的覆盖）。
15. **pitchControls 稀疏**：只有 4 个组共 9 个手动音高控制点；`pitchControls` 是
    list 不是 dict（与 `parameters` 不同），不要写死 schema。
16. **`accent` 字段全为空**；`musicalType` 全为 `singing`（没有 rest 类型，休止靠无音符）。
17. **速度/tick 常量不要猜**：705600000 来自实测（1/16 拍网格全部对齐），不是文档拍脑袋。

---

## 6. 转换器用法与参数

```
python svp2viseme.py [流沙.svp] [--outdir DIR] [--fps 60]
    [--duration SEC] [--tail SEC]
    [--primary-track N] [--harmony-track N,N] [--no-fill]
    [--consonant-frames 2] [--pre-consonant-frames 1]
    [--coda-frames 2] [--gap-hold 0.08] [--min-note-frames 2]
    [--preview-start 0] [--preview-end 60] [--no-png]
    [--seed 42] [--expression-overrides FILE.json]
```

* `--fps`：24/30/60/任意正整数；帧网格 = i/fps。
* `--primary-track/--harmony-track/--no-fill`：覆盖自动主唱/和声选择。
* `--no-fill`：只让 primary 轨驱动口型（其余时段闭口）——用于对照/调试。
* `--duration`：可只导出某段（例如 60s 切片给 demo）；不传则全曲。
* `--expression-overrides`：人工标注合并（schema 见 §7.3）。
* 所有输出直接覆盖同名文件；脚本不写 `.svp`。

`viseme_timeline.json` 关键字段：

```jsonc
{
  "fps": 60, "duration": 239.315789, "frame_count": 14359,
  "frames": [{"t": 0.0, "viseme": "closed", "openness": 0.0, "note": null}, ...],
  "notes": [{"index":..., "start_sec":..., "end_sec":..., "pitch_midi":...,
             "lyric":"爱", "lyric_method":"pinyin", "phones":["", "ai"],
             "onset_viseme":null, "main_viseme":"a", "coda_viseme":null,
             "inherited_sustain":false, ...}],
  "mouth_runs": [{"start_sec":0.0,"end_sec":15.783,"viseme":"closed"}, ...],
  "meta": { "primary_track":5, "secondary_tracks":[4], "rules": {...}, ... },
  "viseme_classes": {"order":[...], "openness":{...}, "colors_rgb":{...}},
  "stats": {...}, "token_coverage": {...}, "project_validation": {"checks":[...]}
}
```

`note` 字段是 `notes[]` 的下标（`null`=休止）。**注意**：音符起点前
`--pre-consonant-frames` 帧的 `note` 也会指向该音符（协同发音预闭口），
比对 `note.start_sec` 时会看到 t 略早于 start，这是预期行为。

---

## 7. 眼睛 / 表情事件（原型 + 需外部标注的部分）

### 7.1 SVP 能提供什么

* **有**：歌词（逐音符）、MIDI 音高/时值、组级 voice 参数（tension/breathiness/
  vocalModes，本工程 4 个组有）、音符 `attributes`（`evenSyllableDuration`、
  `muted`、英文覆盖）。
* **没有（本工程全为空）**：任何逐帧参数自动化 `pitchDelta/loudness/tension/
  breathiness/mouthOpening/...`；也没有“表情/眼睛”轨道。
* 结论：**眨眼时机可由乐句结构推导；表情情绪必须外部标注**（人工或 LLM 用歌词判断）。

### 7.2 启发式规则（`expression_events()`）

**眨眼**（写入 `expression_events.json` → `blinks[]`）：

* 乐句边界：合并后的有声区间之间，间隙 ≥0.7s 时在休止处眨一次（间隙 0.35–0.7s
  也在中点眨一次）；
* 歌曲开头（0.6s）；
* 保底：演唱中若 4.5s 没有眨眼则插入（RNG 以 `--seed` 复现，时长 0.11–0.18s）；
* 标点触发规则（本工程歌词无标点，规则保留）；
* 去重：0.25s 内只保留一次。本工程生成 **92 次眨眼 / 239s ≈ 23 次/分**（动画可接受）。

**情绪**（`emotions[]`）：按有声区间聚合，特征 = 平均音高相对全曲中位数的位置 +
音符密度 + 组级 `paramTension/paramBreathiness`；输出
`mood ∈ {soft, calm, bright, intense, melancholic}` + `intensity 0..1` + 特征值。
本工程 29 段。

### 7.3 必须外部标注的东西（已写入 JSON meta）

* 每句歌词想表达的**情绪**（喜/怒/哀/惊…）与强度曲线；
* 视线的**眼珠朝向/注视点**；
* 眉毛/眼型（眨眼时机可推导，但“半闭/惊讶”等眼型不能）；
* 8 类 viseme 之外的**口型细节**（如笑口型、撅嘴、齿音）；
* idle 微动作、点头/身体律动、头发物理触发。

人工覆盖 schema（`--expression-overrides`）：

```json
{
  "blinks": [{"t": 12.3}],
  "emotion_overrides": [{"t_start": 3.0, "t_end": 8.0, "mood": "sad", "intensity": 0.7}]
}
```

---

## 8. 环境与依赖（离线可复现）

* Python 3.13（`F:\Program Files\Miniconda\python.exe`）；numpy/pillow 已有。
* **pypinyin 不在线安装**：本机 HTTPS 被拦，改用 HTTP 镜像下载 wheel 并解包到
  `_work/svp/_vendor/`（`lyric2viseme.py` 会优先把它加入 `sys.path`）：
  ```powershell
  Invoke-WebRequest -Uri "http://mirrors.aliyun.com/pypi/packages/.../pypinyin-0.16.1-py2.py3-none-any.whl" -OutFile pypinyin.whl
  # 解包到 _work/svp/_vendor/
  ```
* 若 pypinyin 不可用：脚本自动退回 `pinyin_fallback.json`（本工程 68 个汉字全覆盖），
  覆盖率仍 100%；其它工程的生僻字会退化为 `pinyin_heuristic`/`unmapped` 并在
  `token_coverage.unmapped` 中列出。
* 只依赖标准库 + Pillow（画 PNG）。无 matplotlib / 无网络也可跑。

---

## 9. 健壮性建议（换工程 / 换 SynthV 版本）

1. **不要硬编码轨道下标**：先用 `recommended_roles()`（命名提示 → 覆盖率），
   再用 `--primary-track` 修正；把选择结果写进输出 meta 便于复现。
2. **语言判定**：优先 `ref.database.languageOverride/phonesetOverride`
   → 音符 `attributes.languageOverride/phonesetOverride` → 组 `database`
   → 最后才用字符类型猜测。若遇到 `japanese/romaji` 的组，需要补充日文罗马音规则
   （`lyric2viseme` 的 `plan_pinyin_syllable`/`plan_english_word` 之间加一层即可；
   本工程语言为 mandarin/xsampa，未启用）。
3. **若 `notes[].phonemes` 非空**：应优先用 phonemes（SynthV 已做歌词→音素），
   当前转换器只用 lyrics；改造点在 `VisemeConverter._build_events()`
   （`note.phonemes` 非空时走 `L2V.plan_phoneme_string`）。
4. **多段 tempo/meter**：`TempoMap` 已支持多 tempo 点积分；meter 目前仅用于展示，
   若要做小节级眨眼/律动可补。
5. **linked group（一个 NoteGroup 多个引用）**：按引用各展开一次（当前实现即如此），
   不要按 groupID 去重。
6. **工程结构变体**：音符可能在 `mainGroup.notes`（已兼容）；`groups` 可能为空
   （纯主组工程）；`library` 可能不存在（旧版本）。建议保留 `svp_probe` 的
   `checks` 作为导入前的自检（网格/时长/负时间）。
7. **版本字段**：`version=196` 对应 SynthV 2.x；若版本变化，先跑
   `svp_probe.py` 看关键字段是否仍在（`library/uuid/notes/lyrics/blickOffset`），
   失败时它会报出缺失项而不是静默产出错时间轴。
8. **时间轴消费方**：建议只依赖 `fps/duration/frames[]`（最稳定）；
   `notes[]/mouth_runs[]` 供调试与口型事件对齐；`stats/project_validation`
   供 QA 阈值告警（如“闭口占比>80%”或“边界对齐<95%”）。
9. **性能**：全曲 60fps 一次生成 < 2s（含 PNG）；逐帧循环是纯 Python，
   若未来上 240fps/长曲可改成 numpy 向量化（`viseme` 用 int8 数组）。

---

## 10. 已知局限

* viseme 只有 8 类，`ian/üan→e`、`yuan→e` 等韵母归并较粗；对精度要求高的口型
  （齿音、圆唇程度）需要更细的差分表或外部标注。
* 辅音过渡是固定帧数的启发式，不是真正的协同发音模型（无音素级时长数据可用）。
* 表情/眨眼是原型规则，**不是从工程数据学出来的**；情绪必须外部标注。
* `-` 延音的 carry-forward 在“休止后延音”的异常数据上是妥协方案（本工程 2 处）。
* 本项目多处数据是人工拼接的副本组，若用户继续编辑工程，需重新跑转换器。

---

## 附录 A：本工程全部 227 个 lyric token → viseme

> 完整机器可读版本：`token_viseme_map.csv`（列：token,count,method,normalized,
> onset_viseme,main_viseme,coda_viseme,confidence）。
> `-` 的 main 为空表示“继承上一音符”（`inherited_sustain=true`）。

| # | token | n | method | normalized | onset | main | coda | conf |
|---|-------|---|--------|------------|-------|------|------|------|
| 1 | - | 114 | sustain |  | - | (inherit) | - | rule |
| 2 | bu | 23 | pinyin | bu | closed | **u** | - | rule |
| 3 | br | 18 | breath | br | - | **closed** | - | rule |
| 4 | yi | 18 | pinyin | yi | - | **i** | - | rule |
| 5 | wo | 17 | pinyin | wo | - | **o** | - | rule |
| 6 | wu | 17 | pinyin | wu | - | **u** | - | rule |
| 7 | shi | 12 | pinyin | shi | - | **i** | - | rule |
| 8 | de | 11 | pinyin | de | - | **e** | - | rule |
| 9 | xiang | 10 | pinyin | xiang | - | **a** | n | rule |
| 10 | hao | 8 | pinyin | hao | - | **a** | - | rule |
| 11 | 不 | 8 | pinyin | bu | closed | **u** | - | rule |
| 12 | a | 7 | pinyin | a | - | **a** | - | rule |
| 13 | liu | 7 | pinyin | liu | - | **o** | - | rule |
| 14 | qing | 7 | pinyin | qing | - | **i** | n | rule |
| 15 | zhi | 7 | pinyin | zhi | - | **i** | - | rule |
| 16 | 'ai | 6 | pinyin | ai | - | **a** | - | rule |
| 17 | 'yi | 6 | pinyin | yi | - | **i** | - | rule |
| 18 | hu | 6 | pinyin | hu | - | **u** | - | rule |
| 19 | li | 6 | pinyin | li | - | **i** | - | rule |
| 20 | zhen | 6 | pinyin | zhen | - | **e** | n | rule |
| 21 | an | 5 | pinyin | an | - | **a** | n | rule |
| 22 | ba | 5 | pinyin | ba | closed | **a** | - | rule |
| 23 | di | 5 | pinyin | di | - | **i** | - | rule |
| 24 | lu | 5 | pinyin | lu | - | **u** | - | rule |
| 25 | zai | 5 | pinyin | zai | - | **a** | - | rule |
| 26 | 我 | 5 | pinyin | wo | - | **o** | - | rule |
| 27 | 的 | 5 | pinyin | de | - | **e** | - | rule |
| 28 | 'a | 4 | pinyin | a | - | **a** | - | rule |
| 29 | ai | 4 | pinyin | ai | - | **a** | - | rule |
| 30 | hei | 4 | pinyin | hei | - | **e** | - | rule |
| 31 | huang | 4 | pinyin | huang | - | **a** | n | rule |
| 32 | ji | 4 | pinyin | ji | - | **i** | - | rule |
| 33 | jia | 4 | pinyin | jia | - | **a** | - | rule |
| 34 | man | 4 | pinyin | man | closed | **a** | n | rule |
| 35 | ni | 4 | pinyin | ni | - | **i** | - | rule |
| 36 | you | 4 | pinyin | you | - | **o** | - | rule |
| 37 | 是 | 4 | pinyin | shi | - | **i** | - | rule |
| 38 | 'an | 3 | pinyin | an | - | **a** | n | rule |
| 39 | bei | 3 | pinyin | bei | closed | **e** | - | rule |
| 40 | fu | 3 | pinyin | fu | f | **u** | - | rule |
| 41 | hai | 3 | pinyin | hai | - | **a** | - | rule |
| 42 | he | 3 | pinyin | he | - | **e** | - | rule |
| 43 | hui | 3 | pinyin | hui | - | **e** | - | rule |
| 44 | huo | 3 | pinyin | huo | - | **o** | - | rule |
| 45 | la | 3 | english | la | - | **a** | - | heuristic |
| 46 | wei | 3 | pinyin | wei | - | **e** | - | rule |
| 47 | xia | 3 | pinyin | xia | - | **a** | - | rule |
| 48 | xian | 3 | pinyin | xian | - | **e** | n | rule |
| 49 | yan | 3 | pinyin | yan | - | **e** | n | rule |
| 50 | yao | 3 | pinyin | yao | - | **a** | - | rule |
| 51 | zhe | 3 | pinyin | zhe | - | **e** | - | rule |
| 52 | zhu | 3 | pinyin | zhu | - | **u** | - | rule |
| 53 | 你 | 3 | pinyin | ni | - | **i** | - | rule |
| 54 | 像 | 3 | pinyin | xiang | - | **a** | n | rule |
| 55 | 好 | 3 | pinyin | hao | - | **a** | - | rule |
| 56 | 情 | 3 | pinyin | qing | - | **i** | n | rule |
| 57 | 愛 | 3 | pinyin | ai | - | **a** | - | rule |
| 58 | 沙 | 3 | pinyin | sha | - | **a** | - | rule |
| 59 | 流 | 3 | pinyin | liu | - | **o** | - | rule |
| 60 | 真 | 3 | pinyin | zhen | - | **e** | n | rule |
| 61 | 'er | 2 | pinyin | er | - | **e** | - | rule |
| 62 | 'wu | 2 | pinyin | wu | - | **u** | - | rule |
| 63 | .t 7 cl | 2 | xsampa | .t 7 cl | - | **e** | - | rule |
| 64 | bing | 2 | pinyin | bing | closed | **i** | n | rule |
| 65 | chu | 2 | pinyin | chu | - | **u** | - | rule |
| 66 | dai | 2 | pinyin | dai | - | **a** | - | rule |
| 67 | dang | 2 | pinyin | dang | - | **a** | n | rule |
| 68 | du | 2 | pinyin | du | - | **u** | - | rule |
| 69 | gan | 2 | pinyin | gan | - | **a** | n | rule |
| 70 | guo | 2 | pinyin | guo | - | **o** | - | rule |
| 71 | ha | 2 | pinyin | ha | - | **a** | - | rule |
| 72 | hi | 2 | english | hi | - | **i** | - | heuristic |
| 73 | lai | 2 | pinyin | lai | - | **a** | - | rule |
| 74 | lei | 2 | pinyin | lei | - | **e** | - | rule |
| 75 | luo | 2 | pinyin | luo | - | **o** | - | rule |
| 76 | mai | 2 | pinyin | mai | closed | **a** | - | rule |
| 77 | na | 2 | english | na | - | **a** | - | heuristic |
| 78 | neng | 2 | pinyin | neng | - | **e** | n | rule |
| 79 | pian | 2 | pinyin | pian | closed | **e** | n | rule |
| 80 | qu | 2 | pinyin | qu | - | **u** | - | rule |
| 81 | shan | 2 | pinyin | shan | - | **a** | n | rule |
| 82 | sheng | 2 | pinyin | sheng | - | **e** | n | rule |
| 83 | ye | 2 | pinyin | ye | - | **e** | - | rule |
| 84 | 吧 | 2 | pinyin | ba | closed | **a** | - | rule |
| 85 | 恍 | 2 | pinyin | huang | - | **a** | n | rule |
| 86 | 惚 | 2 | pinyin | hu | - | **u** | - | rule |
| 87 | 想 | 2 | pinyin | xiang | - | **a** | n | rule |
| 88 | 自 | 2 | pinyin | zi | - | **i** | - | rule |
| 89 | 路 | 2 | pinyin | lu | - | **u** | - | rule |
| 90 | 過 | 2 | pinyin | guo | - | **o** | - | rule |
| 91 | 'ang | 1 | pinyin | ang | - | **a** | n | rule |
| 92 | 'ei | 1 | pinyin | ei | - | **e** | - | rule |
| 93 | 'ou | 1 | pinyin | ou | - | **o** | - | rule |
| 94 | '愛 | 1 | pinyin | ai | - | **a** | - | rule |
| 95 | '牽 | 1 | pinyin | qian | - | **e** | n | rule |
| 96 | .:n ts a :\i | 1 | xsampa | .:n ts a :\i | - | **a** | n | rule |
| 97 | .@ :n cl | 1 | xsampa | .@ :n cl | - | **e** | n | rule |
| 98 | .A | 1 | xsampa | .A | - | **a** | - | rule |
| 99 | .U N cl | 1 | xsampa | .U N cl | - | **u** | n | rule |
| 100 | .a :\i cl | 1 | xsampa | .a :\i cl | - | **a** | - | rule |
| 101 | .cl a :\i cl | 1 | xsampa | .cl a :\i cl | closed | **a** | - | rule |
| 102 | .j e :\i | 1 | xsampa | .j e :\i | - | **e** | - | rule |
| 103 | .n p u | 1 | xsampa | .n p u | closed | **u** | - | rule |
| 104 | .p ie ts` | 1 | xsampa | .p ie ts` | closed | **e** | - | rule |
| 105 | .p u j | 1 | xsampa | .p u j | closed | **u** | - | rule |
| 106 | .s\ iA | 1 | xsampa | .s\ iA | - | **a** | - | rule |
| 107 | .s\ iAU cl | 1 | xsampa | .s\ iAU cl | - | **a** | - | rule |
| 108 | .s` i` cl | 1 | xsampa | .s` i` cl | - | **i** | - | rule |
| 109 | .ts i\ cl | 1 | xsampa | .ts i\ cl | - | **i** | - | rule |
| 110 | .ts\h iE :n cl | 1 | xsampa | .ts\h iE :n cl | - | **e** | n | rule |
| 111 | .x a :\i cl | 1 | xsampa | .x a :\i cl | - | **a** | - | rule |
| 112 | ang | 1 | pinyin | ang | - | **a** | n | rule |
| 113 | ao | 1 | pinyin | ao | - | **a** | - | rule |
| 114 | baby | 1 | english | baby | closed | **e** | - | heuristic |
| 115 | ban | 1 | pinyin | ban | closed | **a** | n | rule |
| 116 | bian | 1 | pinyin | bian | closed | **e** | n | rule |
| 117 | cang | 1 | pinyin | cang | - | **a** | n | rule |
| 118 | chan | 1 | pinyin | chan | - | **a** | n | rule |
| 119 | cuo | 1 | pinyin | cuo | - | **o** | - | rule |
| 120 | da | 1 | pinyin | da | - | **a** | - | rule |
| 121 | duo | 1 | pinyin | duo | - | **o** | - | rule |
| 122 | e | 1 | pinyin | e | - | **e** | - | rule |
| 123 | ei | 1 | pinyin | ei | - | **e** | - | rule |
| 124 | er | 1 | pinyin | er | - | **e** | - | rule |
| 125 | fa | 1 | pinyin | fa | f | **a** | - | rule |
| 126 | fang | 1 | pinyin | fang | f | **a** | n | rule |
| 127 | fei | 1 | pinyin | fei | f | **e** | - | rule |
| 128 | gai | 1 | pinyin | gai | - | **a** | - | rule |
| 129 | gu | 1 | pinyin | gu | - | **u** | - | rule |
| 130 | hua | 1 | pinyin | hua | - | **a** | - | rule |
| 131 | jian | 1 | pinyin | jian | - | **e** | n | rule |
| 132 | jiao | 1 | pinyin | jiao | - | **a** | - | rule |
| 133 | jing | 1 | pinyin | jing | - | **i** | n | rule |
| 134 | ka | 1 | pinyin | ka | - | **a** | - | rule |
| 135 | kan | 1 | pinyin | kan | - | **a** | n | rule |
| 136 | ku | 1 | pinyin | ku | - | **u** | - | rule |
| 137 | lan | 1 | pinyin | lan | - | **a** | n | rule |
| 138 | lang | 1 | pinyin | lang | - | **a** | n | rule |
| 139 | lao | 1 | pinyin | lao | - | **a** | - | rule |
| 140 | lv | 1 | pinyin | lv | - | **u** | - | rule |
| 141 | mian | 1 | pinyin | mian | closed | **e** | n | rule |
| 142 | ming | 1 | pinyin | ming | closed | **i** | n | rule |
| 143 | nai | 1 | pinyin | nai | - | **a** | - | rule |
| 144 | ne | 1 | pinyin | ne | - | **e** | - | rule |
| 145 | nou | 1 | pinyin | nou | - | **o** | - | rule |
| 146 | nuo | 1 | pinyin | nuo | - | **o** | - | rule |
| 147 | oh | 1 | english | oh | - | **o** | - | heuristic |
| 148 | pa | 1 | pinyin | pa | closed | **a** | - | rule |
| 149 | qi | 1 | pinyin | qi | - | **i** | - | rule |
| 150 | qin | 1 | pinyin | qin | - | **i** | n | rule |
| 151 | rang | 1 | pinyin | rang | - | **a** | n | rule |
| 152 | san | 1 | pinyin | san | - | **a** | n | rule |
| 153 | sha | 1 | pinyin | sha | - | **a** | - | rule |
| 154 | shang | 1 | pinyin | shang | - | **a** | n | rule |
| 155 | shei | 1 | pinyin | shei | - | **e** | - | rule |
| 156 | shu | 1 | pinyin | shu | - | **u** | - | rule |
| 157 | shui | 1 | pinyin | shui | - | **e** | - | rule |
| 158 | sui | 1 | pinyin | sui | - | **e** | - | rule |
| 159 | ta | 1 | pinyin | ta | - | **a** | - | rule |
| 160 | tai | 1 | pinyin | tai | - | **a** | - | rule |
| 161 | tu | 1 | pinyin | tu | - | **u** | - | rule |
| 162 | wai | 1 | pinyin | wai | - | **a** | - | rule |
| 163 | wen | 1 | pinyin | wen | - | **e** | n | rule |
| 164 | xie | 1 | pinyin | xie | - | **e** | - | rule |
| 165 | xin | 1 | pinyin | xin | - | **i** | n | rule |
| 166 | xing | 1 | pinyin | xing | - | **i** | n | rule |
| 167 | yang | 1 | pinyin | yang | - | **a** | n | rule |
| 168 | yeah | 1 | english | yeah | - | **e** | - | heuristic |
| 169 | yin | 1 | pinyin | yin | - | **i** | n | rule |
| 170 | yu | 1 | pinyin | yu | - | **u** | - | rule |
| 171 | yuan | 1 | pinyin | yuan | - | **e** | n | rule |
| 172 | zao | 1 | pinyin | zao | - | **a** | - | rule |
| 173 | ze | 1 | pinyin | ze | - | **e** | - | rule |
| 174 | zheng | 1 | pinyin | zheng | - | **e** | n | rule |
| 175 | zhou | 1 | pinyin | zhou | - | **o** | - | rule |
| 176 | zi | 1 | pinyin | zi | - | **i** | - | rule |
| 177 | zou | 1 | pinyin | zou | - | **o** | - | rule |
| 178 | zui | 1 | pinyin | zui | - | **e** | - | rule |
| 179 | zuo | 1 | pinyin | zuo | - | **o** | - | rule |
| 180 | 一 | 1 | pinyin | yi | - | **i** | - | rule |
| 181 | 下 | 1 | pinyin | xia | - | **a** | - | rule |
| 182 | 並 | 1 | pinyin | bing | closed | **i** | n | rule |
| 183 | 主 | 1 | pinyin | zhu | - | **u** | - | rule |
| 184 | 也 | 1 | pinyin | ye | - | **e** | - | rule |
| 185 | 以 | 1 | pinyin | yi | - | **i** | - | rule |
| 186 | 全 | 1 | pinyin | quan | - | **a** | n | rule |
| 187 | 其 | 1 | pinyin | qi | - | **i** | - | rule |
| 188 | 再 | 1 | pinyin | zai | - | **a** | - | rule |
| 189 | 去 | 1 | pinyin | qu | - | **u** | - | rule |
| 190 | 又 | 1 | pinyin | you | - | **o** | - | rule |
| 191 | 回 | 1 | pinyin | hui | - | **e** | - | rule |
| 192 | 它 | 1 | pinyin | ta | - | **a** | - | rule |
| 193 | 害 | 1 | pinyin | hai | - | **a** | - | rule |
| 194 | 實 | 1 | pinyin | shi | - | **i** | - | rule |
| 195 | 己 | 1 | pinyin | ji | - | **i** | - | rule |
| 196 | 已 | 1 | pinyin | yi | - | **i** | - | rule |
| 197 | 幸 | 1 | pinyin | xing | - | **i** | n | rule |
| 198 | 心 | 1 | pinyin | xin | - | **i** | n | rule |
| 199 | 怕 | 1 | pinyin | pa | closed | **a** | - | rule |
| 200 | 扎 | 1 | pinyin | zha | - | **a** | - | rule |
| 201 | 掙 | 1 | pinyin | zheng | - | **e** | n | rule |
| 202 | 掛 | 1 | pinyin | gua | - | **a** | - | rule |
| 203 | 放 | 1 | pinyin | fang | f | **a** | n | rule |
| 204 | 早 | 1 | pinyin | zao | - | **a** | - | rule |
| 205 | 會 | 1 | pinyin | hui | - | **e** | - | rule |
| 206 | 有 | 1 | pinyin | you | - | **o** | - | rule |
| 207 | 样 | 1 | pinyin | yang | - | **a** | n | rule |
| 208 | 楚 | 1 | pinyin | chu | - | **u** | - | rule |
| 209 | 清 | 1 | pinyin | qing | - | **i** | n | rule |
| 210 | 為 | 1 | pinyin | wei | - | **e** | - | rule |
| 211 | 爱 | 1 | pinyin | ai | - | **a** | - | rule |
| 212 | 由 | 1 | pinyin | you | - | **o** | - | rule |
| 213 | 看 | 1 | pinyin | kan | - | **a** | n | rule |
| 214 | 眼 | 1 | pinyin | yan | - | **e** | n | rule |
| 215 | 福 | 1 | pinyin | fu | f | **u** | - | rule |
| 216 | 而 | 1 | pinyin | er | - | **e** | - | rule |
| 217 | 著 | 1 | pinyin | zhe | - | **e** | - | rule |
| 218 | 裡 | 1 | pinyin | li | - | **i** | - | rule |
| 219 | 讓 | 1 | pinyin | rang | - | **a** | n | rule |
| 220 | 走 | 1 | pinyin | zou | - | **o** | - | rule |
| 221 | 这 | 1 | pinyin | zhe | - | **e** | - | rule |
| 222 | 還 | 1 | pinyin | hai | - | **a** | - | rule |
| 223 | 都 | 1 | pinyin | dou | - | **o** | - | rule |
| 224 | 隨 | 1 | pinyin | sui | - | **e** | - | rule |
| 225 | 頭 | 1 | pinyin | tou | - | **o** | - | rule |
| 226 | 願 | 1 | pinyin | yuan | - | **e** | n | rule |
| 227 | 騙 | 1 | pinyin | pian | closed | **e** | n | rule |
