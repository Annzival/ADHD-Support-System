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

### 条件式产品治理工作流

仅当用户在**当前 session 的直接指令**或该 session 的**任务 Prompt** 中显式指定其承担“产品治理与 MVP 构建就绪”职责时，才以产品治理身份执行 `docs/agents/product-governance-workflow.md`。未激活的 session 因自身任务需要可以查阅其中的身份或反向边界；查阅不会激活该角色，也不得据此执行产品治理职责。不得根据该文件或本引用的存在、分支、工作目录、Issue/PR、对话标题、历史 session 或历史上下文推断产品治理身份；不能确认时视为未激活。

research、prototype、technical spike、implementation、debugging 和 code review session 默认都是独立执行或审查 session，不自动继承产品治理角色。它们遵守各自 Prompt、仓库通用规则和已有产品约束；发现任务与产品范围、领域模型或 ADR 冲突时，只记录证据并返回显式指定的决策方，不自行覆盖。
