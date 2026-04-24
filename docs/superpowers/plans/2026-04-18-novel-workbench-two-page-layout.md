# Novel Workbench Two-Page Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前混杂的小说工作台重构为“写作工作台”和“配置中心”两个独立页面，收拢英文/乱码文案，保留现有生成、导入、章节历史、故事切换等能力，同时让 API 与 Agent 配置集中到单独页面管理。

**Architecture:** 采用固定左侧导航 + 独立路由页面结构。`/` 负责创作与章节推进，`/config` 负责全局 API、Agent 覆盖与运行策略配置。共享状态仍通过现有接口与前端数据层读取，不引入新的全局状态库；主要通过拆分现有大型组件、清理页面职责、补充导航壳层和测试用例完成本次改版。

**Tech Stack:** Next.js App Router, React 18, TypeScript, FastAPI, Playwright, pytest.

---

### Task 1: 建立新的双页导航骨架

**Files:**
- Modify: `apps/web/app/layout.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/app/config/page.tsx`
- Create: `apps/web/components/AppShell.tsx`
- Create: `apps/web/components/AppSidebarNav.tsx`
- Modify: `apps/web/app/globals.css`

- [ ] **Step 1: 先写页面级导航测试**

在 `apps/web/tests/story-workbench.spec.ts` 或新增独立组件测试里补一个最小断言，确认首页和配置页都存在清晰入口与标题。

```tsx
it("shows workbench and config navigation", async () => {
  render(<AppShell><div>content</div></AppShell>);
  expect(screen.getByRole("link", { name: "写作工作台" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "配置中心" })).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认当前失败**

Run: `npm --prefix apps/web test -- --runInBand story-workbench`

Expected: FAIL，因为当前还没有统一导航壳层。

- [ ] **Step 3: 实现共享壳层**

新增 `AppShell.tsx` 和 `AppSidebarNav.tsx`，封装：
- 左侧固定导航
- 页面标题区
- 页面描述区
- 主内容容器

建议接口：

```tsx
export function AppShell({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="app-shell">
      <AppSidebarNav />
      <main className="app-shell__main">
        <header className="app-shell__header">
          <h1>{title}</h1>
          {description ? <p>{description}</p> : null}
        </header>
        <section className="app-shell__content">{children}</section>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: 把首页与配置页接入壳层**

`apps/web/app/page.tsx` 和 `apps/web/app/config/page.tsx` 都改为使用 `AppShell`，不要再各自重复导航与标题结构。

- [ ] **Step 5: 复跑测试确认通过**

Run: `npm --prefix apps/web test -- --runInBand story-workbench`

Expected: PASS。

---

### Task 2: 重构写作工作台，让创作区与系统区彻底分离

**Files:**
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/components/StorySidebar.tsx`
- Modify: `apps/web/components/BookImportPanel.tsx`
- Modify: `apps/web/components/BookLibraryBrowser.tsx`
- Modify: `apps/web/components/ChapterBundleView.tsx`
- Create: `apps/web/components/workbench/WorkbenchInputColumn.tsx`
- Create: `apps/web/components/workbench/WorkbenchChapterColumn.tsx`
- Create: `apps/web/components/workbench/WorkbenchStatusColumn.tsx`
- Create: `apps/web/components/workbench/StoryRunStatusCard.tsx`

- [ ] **Step 1: 写工作台结构的失败测试**

补一个页面测试，确认首页不再展示 API 配置表单，而是展示三个主要区域：创作输入、章节阅读、故事状态。

```tsx
it("keeps api configuration out of the workbench page", async () => {
  render(<HomePage />);
  expect(screen.getByText("导入书籍目录")).toBeInTheDocument();
  expect(screen.getByText("当前章节")).toBeInTheDocument();
  expect(screen.getByText("故事状态")).toBeInTheDocument();
  expect(screen.queryByText("全局 API 密钥")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix apps/web test -- --runInBand story-workbench`

Expected: FAIL，因为首页目前仍混有配置内容或旧结构断言不成立。

- [ ] **Step 3: 拆分首页为三栏**

把首页拆成三个明确区域：
- 左栏：大纲、导演补充、角色卡、导入入口
- 中栏：当前章节、章节正文、生成下一章、回滚
- 右栏：故事状态、Agent 状态、章节历史、故事切换

要求：
- `StorySidebar.tsx` 不再承担整个右侧全部布局逻辑，只保留“状态/历史/分支”职责
- `BookImportPanel.tsx` 只处理导入与预读，不夹带系统设置表单
- `ChapterBundleView.tsx` 负责正文与摘要展示，减少页面级拼装复杂度

- [ ] **Step 4: 清理英文与占位提示**

把首页出现的英文提示、测试 mock 说明、零散错误文案统一改成中文。重点检查：
- 生成按钮状态文案
- “No state yet” / “Server Error” 之类提示
- 章节正文标题和摘要说明
- 运行模式提示

- [ ] **Step 5: 复跑页面测试**

Run: `npm --prefix apps/web test -- --runInBand story-workbench`

Expected: PASS。

---

### Task 3: 重建配置中心，集中管理全局与 Agent 独立配置

**Files:**
- Modify: `apps/web/app/config/page.tsx`
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/components/config/ConfigPageClient.tsx`
- Create: `apps/web/components/config/GlobalApiConfigCard.tsx`
- Create: `apps/web/components/config/AgentOverrideGrid.tsx`
- Create: `apps/web/components/config/AgentConfigCard.tsx`
- Create: `apps/web/components/config/RuntimeStrategyCard.tsx`

- [ ] **Step 1: 先补配置页交互测试**

新增或修改测试，确认配置页单独展示：
- 全局 API 配置
- 四个 Agent 的独立 API / Base URL / 模型覆写
- 统一保存按钮
- 测试连接按钮

```tsx
it("shows global and per-agent configuration on config page", async () => {
  render(<ConfigPage />);
  expect(screen.getByText("全局默认配置")).toBeInTheDocument();
  expect(screen.getByText("角色代理")).toBeInTheDocument();
  expect(screen.getByText("导演代理")).toBeInTheDocument();
  expect(screen.getByText("写作代理")).toBeInTheDocument();
  expect(screen.getByText("记忆代理")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix apps/web test -- --runInBand story-workbench`

Expected: FAIL，因为现有配置页结构混乱且文案异常。

- [ ] **Step 3: 重写配置页组件树**

将 `apps/web/app/config/page.tsx` 改为纯页面壳，实际交互逻辑放进 `ConfigPageClient.tsx`。页面结构建议：
- 顶部说明
- 全局默认配置卡片
- Agent 覆盖网格
- 运行策略卡片
- 底部统一保存栏

每个 Agent 卡片至少包含：
- 是否启用独立覆盖
- API Key
- Base URL
- 模型名
- 回退说明（留空即继承全局）

- [ ] **Step 4: 保持与后端现有保存接口兼容**

核对 `apps/web/lib/api.ts` 中的请求结构，确保：
- 页面载入时能读出当前保存值
- 保存时提交全局配置 + 每个 Agent 覆盖
- 测试连接支持“全局默认”和“单 Agent 覆盖”两种场景

如果后端字段已经存在，仅清理前端映射；如果前端结构偏差，就补一层转换函数，例如：

```ts
function toAgentOverridePayload(form: AgentFormState): AgentOverridePayload | null {
  if (!form.enabled) return null;
  return {
    apiKey: form.apiKey || undefined,
    baseUrl: form.baseUrl || undefined,
    model: form.model || undefined,
  };
}
```

- [ ] **Step 5: 复跑配置相关测试**

Run: `npm --prefix apps/web test -- --runInBand story-workbench`

Expected: PASS。

---

### Task 4: 修复导入书籍后的主流程入口，确保“导入后可直接开始生成”

**Files:**
- Modify: `apps/web/components/BookImportPanel.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/lib/api.ts`
- Modify: `tests/e2e/book-import-entry.spec.ts`
- Modify: `tests/e2e/story-generation.spec.ts`

- [ ] **Step 1: 先写端到端失败用例**

覆盖如下流程：
1. 输入书籍目录
2. 校验目录成功
3. 载入工作台成功
4. 页面出现“开始生成第一章”或等价主按钮

```ts
test("imported book can immediately start chapter generation", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("本地目录路径").fill(samplePath);
  await page.getByRole("button", { name: "校验目录" }).click();
  await page.getByRole("button", { name: "载入到工作台" }).click();
  await expect(page.getByRole("button", { name: /开始生成第一章|生成下一章/ })).toBeVisible();
});
```

- [ ] **Step 2: 运行用例确认失败**

Run: `npx playwright test tests/e2e/book-import-entry.spec.ts --project=chromium`

Expected: FAIL，如果当前导入后没有主操作入口或入口位置不明确。

- [ ] **Step 3: 在工作台显式展示主流程状态**

导入成功后，中栏顶部明确显示：
- 当前故事标题
- 当前章节数
- 若还未生成章节，显示“开始生成第一章”
- 若已有章节，显示“生成下一章”

同时保留导入结果摘要，不要让用户导入后失去方向。

- [ ] **Step 4: 复跑端到端测试**

Run: `npx playwright test tests/e2e/book-import-entry.spec.ts tests/e2e/story-generation.spec.ts --project=chromium`

Expected: PASS。

---

### Task 5: 统一中文文案与视觉风格，去掉“拼起来的后台面板”感

**Files:**
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/app/config/page.tsx`
- Modify: `apps/web/components/**/*.tsx`（仅涉及展示文案与 className 的组件）

- [ ] **Step 1: 整理文案清单**

按页面梳理需要替换的英文/乱码文案：
- 首页按钮、空态、错误态、说明文案
- 配置页说明、测试结果、保存反馈
- Agent 状态描述
- 导入校验反馈

- [ ] **Step 2: 建立统一视觉变量**

在 `globals.css` 中定义页面级变量，例如：

```css
:root {
  --bg: #f7efe2;
  --panel: rgba(255, 250, 242, 0.92);
  --panel-border: rgba(162, 118, 57, 0.2);
  --text-main: #2f2419;
  --text-muted: #7a6753;
  --accent: #9d5b2a;
  --accent-strong: #6f3b14;
}
```

目标不是简单换色，而是让两个页面共享稳定的产品气质：
- 左侧导航更像创作软件
- 中间正文区更像阅读/编辑器
- 配置页更像控制台，但仍保持同一视觉体系

- [ ] **Step 3: 优化布局细节**

至少处理这些问题：
- 卡片留白过散或过挤
- 主按钮层级不明显
- 正文区可读性差
- 表单区密度过高
- 移动端下三栏堆叠顺序混乱

- [ ] **Step 4: 手动回归两页观感**

Run:
- `npm --prefix apps/web run dev`
- 打开 `/`
- 打开 `/config`

检查点：
- 两页都能一眼看懂主任务
- 配置不再打断写作
- 没有明显英文或乱码残留

---

### Task 6: 补齐回归测试，避免旧功能在拆页后失效

**Files:**
- Modify: `apps/web/tests/story-workbench.spec.ts`
- Modify: `tests/e2e/book-import-entry.spec.ts`
- Modify: `tests/e2e/story-generation.spec.ts`
- Modify: `tests/e2e/story-character-controls.spec.ts`
- Modify: `tests/e2e/story-cast-and-rollback.spec.ts`

- [ ] **Step 1: 更新首页入口选择器**

旧测试如果假设 API 配置和写作面板同页，需要改成：
- 首页只测创作流程
- `/config` 单独测配置流程

- [ ] **Step 2: 补配置页测试**

增加：
- 进入 `/config` 可看到全局默认配置
- 修改表单后可保存
- 测试连接反馈能回显到当前卡片

- [ ] **Step 3: 补工作台历史与故事切换检查**

确保拆页后以下功能仍可用：
- 历史章节列表展示
- 点击历史章节可回看
- 故事分支切换
- 回滚到上一章

- [ ] **Step 4: 运行完整前端回归**

Run:
- `npm --prefix apps/web test -- --runInBand`
- `npx playwright test tests/e2e/book-import-entry.spec.ts tests/e2e/story-generation.spec.ts tests/e2e/story-character-controls.spec.ts tests/e2e/story-cast-and-rollback.spec.ts --project=chromium`

Expected: 全部 PASS。

---

### Task 7: 最终联调与验收

**Files:**
- Modify only if verification reveals issues

- [ ] **Step 1: 运行前后端联调**

Run:
- `uvicorn apps.api.main:app --reload --port 8000`
- `npm --prefix apps/web run dev -- --port 3000`

- [ ] **Step 2: 手动验收关键路径**

按顺序验证：
1. 打开首页，能看见写作工作台
2. 打开配置中心，能看见全局与 Agent 配置
3. 保存一套全局配置
4. 给单个 Agent 设置独立 API / 模型
5. 返回首页导入书籍目录
6. 载入工作台
7. 生成第一章
8. 查看历史章节
9. 切换故事或回滚章节

- [ ] **Step 3: 记录剩余问题**

如果还有残留问题，只记录真实存在的问题，例如：
- 某个错误提示仍是英文
- 某个 Agent 卡片保存后未即时刷新
- 小屏宽度下右栏折叠策略还不够好

不要写笼统的“继续优化 UI”。

---

### Implementation Notes

- 现有工作区是脏的，动手前先逐文件确认不要覆盖用户已有修改。
- `apps/web/app/config/page.tsx` 已有历史内容且包含明显乱码，重写时优先保留接口契约，丢弃失真的旧展示层。
- 这次改版不引入新的多 Agent 编排逻辑，重点是把已有能力放进正确的页面结构里。
- 首页必须始终围绕“当前章节”和“下一步生成”组织，而不是围绕系统表单组织。
- 配置页必须支持“全局默认 + 单 Agent 覆盖”，并清楚表达继承关系。

### Verification Checklist

Run all:

```bash
npm --prefix apps/web test -- --runInBand
npx playwright test tests/e2e/book-import-entry.spec.ts tests/e2e/story-generation.spec.ts tests/e2e/story-character-controls.spec.ts tests/e2e/story-cast-and-rollback.spec.ts --project=chromium
npm --prefix apps/web run build
```

Manual smoke check:

```bash
uvicorn apps.api.main:app --reload --port 8000
npm --prefix apps/web run dev -- --port 3000
```
