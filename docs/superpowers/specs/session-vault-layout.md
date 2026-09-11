# 本地会话 Vault 目录与 Bundle 规范

**状态：** 已确认的设计
**日期：** 2026-08-07
**所属设计：** [网页与本地会话到 Obsidian 知识管道](web-to-obsidian-knowledge-pipeline-design.md)
**范围：** Codex rollout 与 WorkBuddy conversation JSONL 的会话来源 bundle 在 `01 Sources/Sessions/` 中的物化

## 1. 定位与规范层级

本文是会话来源的最终 Vault 物化规范。它定义如何将已验证的 `ConversationNormalized` 写为稳定目录、当前 bundle 文件、锚点、原始内容和增量发布；不定义 JSONL 的读取、provider schema 映射、记录归并或知识提炼算法。上游输入、游标、provider 映射和 evidence block 的生产规则由[本地会话到 OKF Producer 规范](session-to-okf-producer.md)定义。

主设计稿中的 Vault 根目录配置、OKF v0.2 合规边界、标识符与 slug 验证、受管区块保护、发布事务、安全与保留策略均直接适用。由会话 producer 产出的 `ConversationNormalized` 是本文唯一的上游输入。

## 2. 目录与当前 bundle

每个 session 使用一个稳定目录，只保留当前可消费的来源 bundle。历史内容由 Evidence Store 按 `document_version_id` 保存，不在 Vault 内复制历史目录：

```text
01 Sources/
  Sessions/
    <provider>/
      index.md                         # session ID 与标题索引；无 frontmatter
      <session-id>/
        index.md                         # bundle 清单；无 frontmatter
        log.md                           # 变更历史；无 frontmatter
        session.md                       # type: Agent Session
        reasoning.md                     # type: Session Reasoning
        system.md                        # type: Session Context
        tools.md                          # type: Session Tools
        events.md                         # type: Session Events
        assets/
          <managed attachment or chunk>
```

- `provider` 只能是已配置且受支持的 provider，例如 `codex` 或 `workbuddy`。
- `session-id` 是稳定主键，也是唯一的会话目录名；标题为空时使用 `untitled`。标题变化只更新 provider 级 `index.md`、概念文档 frontmatter 与 `log.md`，不得改名目录。
- `<provider>/index.md` 是 provider 级检索索引，记录该 provider 下每个已发布 session 的稳定 ID 与当前标题；它是从发布状态派生的目录清单，不是事实来源。
- `<provider>/<session-id>/index.md` 只列出当前 bundle 的概念文档和 `assets/`，不含 frontmatter；它不重复 `session.md` 的会话内容或标题。
- `log.md` 记录该 bundle 成功的创建、内容更新、元数据更新、source reset、附件、废弃和迁移事件，不含 frontmatter。
- 文件截断、替换或 file identity 变化不会创建新目录；发布器在原目录原子重建当前 bundle，生成新的 `document_version_id`，并记录 `Source Reset`。

### 2.1 Session bundle `index.md` 的 formatter 与正文

`<provider>/<session-id>/index.md` 是 OKF 保留目录清单，不是概念文档：必须是 UTF-8、LF 换行、无 BOM、无 YAML frontmatter，且不能使用 `type`、`sources` 或 AGENT 管理标记。它只能链接当前 bundle 内文件与附件，必须使用标准 Markdown 链接，按下列骨架输出：

```markdown
# Session Bundle

## Documents

- [会话](session.md)
- [推理](reasoning.md)
- [运行上下文](system.md)
- [工具](tools.md)
- [事件](events.md)

## Assets

- [<asset-name>](assets/<asset-name>) — `sha256:<hex>`
```

空 `Assets` 区块可省略；其他列出的文件不存在时必须阻止发布，而不是留下死链接。

标题不属于 session bundle `index.md`，因此仅标题变化不得重写该文件。概念文档集合或已发布附件集合不变时，发布器也不得为了普通内容更新重写它。

### 2.2 Provider `index.md` 的 formatter 与正文

`<provider>/index.md` 是 OKF 保留目录清单，不是概念文档：必须是 UTF-8、LF 换行、无 BOM、无 YAML frontmatter，且不能使用 `type`、`sources` 或 AGENT 管理标记。它只记录当前已发布 session 的标题到稳定 ID 的映射，并使用到各 session 主文档的标准相对 Markdown 链接；不得列出未发布、删除或其他 provider 的 session。

```markdown
# <provider> Sessions

## Sessions

- [<session-title>](<session-id>/session.md) — `<session-id>`
```

每个当前已发布 session 恰有一项。条目按 `session-id` 的字节序升序排列，标题相同仍以 `session-id` 区分；标题变化只替换该条目的显示文本，不改变链接目标或排序规则。没有已发布 session 时保留标题和 `## Sessions`，但不输出列表项。

### 2.3 `log.md` formatter

`log.md` 是 OKF 保留的目录更新日志，必须无 frontmatter、按日期倒序排列，并使用以下结构化散文格式：

```markdown
# Directory Update Log

## 2026-08-10

- **Update** — at: 2026-08-10T12:00:00Z; by: web-knowledge-pipeline/1.0; document_version_id: `docv:...`; changed: [session.md](session.md), [tools.md](tools.md); reason: appended source records.
```

事件类型固定为 `Creation`、`Update`、`Metadata Update`、`Source Reset`、`Attachment`、`Deprecation` 和 `Migration`。无变化或失败不写入本日志；失败由 Run Journal 记录。

## 3. Bundle 的原子性与必备文件

`session.md`、`reasoning.md`、`system.md`、`tools.md`、`events.md`、session bundle `index.md` 和 `log.md` 共同构成当前来源 bundle。`<provider>/index.md` 是与该 bundle 关联的派生检索索引。发布器必须在同一逻辑发布事务中更新所有发生变化的 bundle 文件及 provider 索引；只有 session bundle 与 provider 索引均处于同一已发布状态后，才能写入 `PublicationCompleted`。概念文档集合和附件集合未变化时，session bundle `index.md` 是有效的未修改输入，不得被无故重写。

除 `index.md` 与 `log.md` 外，每个 Markdown 文件都是 OKF 概念文档：开头具有可解析 YAML frontmatter 和非空 `type`。所有文件共享 session 来源身份、provider 和 session ID；每份文件独立声明自身的 `document_version_id` 与 `content_hash`，附属文件还声明自身的 `type`、记录范围和 `sources`。`sources` 必须指向 `session.md` 或 `source_file_ref`，且每项均包含 `resource`。

`resource` 与 `source_file_ref` 使用稳定的 `evidence://<provider>/<session-id>` 形式，是 Evidence Store 引用，绝不是本机绝对路径。具体来源版本由 `document_version_id` 标识；原始工作目录只以 `cwd_display` 保存。

### 3.1 概念文档的通用 formatter

`session.md`、`reasoning.md`、`system.md`、`tools.md`、`events.md` 及所有受管分片 Markdown 都必须是 UTF-8、LF 换行的 OKF 概念文档：第一行和 frontmatter 结束行均为独占的 `---`，frontmatter 前不得有 BOM、空行或其他文本，且 `type` 非空。`generated.by` 使用 `<producer>/<version>`，`generated.at` 和其他时间字段使用带时区 ISO-8601；`status` 只能为 `draft`、`stable` 或 `deprecated`。

所有概念文档共享来源身份字段；每份文档独立写入自身的 `document_version_id` 与 `content_hash`。附属文件的 `id` 在尾部加自身角色，`type` 取各文件规定的类型。尖括号均为 producer 值，不能写入最终文件：

```yaml
---
id: "source:session:<provider>:<session-id>:<document-role>"
type: <document-type>
kind: agent-session-<document-role>
title: "<session-title> — <document-label>"
description: "<单句描述>"
resource: "evidence://<provider>/<session-id>"
source_file_ref: "evidence://<provider>/<session-id>"
provider: "<provider>"
session_id: "<session-id>"
document_version_id: "docv:<session-document-id>:<content-hash-prefix>"
content_hash: "sha256:<hex>"
captured_at: "<ISO-8601>"
line_range: [<first-line>, <last-line>]
status: stable
generated:
  by: web-knowledge-pipeline/1.0
  at: "<ISO-8601>"
sources:
  - id: session-jsonl
    resource: "evidence://<provider>/<session-id>"
    title: "<provider> session JSONL"
    document_version_id: "<document-version-id>"
managed_by: web-knowledge-pipeline
---
```

`sources[].resource` 是每份会话概念文档必需的 OKF 溯源字段；`source_file_ref` 仅为同一事实的 producer 扩展，不能替代它。内部跳转使用标准 Markdown 相对链接和 Obsidian block fragment；不能以 wiki link 作为唯一表示。

`session.md` 的 `document_version_id` 是当前会话源快照的 canonical version；`reasoning.md`、`system.md`、`tools.md`、`events.md` 和受管分片拥有各自的 `document_version_id`，但其 `sources[].document_version_id` 指向本次发布的 `session.md` canonical version。

## 4. session.md：消息主文档

`session.md` 是主会话笔记，frontmatter 至少包含：

- `id`、`type: Agent Session`、`kind: agent-session`、`provider`、`session_id`、`title` 与 `description`；
- `resource`、`source_file_ref`、`cwd_display`、`bundle_files`、`started_at`、`captured_at`、`line_range`、`content_hash` 与 `status`；
- `session_kind`，以及仅对子智能体 session 必填的 `parent_session`；
- `ingestion`（schema 与 reasoning/system context/raw tool output 是否纳入）；
- 合规的 `generated`，至少有 `by` 和 `at`；
- 至少一项含 `id` 与 `resource` 的 `sources`，以及 `managed_by: web-knowledge-pipeline`。

### 4.1 `session.md` 正文 formatter

`session.md` 在通用 frontmatter 后必须按以下骨架输出。`# 完整会话` 内的 turn 与消息锚点是 evidence block，必须按 JSONL 原始行序递增；用户或助手缺席时只输出实际存在的消息节。概览、阅读卡片和概念清单是受管区块，完整消息正文不是摘要、不得省略或改写。

`session.md` 将 §3.1 模板中的 `id`、`type`、`kind`、`title`、`description` 与 `document-role` 固定为主会话值：`id` 以 `:session` 结尾、`type: Agent Session`、`kind: agent-session`、`title: "<session-title>"`、`description` 为会话的单句描述。它必须在 `line_range` 后、`status` 前以如下顺序增加主文档字段：

```yaml
cwd_display: "<workspace-relative-or-redacted-path>"
bundle_files: [session.md, reasoning.md, system.md, tools.md, events.md]
started_at: "<ISO-8601-or-null>"
session_kind: "root|subagent|unknown"
# 仅 session_kind: subagent 时存在：
parent_session:
  provider: "<parent-provider>"
  session_id: "<parent-session-id>"
  relation_id: "rel:<parent-provider>:<parent-session-id>:<provider>:<session-id>"
  raw_evidence_ref: "ev:<provider>:<session-id>:<line-number>:<record-hash>"
ingestion:
  schema: "<provider-schema>"
  reasoning_included: true
  system_context_included: true
  raw_tool_output_included: true
```

`session_kind` 是受管枚举：具有已验证父子关系的 child 为 `subagent`；已验证不属于子智能体的 session 为 `root`；来源无法可靠判断时为 `unknown`。`session_kind: subagent` 必须同时具有完整的 `parent_session` 对象；`root` 与 `unknown` 不得写入空对象。`parent_session` 是导航关系的结构化投影，不替代 `system.md` 中完整保留的 `session_meta` evidence；其 `relation_id` 固定为 `rel:<parent-provider>:<parent-session-id>:<provider>:<session-id>`，不得包含标题、昵称或角色等可变展示值。

```markdown
# 会话概览
## 阅读卡片
- 真实 Turn、用户消息、助手消息、工具调用和推理记录的确定性计数
- [推理](reasoning.md) · [运行上下文](system.md) · [工具](tools.md) · [事件](events.md)

<!-- AGENT:BEGIN session-summary -->
<基于会话记录的简短概览。>[^session-jsonl]
<!-- AGENT:END session-summary -->

# 子智能体会话
<!-- AGENT:BEGIN subagent-sessions -->
- [<child-title>](../<child-session-id>/session.md) — `<child-session-id>`；昵称：`<agent-nickname>`；角色：`<agent-role>`
<!-- AGENT:END subagent-sessions -->

# 完整会话

会话开端上下文：
- [会话元数据](system.md#^context-<session-metadata-stable-id>)
- [系统提示](system.md#^context-<base-instructions-stable-id>)
- [父会话](../<parent-session-id>/session.md)

## Turn <turn-key> ^turn-<stable-id>

### 用户 ^msg-<stable-id>
<完整原始用户消息，以 Markdown 原样渲染>

<details><summary>来源与原始记录</summary>
<原始 JSONL 行与镜像 evidence refs>
</details>

关联记录：
- [本轮推理](reasoning.md#^reasoning-<stable-id>)
- [工具调用与结果](tools.md#^tool-<call-id>)
- [本轮运行上下文](system.md#^context-<stable-id>)

### 助手 ^msg-<stable-id>
<完整原始助手消息，以 Markdown 原样渲染>

<details><summary>来源与原始记录</summary>
<原始 JSONL 行与镜像 evidence refs>
</details>

# 提取出的概念
<!-- AGENT:BEGIN extracted-concepts -->
- [<Concept>](</02 Concepts/<type>/<concept>.md>)
<!-- AGENT:END extracted-concepts -->

# 人工笔记
<用户维护的内容>

[^session-jsonl]: <provider> session JSONL
```

`# 完整会话` 开头必须先链接本 session 的 `session_metadata` block；存在 `base_instructions` block 时必须紧随其后链接系统提示。会话中没有对应记录时，发布器省略该链接而不是制造空 evidence block。标准 Markdown 相对链接是规范链接形式；Obsidian wiki link 不能作为唯一表示。

阅读卡片只能从已归并记录的计数、名称、状态和首个真实用户消息生成，不能调用模型或引入来源中不存在的结论。`developer`/`system` 角色消息，以及以 `<environment_context>`、`<recommended_plugins>`、`<app-context>`、`<skills_instructions>`、`<permissions instructions>`、`<collaboration_mode>`、`<apps_instructions>`、`<plugins_instructions>` 或 `<model_switch>` 开头的伪 user 消息是运行时注入上下文，不得作为 `### 用户` 写入主线；主线在其位置可显示到 `system.md` 的折叠提示。完整 user/assistant 正文不得放进代码围栏；来源、行号和镜像 evidence refs 必须放在默认折叠的“来源与原始记录”区。

同一 Turn 内、两个真实 user/assistant 消息之间没有真实消息穿插的连续工具调用必须聚合为一条“工具活动”摘要，显示类别、调用数、完成/未完成状态与到 `tools.md` 记录的链接。缺少 provider `turn_id` 的工具调用附着到前一个真实消息 Turn；会话开头、尚无真实消息时的连续调用只形成一个 `## 会话准备` 区块，不能为每个调用制造 `Turn record-*`。工具结果不得写入 `session.md`。

`# 子智能体会话` 只属于 parent session，位于 `# 会话概览` 与 `# 完整会话` 之间。它是唯一的受管区块：仅列出已发布、可消费且与当前 session 有已验证直接父子关系的 child bundle；按 child `session_id` 的字节序升序，每个 child 恰有一项。显示名依次取 child 当前标题、`agent_nickname`、`untitled`；昵称或角色缺失时省略对应片段。没有合格 child 时，发布器必须删除整个标题和受管区块。条目只使用到同 provider sibling bundle 的相对标准 Markdown 链接，不能复制 child 正文。

`- [父会话]` 仅在当前 `session_kind: subagent` 且 parent bundle 已发布、可消费时出现；否则省略该行，不得留下死链接。一个 subagent 可以同时成为其他 subagent 的 parent，但每个 session 只列出直接 child，不能递归展开任务树。

## 5. 附属文档与原始内容

每条已归并记录都以稳定 evidence block 写入以下唯一归属位置，并保留原始 JSONL 行引用：

| 文件             | 必须物化的记录                                                        | 最低内容要求                                                                                   |
| ---------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `reasoning.md` | reasoning                                                             | 按 turn 分节、原始`rawContent`、时间、来源角色与 block ID                                    |
| `system.md`    | session metadata、system/base instructions、turn context、world state | 完整结构、来源角色、关联 turn 与 block ID                                                      |
| `tools.md`     | tool call 与 tool result                                              | 工具名称、状态、原始参数字符串、可解析 JSON、结果、call ID、时间、provider 扩展字段与 block ID |
| `events.md`    | lifecycle、多智能体通信、压缩、文件快照和未知记录                     | 原始结构、序号、时间、关联键、record kind 与 block ID                                          |

`file-history-snapshot` 只保存元数据，不读取备份文件正文。`providerData`、`rawResponse`、`mcpMeta` 和未知字段保留为结构化 opaque JSON，保留其原始行引用。

### 5.1 附属文档正文 formatter

每个附属文档使用 §3.1 的通用 frontmatter，并在其后使用下列固定一级标题和记录格式。固定一级标题后先输出返回 `session.md` 的链接和无标题概览，再按 Turn 或类别分组；稳定 evidence block 位于三级标题行末。`原始 JSONL 行` 必须链接到 `source_file_ref` 的可寻址行/记录引用。完整参数、完整 JSON、完整结果和其他原始结构默认放在 `<details>` 中；字段值为结构化数据时，details 内使用 `~~~json` 围栏并保留原始值。

```markdown
# 推理

> 返回主会话：[session.md](session.md)

## 概览
<确定性记录数与 Turn 范围>

## Turn <turn-key>

### 推理记录 ^reasoning-<stable-id>

- 时间：<ISO-8601-or-null>
- 来源角色：reasoning
- 原始 JSONL 行：<raw-evidence-ref>

<原始 rawContent>
```

```markdown
# 运行上下文

> 返回主会话：[session.md](session.md)

## 概览
<会话级、注入和 Turn 级记录的确定性计数>

## 会话级上下文

### <context-kind> ^context-<stable-id>

- 关联 Turn：<turn-key-or-null>
- 时间：<ISO-8601-or-null>
- 原始 JSONL 行：<raw-evidence-ref>

<details><summary>完整原始上下文</summary>

~~~json
<完整 session metadata、base instructions、turn context 或 world state>
~~~
</details>
```

```markdown
# 工具

> 返回主会话：[session.md](session.md)

## 概览
<确定性的调用、配对和未完成计数>

## Turn <turn-key>

### <tool-name> ^tool-<call-id>

- Call ID：`<call-id>`
- 状态：<completed|incomplete|unknown>
- 时间：<ISO-8601-or-null>
- 原始 JSONL 行：<raw-evidence-ref>

### 请求
~~~json
<原始参数或可解析 JSON>
~~~

### 结果
<完整工具结果，或到 assets/分片的标准 Markdown 链接>
```

```markdown
# 事件

## <record-kind> ^event-<stable-id>

- 序号：<sequence>
- 关联键：<turn-key-or-call-id-or-null>
- 时间：<ISO-8601-or-null>
- 原始 JSONL 行：<raw-evidence-ref>

~~~json
<完整 lifecycle、多智能体、压缩、快照或未知记录>
~~~
```

`reasoning.md`、`system.md`、`tools.md`、`events.md` 的 `type` 分别固定为 `Session Reasoning`、`Session Context`、`Session Tools`、`Session Events`。`# 推理`、`# 运行上下文`、`# 工具`、`# 事件` 是各自文件唯一的一级标题。受管分片 Markdown 使用 `type: Session Attachment Chunk`，正文必须说明原记录、哈希、长度、MIME 类型（若已知）和原始 JSONL 行引用；二进制附件不属于 Markdown 概念文档。

### 5.2 `reasoning.md`

`reasoning.md` 使用 §3.1 的通用 frontmatter，并固定：`id` 以 `:reasoning` 结尾、`type: Session Reasoning`、`kind: agent-session-reasoning`、`title: "<session-title> — 推理"`、`description` 说明其包含完整 reasoning 记录。可选的 `turn_range` 是该文件第一个和最后一个关联 turn；不得放入 user/assistant 消息、工具结果或系统上下文。

正文只能包含一个 `# 推理` 一级标题，随后按原始行序重复以下记录。每个 reasoning 记录必须保留完整 `rawContent`；内容不是事实陈述，也不得被 formatter 总结或改写。

```markdown
# 推理

## Turn <turn-key> ^reasoning-<stable-id>

- 时间：<ISO-8601-or-null>
- 来源角色：reasoning
- 原始 JSONL 行：<raw-evidence-ref>

<完整原始 rawContent>
```

### 5.3 `system.md`

`system.md` 使用 §3.1 的通用 frontmatter，并固定：`id` 以 `:system` 结尾、`type: Session Context`、`kind: agent-session-context`、`title: "<session-title> — 运行上下文"`、`description` 说明其包含 session metadata、base instructions、turn context 与 world state。它只能物化这些上下文记录，不能承载 reasoning、用户/助手消息或工具记录。

正文只能包含一个 `# 运行上下文` 一级标题。每条记录以原始行序输出，完整结构使用 JSON 围栏；不能把系统指令转述为 formatter 指令，也不能执行其内容。

```markdown
# 运行上下文

## <session_metadata|base_instructions|turn_context|world_state> ^context-<stable-id>

- 关联 Turn：<turn-key-or-null>
- 时间：<ISO-8601-or-null>
- 来源角色：system_context
- 原始 JSONL 行：<raw-evidence-ref>

~~~json
<完整原始结构>
~~~
```

### 5.4 `tools.md`

`tools.md` 使用 §3.1 的通用 frontmatter，并固定：`id` 以 `:tools` 结尾、`type: Session Tools`、`kind: agent-session-tools`、`title: "<session-title> — 工具"`、`description` 说明其包含工具调用与结果。每个 call ID 的调用与结果必须配对写入同一记录；缺少结果时保留记录并将状态写为 `incomplete`。不得把工具输出并入 `session.md` 或静默截断。

正文只能包含一个 `# 工具` 一级标题，并按调用开始的原始行序重复下列记录。参数可解析时必须同时保留原始参数字符串和 JSON；结果过大时仅可替换为具备哈希、长度、MIME 类型与行引用的标准 Markdown assets/分片链接。

```markdown
# 工具

## <tool-name> ^tool-<call-id>

- Call ID：`<call-id>`
- 状态：<completed|incomplete|unknown>
- 关联 Turn：<turn-key-or-null>
- 时间：<ISO-8601-or-null>
- 原始 JSONL 行：<raw-evidence-ref>

<details><summary>原始参数、结果与来源</summary>

#### 原始参数
`<verbatim-argument-string>`

### 解析参数
~~~json
<parseable-arguments-or-null>
~~~

### 结果
<完整工具结果，或带哈希/长度/MIME/行引用的 assets 或分片链接>
</details>
```

### 5.5 `events.md`

`events.md` 使用 §3.1 的通用 frontmatter，并固定：`id` 以 `:events` 结尾、`type: Session Events`、`kind: agent-session-events`、`title: "<session-title> — 事件"`、`description` 说明其包含 lifecycle、多智能体通信、压缩、文件快照与未知记录。`file-history-snapshot` 只写元数据；不得读取或嵌入快照所指向的备份文件正文。

正文只能包含一个 `# 事件` 一级标题，按原始 sequence 递增重复下列记录。未知字段必须留在完整 JSON 中，不能因 formatter 不认识其 schema 而删除。

```markdown
# 事件

> 返回主会话：[session.md](session.md)

## 时间线
| 序号 | 类型 | 关联键 | 时间 |
| ---: | --- | --- | --- |

## 完整记录

### <record-kind> ^event-<stable-id>

- 序号：<sequence>
- 关联键：<turn-key-or-call-id-or-null>
- 时间：<ISO-8601-or-null>
- 原始 JSONL 行：<raw-evidence-ref>

<details><summary>完整原始事件</summary>

~~~json
<完整原始 lifecycle、多智能体、压缩、快照或未知记录>
~~~
</details>
```

### 5.6 受管分片 Markdown

无法安全内嵌、但仍是文本的超大工具输出或 opaque JSON 必须写入当前 bundle 的受管分片 Markdown。它使用 §3.1 的通用 formatter，并固定：`id` 以 `:chunk:<stable-id>` 结尾、`type: Session Attachment Chunk`、`kind: agent-session-attachment-chunk`、`title` 说明原记录和分片序号、`description` 说明内容类别。正文只能包含 `# 附件分片` 一个一级标题，随后输出哈希、字节长度、MIME 类型（若已知）、原始 JSONL 行引用及完整内容。二进制数据写入 `assets/`，不是 Markdown 文件。

```markdown
# 附件分片

- 原记录：<record-key>
- SHA-256：`sha256:<hex>`
- 字节长度：<integer>
- MIME 类型：<mime-or-null>
- 原始 JSONL 行：<raw-evidence-ref>

## 内容 ^chunk-<stable-id>

<完整分片文本>
```

不能安全内嵌为 Markdown 的二进制内容、UTF-8 序列化后超过 32 KiB 的工具结果、运行上下文或事件 opaque JSON，写入当前 bundle 的 `assets/` 或受管分片 Markdown。文本分片必须在 UTF-8 代码点边界拆分，按分片序号拼接后完全还原原文。原位置必须保留链接、SHA-256、总字节长度、MIME 类型（若已知）和原始 JSONL 行引用；不得静默截断或按内容类型省略记录。任何受管分片 Markdown 也必须有 YAML frontmatter 和非空 `type`。

### 5.7 Codex rollout 原始字段到正文的映射

本节为 `codex` provider 的规范性映射。它把 [Codex rollout JSONL schema](../../../rollout_jsonl_schema.md) 中的 legacy 原始行，经 producer 归并后，绑定到本节已定义的 Markdown 正文位置；不改变 §3.1 的 frontmatter、§4 的 `session.md` formatter 或 §5.1--§5.6 的记录 formatter。表中的 `payload` 均指行级 `{ timestamp, type, payload }` 的 `payload`，`完整 JSON` 表示保留该字段及未知同级字段的原始结构，而不是重新序列化出的字段白名单。

| 原始行条件与字段路径 | 归并后的记录 | 目标 Markdown 正文位置 | 写入规则 |
| --- | --- | --- | --- |
| 所有行：`timestamp`、原始行序号 | 每条 evidence block 的时间和来源 | 对应记录中的 `时间`、`原始 JSONL 行` | `timestamp` 写为 `时间`；原始行序号与行内容哈希组成 `raw-evidence-ref`。同一归并记录可列出多个原始行引用，顺序必须与 JSONL 一致。 |
| `session_meta`：`payload.session_id`，缺失时 `payload.id` | session 身份 | `session.md` frontmatter 的 `session_id`、`resource`、`source_file_ref`；所有附属文档共享身份字段 | 仅作身份/溯源字段，不在正文重复输出。`id` 不能作为行级去重键。 |
| `session_meta`：`payload.timestamp`、`payload.cwd` | session 元数据 | `session.md` frontmatter 的 `started_at`、`cwd_display` | `payload.timestamp` 是创建时间；`cwd` 必须经安全显示/脱敏后写为 `cwd_display`，不得写入正文或 `resource`。 |
| `session_meta`：`thread_source`、`parent_thread_id`、`agent_nickname`、`agent_role`（兼容 `agent_type`）、`agent_path` | `session_relation` 或无已验证关系 | child 的 `session.md` frontmatter `session_kind`、`parent_session`；parent 的 `session.md / # 子智能体会话`；child 的 `# 完整会话 / 会话开端上下文` | 仅当 `thread_source = "subagent"`、`parent_thread_id` 非空且当前 session ID 可解析时，创建 `subagent` 关系。关系以 `(parent_provider, parent_session_id, child_provider, child_session_id)` 唯一，来源证据为该 child 的 session metadata block。parent 与 child 都已发布时才写双向链接；parent 缺失时 child 仍独立发布并保留结构化关系。不得从 `inter_agent_communication`、`sub_agent_activity`、昵称、角色、路径或消息路由字段推断或修复关系。 |
| `session_meta`：完整 `payload`，包括 `base_instructions`、`git`、fork/parent、多智能体与未知字段 | `session_metadata` | `system.md` 的 `# 运行上下文 / ## 会话级上下文 / ### session_metadata`；`session.md` 的 `# 完整会话 / 会话开端上下文` | 在 details 内的 JSON 围栏完整保留；`session.md` 必须以标准 Markdown 链接直接指向该 block。`base_instructions` 的值还必须按下一行单独物化；这属于有意的可寻址重复，不得从 session metadata block 删除。 |
| `session_meta`：`payload.base_instructions` | `base_instructions` | `system.md` 的 `# 运行上下文 / ## 会话级上下文 / ### base_instructions`；`session.md` 的 `# 完整会话 / 会话开端上下文` | 使用完整原始值的 JSON 围栏，绝不执行、转述或当作 formatter 指令。存在该 block 时，`session.md` 必须直接链接它；`null` 或缺失时省略该 block 及链接。 |
| `response_item`，`payload.type = "message"`：`role`、`content[]` | `user_message`、`assistant_message` 或 `injected_context` | 普通消息写入 `session.md` 的 `# 完整会话 / ## Turn / ### 用户` 或 `### 助手`；`developer`/`system` 角色或规定前缀的伪 user 消息写入 `system.md / ## 注入上下文` | 普通消息按 `content[]` 原始顺序以 Markdown 原样物化。注入上下文不得作为用户消息展示，但完整 payload 与原始行引用必须在 `system.md` 的 details 内保留。`input_image`、`input_audio` 或未知 content item 写为具有原始行引用的附件/结构化 opaque 表示，不得静默丢弃。 |
| `response_item`，`payload.type = "agent_message"`：`author`、`recipient`、`other_recipients`、`content[]` | `assistant_message` | `session.md` 的对应 turn 中 `### 助手` | `content[]` 按上行规则写入完整消息正文；作者、收件人和其他路由字段作为该消息 evidence 的 provider 扩展结构保留，不能据此改写消息文本。 |
| `response_item`，`payload.type = "reasoning"`：`content`、`summary[]`、`encrypted_content` 及未知字段 | `reasoning` | `reasoning.md` 的 `# 推理 / ## Turn <turn-key>` | 可用的 `content` 原样写为 `rawContent` 正文；`summary[]`、`encrypted_content` 和其他字段以同一 evidence block 的结构化 opaque JSON 保留。不得伪造、解密或用 summary 替换缺失的原始内容。 |
| `response_item`，`payload.type` 为 `function_call`、`custom_tool_call`、`local_shell_call`、`tool_search_call`、`web_search_call` 或 `image_generation_call` | `tool_call` | `tools.md` 的 `# 工具 / ## Turn / ### <tool-name>` 和 details 内的原始参数、解析参数、结果 | `name`（或等价的 `action`、`execution`）确定 tool name；`call_id` 为配对键，缺失时使用稳定 record key；原始 `arguments`、`input`、`action` 或 `execution` 必须逐字保留，能解析时才在 details 内另写 JSON。`result` 等同一行返回值写入结果；`status` 与所有 provider 扩展字段保留。 |
| `response_item`，`payload.type` 为 `function_call_output`、`custom_tool_call_output` 或 `tool_search_output` | `tool_result` | 与相同 `call_id` 的 `tools.md / ## <tool-name> / ### 结果` | 将 `output` 或 `tools[]` 完整写入已有调用记录；没有匹配调用时仍创建状态为 `unknown` 的工具记录。超大或二进制结果按 §5.6 转交 assets/分片。 |
| `response_item`，`payload.type` 为 `compaction` 或 `context_compaction` | `compaction` | `events.md` 的 `# 事件 / ## compaction` 或 `## context_compaction` | 完整 `payload` 写入 JSON 围栏；不从其 `encrypted_content` 生成或覆盖消息、推理或上下文 block。 |
| `event_msg`，`payload.type` 为 `user_message` 或 `agent_message` | `user_message` 或 `assistant_message` | `session.md` 的 `# 完整会话 / ## Turn / ### 用户` 或 `### 助手` | 与 `response_item` 消息按 turn ID、角色、规范化文本和相邻 sequence 去重，正文只物化一次；两个表示的原始行引用都必须保留在该 evidence block。 |
| `event_msg`，`payload.type` 为 `agent_reasoning` 或 `agent_reasoning_raw_content` | `reasoning` | `reasoning.md` 的对应 `## Turn <turn-key>` | 与等价 `response_item.reasoning` 合并并保留全部来源行；可用原始内容写入 `rawContent`，其余字段保留为同一 block 的 opaque JSON。 |
| `event_msg`，`payload.type` 为 `token_count`、`thread_goal_updated`、`thread_rolled_back`、`turn_aborted`、`task_started`、`task_complete`、`thread_settings_applied`、`entered_review_mode`、`exited_review_mode`、`patch_apply_end`、`context_compacted`、`mcp_tool_call_end`、`web_search_end`、`image_generation_end`、`sub_agent_activity` 或持久化的 `item_completed` | `lifecycle` 或 provider 扩展事件 | `events.md` 的 `# 事件 / ## <payload.type>` | 完整 `payload` 写入 JSON 围栏；`turn_id` 优先、`call_id` 次之写入 `关联键`。工具完成事件可以补全同一 `call_id` 的工具状态/结果，但事件本身仍保留独立 evidence block。 |
| `turn_context`：完整 `payload` 与 `payload.turn_id` | `turn_context` | `system.md` 的 `# 运行上下文 / ## turn_context` | 完整 JSON 写入；`turn_id` 写入 `关联 Turn`。其中 `cwd` 不得替代 `session.md` 的已脱敏 `cwd_display`。 |
| `world_state`：完整 `payload` | `world_state` | `system.md` 的 `# 运行上下文 / ## world_state` | 完整 JSON 写入，包括自由结构的 `state` 与未来未知字段。 |
| `compacted`：完整 `payload`，包括 `replacement_history[]` | `compacted` | `events.md` 的 `# 事件 / ## compacted` | 完整 JSON 写入一个事件 block。`replacement_history[]` 只维护上下文连续性；其中已由独立原始行物化的消息不得再次创建消息 evidence block。 |
| `inter_agent_communication`：`author`、`recipient`、`other_recipients`、`content`、`encrypted_content`、`trigger_turn` | 有可用 `content` 时为 `assistant_message`；否则为 `lifecycle` | 有内容时写入 `session.md / ### 助手`；否则写入 `events.md / ## inter_agent_communication` | 文本消息保留 author/recipient 路由字段与原始行引用；`encrypted_content` 和无法作为会话正文呈现的字段仍以 opaque JSON 保留，不得解密。 |
| `inter_agent_communication_metadata`：完整 `payload` | `lifecycle` | `events.md` 的 `# 事件 / ## inter_agent_communication_metadata` | 完整 JSON 写入。 |
| 任何未识别的行级 `type`、未识别的 `payload.type`，或上述记录中的未知字段 | `unknown` 或所属记录的 provider 扩展 | `events.md / ## <record-kind>`，或所属 `system.md`、`reasoning.md`、`tools.md` evidence block | 未识别记录完整写入 `events.md`；已识别记录的未知同级/嵌套字段与该记录同处保留。不得因 formatter 不认识 schema 而删除、截断或重新归类为消息。 |

所有 `Turn <turn-key>` 由 `payload.internal_chat_message_metadata_passthrough.turn_id` 或等价事件 `turn_id` 关联；缺失时 producer 必须使用稳定 record key，不能以时间戳或可复用的 provider `id` 猜测。工具记录以调用开始的原始行序排列，调用与结果按 `call_id` 配对；缺少结果的调用状态为 `incomplete`。`session.md` 中的关联链接只指向实际已物化的 reasoning、工具或上下文 block。

child 首次发布、标题或关系展示字段变化、关系移除、child 废弃或恢复可消费状态时，发布器必须重新计算受影响 parent 的子智能体会话区块。child bundle 与所有受影响 parent `session.md`、`log.md` 必须在同一逻辑发布事务中更新；若任一步失败，不能推进 cursor 或留下单侧导航链接。parent 先发布时允许没有该区块，child 后续发布时再补写；跨 provider 父子关系不在本规范支持范围内。

## 6. 追加、替换与重发

新增完整 JSONL 行只能追加新记录或更新受影响尾部 turn；既有记录的原始行序、文件名、锚点和 evidence ID 不得重排。每次实质内容变化都为受影响 Markdown 生成新的 `document_version_id`，并在 `log.md` 记录变更。`publication-manifest.json` 管理附属文件路径和当前版本。

适配器发现文件截断、替换或 identity 改变时，必须在同一稳定 session 目录重建完整当前 bundle，生成新的 `document_version_id`，并写入 `Source Reset` 日志。旧版本正文由 Evidence Store 保留；Vault 不复制历史目录，也不为历史版本创建新路径。

标题变化只更新 provider `index.md` 中对应条目的显示标题、概念文档 frontmatter 和 `log.md`，不得改变 session 目录名、链接目标或 session bundle `index.md`。session 创建、标题变化、弃用或迁移导致 provider 索引条目变化时，发布器必须从当前 publication manifest 重建该 provider 索引；发布失败时不得更新当前 Markdown、任一 `index.md`、`log.md` 或 cursor。

所有会话内容，包括 reasoning、系统上下文、完整工具输出、world state 和 provider 扩展字段，默认按主设计稿的保留策略原样物化、发布并作为有来源角色的模型输入。若部署策略禁止某项内容发布，必须在来源注册表中显式声明；发布器记录策略判定和替代 evidence 引用，而不能隐式删除。

## 7. 验证要求

会话 bundle 测试必须验证：

- 每个 session 目录同时存在无 frontmatter 的 `index.md`、无 frontmatter 的 `log.md`、五个必备 Markdown 文件和需要时的附件或分片；
- 每个存在已发布 session 的 provider 目录都有无 frontmatter 的 `index.md`；它对每个当前 session 恰有一个到 `<session-id>/session.md` 的链接，并将该 session 的当前标题映射到稳定 `session-id`；
- 除 `index.md` 与 `log.md` 外，所有 Markdown 均有 frontmatter 与非空 `type`，每个 `sources` 条目均有 `resource`；
- `session.md` 完整保留 user/assistant 原始消息，并在 `# 完整会话` 开头直接链接 `system.md` 的 session metadata；有 `base_instructions` 时也直接链接系统提示，且可跳转到相应 turn、推理、工具与上下文；
- `session.md` 的真实消息正文以 Markdown 原样渲染，运行时注入上下文不作为用户消息展示；五份概念文档均有确定性概览、返回主会话链接（`session.md` 除外）和默认折叠的原始证据；
- session bundle `index.md`、provider `index.md` 与 `log.md` 均无 frontmatter；session bundle `index.md` 的链接只指向当前 bundle 文件或附件，provider `index.md` 的链接只指向当前 provider 的 session 主文档；
- 每个概念文档首行为 `---`、含非空 `type` 和带 `resource` 的 `sources`，`session.md`、`reasoning.md`、`system.md`、`tools.md`、`events.md` 和每个受管分片均符合各自的固定一级标题、frontmatter 与记录 formatter；
- Codex legacy rollout fixture 中每个已知行级 `type` 与 `response_item`/`event_msg` 的 `payload.type` 均按 §5.7 写入唯一正文位置；重复消息保留全部原始行引用，未知字段和未知类型不丢失；
- 新增行只追加或更新受影响尾部 turn，不改变历史锚点；
- 截断或替换保持 session 目录稳定、生成新的文档版本并记录 `Source Reset`；
- 标题变化不改变路径、session bundle `index.md` 或 provider 索引的链接目标，只更新 provider 索引中的显示标题；
- 仅标题变化且概念文档集合、附件集合不变时，session bundle `index.md` 保持字节不变；
- 日志按日期倒序，成功发布包含 actor、时间、事件类型、document version、变更文件和原因；
- 超过 32 KiB 的工具结果、运行上下文或事件 opaque JSON，以及二进制记录，以带哈希、总字节长度、MIME 和引用的附件/分片表示；分片拼接可完整还原原文且不丢失来源链。
