# Contributing / 贡献指南

感谢你关注 NovelFlow Engine。我们欢迎 Bug 修复、文档改进、测试、性能优化、创作工作流改进以及新的模块化能力。

## 开始之前

1. 先搜索现有 Issue 和 Pull Request，避免重复工作。
2. 对较大的功能、架构调整或数据格式变化，建议先创建 Issue 说明目标、范围和兼容性影响。
3. 不要提交 API Key、Token、Cookie、个人信息、真实用户小说数据或其他敏感内容。
4. 尽量保持改动聚焦，避免在同一个 PR 中混入无关重构。

## 本地开发

创建配置：

```bash
cp .env.example .env.local
```

启动 API：

```bash
uvicorn apps.api.main:app --reload --port 8000
```

启动 Web：

```bash
cd apps/web
npm install
npm run dev
```

## 测试

提交 PR 前，请至少运行与你改动相关的测试。完整测试基线包括：

```bash
pytest -q
cd apps/web
npx playwright test
```

如果无法运行完整测试，请在 PR 中明确写出已运行的测试和未运行的部分。

## Pull Request 要求

- 说明问题是什么、为什么需要修改。
- 说明主要实现方式及兼容性影响。
- 对行为变化补充或更新测试。
- 对用户可见的配置、API、工作流变化更新文档。
- 不要覆盖用户手工编辑的小说内容或项目状态，除非该行为本身就是经过讨论的变更目标。
- 涉及持久化、迁移、章节重生成时，应优先保证可回滚、幂等和源数据安全。

## 提交与许可

向本仓库提交贡献，即表示你有权提交相关内容，并同意你的贡献按照本仓库的 Apache License 2.0 许可条款提供。

---

Contributions are welcome. Please keep changes focused, document behavioral changes, add relevant tests, and never commit secrets or private user data. By submitting a contribution, you agree that it may be distributed under the repository's Apache License 2.0.
