# 验证脚本

这些脚本依赖**工作区根目录**下的示例素材（`moca.psd`、`流沙.svp` 等），
素材不纳入本仓库，因此克隆后需要先把素材放到仓库上一级目录，或修改脚本里的路径。

| 脚本 | 用途 |
|---|---|
| `e2e_smoke.py` | 后端 PSD/SVP/音频/项目/渲染接口的端到端冒烟，产出 `data/e2e_report.json` |
| `render_smoke.py` | 直接调用渲染服务验证 PNG / ProRes / WebM / MP4 输出 |

前端 UI 冒烟不在这里：

```powershell
cd frontend
npm run smoke
```
