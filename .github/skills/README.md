# UI 设计技能

本次只添加技能及许可，不修改界面、依赖、项目指令或用户级配置。先审核技能，再决定是否用它审查和重设计 UI。

## 已添加

### frontend-design

- 来源：[Anthropic 官方 skills](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/frontend-design)。
- 固定版本：`dbd4588f9e1033efb41dad4bef2f7947c8993d44`。
- [技能原文](frontend-design/SKILL.md)保持英文，未修改内容；[许可](frontend-design/LICENSE.txt)为 Apache 2.0。
- 用途：设计方向、字体、配色、布局、动效、界面文案，以及对模板化设计的自查。
- 针对的问题：整页相同圆角卡片、装饰渐变、无意义编号、机械入场动效、与产品无关的视觉套件。
- 使用方式：审核后，在聊天中明确要求“使用 frontend-design 审查当前界面，先给方案，不改代码”。

放在 Copilot 可发现的项目级技能目录，不添加全局自动执行规则。新增技能若未被识别，可重新打开聊天或重载窗口。

## 候选比较

查询日期：2026-10-22。安装量和 stars 为查询时页面显示值，会变化。

| 技能 | 来源与规模 | 取舍 |
|---|---|---|
| [frontend-design](https://skills.sh/anthropics/skills/frontend-design) | Anthropic 官方；约 100 万安装，仓库约 18.3 万 stars | 本次添加。纯文档，直接覆盖“去 AI 模板感”，便于逐条审核。 |
| [Impeccable](https://github.com/pbakaus/impeccable) | Paul Bakaus；仓库约 8.5 万 stars | 包含 critique、distill、audit 等设计流程。新版集成为单一 impeccable 技能，旧 frontend-design 已弃用；完整安装涉及引擎下载、hooks，部分功能联网。暂不添加。 |
| [web-design-guidelines](https://skills.sh/vercel-labs/agent-skills/web-design-guidelines) | Vercel 官方；仓库约 3.3 万 stars | 偏可访问性、交互和实现质量审查。技能要求每次联网读取最新规则，不能保证审核后规则固定。暂不添加。 |

## 审核要点

原文的“hero”“大胆风格”和移动端建议不是本项目的硬性设计目标。MocaDiff 是桌面创作工作台，不是营销落地页。

后续使用时应遵守：

- 先说明具体问题和视觉方向，获得确认后再改 UI，不因技能已添加就开始重设计。
- 优先保证舞台、图层、属性面板、时间轴的信息层级和操作效率，不为“独特”增加装饰。
- 不把“去 AI 味”直接等同于极简、复古、暗色或零圆角；方向由用户审核。
- 保留中文文案、Canvas 2D、可拖动分栏、舞台与时间轴交互、播放同步和 Session 恢复。
- 不为换风格引入组件库、WebGL、远端字体或素材上传。
- 项目约束以根目录 [AGENTS.md](../../AGENTS.md)、[README.md](../../README.md) 和 [CONTRACT.md](../../CONTRACT.md) 为准。

## 安全检查

已通读技能正文并核对上游目录。该版本只有技能文档与许可，无脚本、hooks、二进制、依赖安装指令、外部 API 调用或密钥读取要求。未发现数据外传或越权操作指令。

本次未执行第三方安装器，未安装 Impeccable 引擎，未设置自动更新。以后更新技能时需重新检查差异。