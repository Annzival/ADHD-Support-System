## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical triage role names are used unchanged. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository. See `docs/agents/domain.md`.

### 文档语言

新增和更新的项目文档正文默认使用简体中文。代码标识符、文件名、协议、库和产品的正式名称保留原文；领域词汇在需要与代码命名对应时采用“中文规范名（英文映射）”。

### 面向用户的解释

- 先说具体发生了什么、谁做了什么，以及用户会看到什么结果，再按需附上规范术语；术语一致不等于每句话都用术语。
- 新术语首次出现时用当前场景解释；“合法”“有效”“可核验”等判断必须指出由谁按什么条件判断。条件尚未确定时直说未确定，不用抽象措辞遮盖缺口。
- 请用户决定产品行为和取舍，不把可自行查证的技术事实或可逆实现细节变成用户问答。选项说明实际结果、代价和推荐原因，而不只列技术名词。
- 用户表示困惑时，先重写说明并用一个具体例子核对理解，不把问题归因为用户知识不足，也不把此前的接受扩展到未说明的细节。

这些是本仓库所有任务面向用户的沟通规则，不激活产品治理角色，不改变 ADR、任务范围或权限；正式规格仍使用统一术语和可测试规则。

### Grilling 发布流程

Grilling 过程中产生的文档变更，按照 `docs/agents/grilling-git-workflow.md` 自主组织分支、commit、push 和 Draft PR。

### 条件式产品治理工作流

仅当用户在**当前 session 的直接指令**或该 session 的**任务 Prompt** 中显式指定其承担“产品治理与 MVP 构建就绪”职责时，才以产品治理身份执行 `docs/agents/product-governance-workflow.md`。未激活的 session 因自身任务需要可以查阅其中的身份或反向边界；查阅不会激活该角色，也不得据此执行产品治理职责。不得根据该文件或本引用的存在、分支、工作目录、Issue/PR、对话标题、历史 session 或历史上下文推断产品治理身份；不能确认时视为未激活。

research、prototype、technical spike、implementation、debugging 和 code review session 默认都是独立执行或审查 session，不自动继承产品治理角色。它们遵守各自 Prompt、仓库通用规则和已有产品约束；发现任务与产品范围、领域模型或 ADR 冲突时，只记录证据并返回显式指定的决策方，不自行覆盖。
