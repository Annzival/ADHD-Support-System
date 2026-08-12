## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical triage role names are used unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.

### 文档语言

新增和更新的项目文档正文默认使用简体中文。代码标识符、文件名、协议、库和产品的正式名称保留原文；领域词汇在需要与代码命名对应时采用“中文规范名（英文映射）”。

### Grilling 发布流程

Grilling 过程中产生的文档变更，按照 `docs/agents/grilling-git-workflow.md` 自主组织分支、commit、push 和 Draft PR。

### 产品治理主线程

产品治理、MVP 构建就绪判断以及 research、prototype、technical spike、implementation 的任务分流，遵循 `docs/agents/product-governance-thread.md`。技术线程不得自行改变产品范围或覆盖已有 ADR；发现冲突时必须返回产品治理主线程决策。
