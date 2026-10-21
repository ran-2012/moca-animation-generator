# 文档索引

| 文件 | 说明 |
|---|---|
| [`../README.md`](../README.md) | 项目总览、运行方式、当前状态 |
| [`../CONTRACT.md`](../CONTRACT.md) | 前后端接口与数据契约（开发必读） |
| [`technical-plan.md`](technical-plan.md) | 开源预研结论与可落地方案（归档副本） |
| [`requirement.md`](requirement.md) | 最初需求记录 |
| [`research/`](research/) | 四份详细预研/分析报告 |

## 关于归档副本

`technical-plan.md` 与 `research/*.md` 是从工作区外的原始资料复制进来的，便于仓库自包含。
原始资料还包含原型代码、demo 视频和报告图片，位于仓库外的 `prototype/` 与 `报告附件/`，
不纳入本仓库（其中 mp4 / png 体积较大，且部分素材有再配布限制）。

## 渲染预览图

原先放在 `docs/` 的两张导出预览图（`preview_export_frame.jpg`、`preview_export_contact.jpg`）
是从角色差分素材渲染出来的，**不适合随仓库分发**，已移到本地忽略目录 `data/docs-preview/`。

需要查看效果时，在本地运行导出后查看 `data/renders/`，或使用：

```powershell
python scripts/render_smoke.py
```

## 素材授权

`moca.psd` 及其差分图、`流沙.svp`、角色立绘/音频、以及由这些素材渲染出的预览图/视频
**均不在本仓库中**，版权归原作者所有；使用前请阅读素材自带的 `readme.txt`
（通常为非商用、禁止二次配布）。本仓库只包含工具代码。
