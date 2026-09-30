# 四页工作台最终浏览器验收（2026-09-30）

本记录补充 [60 章 HTTP 复验](acceptance-2026-09-30.md)，供阶段四最终页面验收复审。

## 验收基线

- 页面代码来自 `748fe6dff02da56139b8d1f31e515365e86397c6`。其后的 `188888368f682917813d461f424dd85ae57375fe` 只记录了长程验收文档和事件证据，没有改运行代码。
- 使用隔离的 `longform_synthetic` API 与 Playwright Chromium。API 返回合成作品“离线长程验收”，含 60 个已确认章节。
- 桌面视口为 `1487 × 1058`，手机视口为 `390 × 844`。每个视口逐项操作并截图。
- 设置页由浏览器拦截并提供空凭据的离线设置与“尚未测试”状态；没有读取或保存真实供应商凭据，也没有触发模型连接测试。
- 本轮只读工作区 API 页面状态并切换页面／分类；没有提交写作命令、编辑配置或更改合成作品。

## 实测结果

- **四页 + 设置**：作品、全书规划、写作、故事设定和设置均可在桌面和 390px 手机视口打开；共 10 张截图。
- **布局**：10 个页面状态下，`documentElement.scrollWidth` 和 `body.scrollWidth` 都等于视口宽度；未发现横向溢出。
- **浏览器错误**：本轮页面 JavaScript 错误数为 0。
- **导航与回退**：`/` 与 `/books` 均进入 `/workspace`；旧 `/projects/{id}/write` 返回 200 并显示“章节创作”；`/projects/new` 显示新建小说，未出现名为 `new` 的项目导航。
- **设置范围**：只验证 `/config` 路由和页面展示。设置接口使用本地浏览器离线占位响应，不代表真实凭据配置、保存或模型连通性验收。

## 页面截图

| 页面 | 桌面 1487 × 1058 | 手机 390 × 844 |
| --- | --- | --- |
| 作品 | [桌面截图](evidence/browser-2026-09-30/作品-desktop.jpg) | [手机截图](evidence/browser-2026-09-30/作品-mobile.jpg) |
| 全书规划 | [桌面截图](evidence/browser-2026-09-30/全书规划-desktop.jpg) | [手机截图](evidence/browser-2026-09-30/全书规划-mobile.jpg) |
| 写作 | [桌面截图](evidence/browser-2026-09-30/写作-desktop.jpg) | [手机截图](evidence/browser-2026-09-30/写作-mobile.jpg) |
| 故事设定 | [桌面截图](evidence/browser-2026-09-30/故事设定-desktop.jpg) | [手机截图](evidence/browser-2026-09-30/故事设定-mobile.jpg) |
| 设置 | [桌面截图](evidence/browser-2026-09-30/设置-desktop.jpg) | [手机截图](evidence/browser-2026-09-30/设置-mobile.jpg) |

## 复审结论

2026-09-30 独立复审者按 HEAD `e526d6cd11c27b3e6d9727c9fcafab7d06008c12` 核对本记录、10 张截图、既有 FastAPI／浏览器交互证据、60 章 HTTP 事件与精确 HEAD CI，结论为 **阶段四 ACCEPT**。阶段 0–4 均已 ACCEPT；本记录只补页面验收证据，不改变运行代码。
