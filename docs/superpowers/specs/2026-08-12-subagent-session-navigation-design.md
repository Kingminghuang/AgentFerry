# 子智能体会话导航设计

**状态：** 已确认的设计
**日期：** 2026-08-12
**所属设计：** [本地会话 Vault 目录与 Bundle 规范](session-vault-layout.md)
**范围：** 将 Codex rollout 的父/子智能体关系投影为可查询元数据，并在父会话中维护到已发布子会话的稳定导航链接

## 1. 目标与边界

每个子智能体仍发布为独立、完整的 session bundle。其父会话 `session.md` 必须能列出并跳转到全部已发布的直接子会话；子会话也必须能跳回已发布父会话。

本设计只增加从已归档 session metadata 派生的关系视图，不改变原始 JSONL 的保留规则、不会复制子会话正文，也不会根据消息文本或 `inter_agent_communication` 猜测父子关系。跨 provider 关系、全局任务图谱和多层关系的汇总视图不在本期范围内。

## 2. 关系来源与标准化投影

仅当 Codex `session_meta` 同时满足下列条件时，producer 才生成一条 `subagent` 关系：

- `thread_source` 严格等于 `subagent`；
- `parent_thread_id` 是非空字符串；
- 当前 `session_id`（缺失时回退 `id`）可解析为稳定 child session ID。

关系的权威来源是 child session 的 `session_meta`。`inter_agent_communication`、`sub_agent_activity`、`agent_path`、昵称、角色或消息路由字段都不能独立创建或修复关系；它们仅可提供同一 child 会话内的原始证据或展示信息。

`ConversationNormalized` 在现有会话身份之外增加可选的 `session_relation`：

```json
{
  "kind": "subagent",
  "parent_provider": "codex",
  "parent_session_id": "<session_meta.parent_thread_id>",
  "child_provider": "codex",
  "child_session_id": "<normalized session_id>",
  "agent_nickname": "<session_meta.agent_nickname or null>",
  "agent_role": "<session_meta.agent_role or agent_type or null>",
  "agent_path": "<session_meta.agent_path or null>",
  "raw_evidence_ref": "<session_meta evidence ID>"
}
```

同一 `(parent_provider, parent_session_id, child_provider, child_session_id)` 最多有一条关系。该关系 ID 固定为 `rel:<parent-provider>:<parent-session-id>:<child-provider>:<child-session-id>`，不包含可变标题、昵称或角色。后续 `session_meta` 的展示字段变化更新该关系的当前投影，但不改变关系 ID。

不满足条件或字段无法解析时，producer 必须保留完整的 `session_metadata` evidence block 与未知字段，但省略 `session_relation`；不得产生不可靠的链接。

## 3. Vault 表示

### 3.1 Child session

有 `session_relation` 的 child `session.md` 在其受管 frontmatter 中增加：

```yaml
session_kind: subagent
parent_session:
  provider: codex
  session_id: "<parent-session-id>"
  relation_id: "rel:codex:<parent-session-id>:codex:<child-session-id>"
  raw_evidence_ref: "ev:..."
```

无此关系的 session 写 `session_kind: root`；无法判断但不应假定为根会话时写 `session_kind: unknown`，且不写 `parent_session`。

child `session.md` 的 `# 完整会话` 开端上下文在已有元数据链接之后，且仅在父 bundle 已发布时，加入：

```markdown
- [父会话](../<parent-session-id>/session.md)
```

链接必须使用相对标准 Markdown；父 bundle 尚未发布、已经废弃或不属于同一 provider 时省略该链接，不能留下死链接。

### 3.2 Parent session

每个具有至少一个已发布直接 child 的 parent `session.md`，在 `# 会话概览` 后、`# 完整会话` 前增加唯一受管区块：

```markdown
# 子智能体会话
<!-- AGENT:BEGIN subagent-sessions -->
- [<child-title>](../<child-session-id>/session.md) — `<child-session-id>`；昵称：`<agent-nickname>`；角色：`<agent-role>`
<!-- AGENT:END subagent-sessions -->
```

`child-title` 优先使用 child session 的当前标题；标题为空时依次回退昵称和 `untitled`。昵称或角色为 null 时省略其片段。条目按 child `session_id` 的字节序升序排列，且每个 child 仅出现一次。parent 没有已发布 child 时，删除整个标题和受管区块，避免留下空章节。

该清单是派生导航，不是事实来源：每一项同时以 relation ID 和 child session 的 canonical `document_version_id` 作为渲染输入。原始关系字段仍只在 child 的 `system.md` session metadata evidence 中完整保存。

## 4. 发布与一致性

关系解析与 child bundle 发布属于同一 producer 流程。渲染器维护按 `parent_provider + parent_session_id` 查询 child relation 的发布状态。

- child 首次成功发布时，若 parent bundle 已发布，必须在同一逻辑发布事务中更新 parent `session.md`、parent `log.md` 和 child bundle。
- parent 先发布时允许没有子会话区块；任何匹配 child 之后首次发布时补写 parent 清单。
- child 标题、昵称、角色、关系字段、状态或 canonical document version 变化时，必须重渲染受影响 parent 清单；如果清单字节不变，则不得虚假更新 parent。
- child 废弃、关系不再成立或 child bundle 不再可消费时，必须在同一事务中从 parent 清单移除该项，并移除 child 的父会话正文链接。
- parent 缺失、未发布或无法解析时，child 仍可作为独立 bundle 发布；关系作为 metadata 保留，导航链接延迟到 parent 发布后建立。
- 一个 child 可以是另一个 child 的 parent。每个 session 只列出直接 child；递归任务树不在单个 `session.md` 中展开。

父/child 同 provider 是本设计的发布前提。若将来允许跨 provider，必须新增 provider 路径解析与跨 provider 原子性设计，不能把 `parent_thread_id` 直接当作同 provider 路径。

## 5. 错误处理与保留

解析不到 parent、缺少 `thread_source`、`thread_source` 不是 `subagent`、或 `parent_thread_id` 为空，均视为“无已验证关系”，不阻止 child session 的正常归档。重复 `session_meta` 通过既有归并规则处理；若其父 ID 相互冲突，producer 必须将会话标记为关系冲突、保留所有原始 evidence，并禁止为该 child 发布父/子导航链接，直到来源恢复一致。

不得解密 `encrypted_content`，不得把 `sub_agent_activity` 的内容折叠成关系状态，也不得以 `inter_agent_communication` 的 author/recipient 替代 `parent_thread_id`。这些记录仍按既有 `events.md` 映射原样物化。

## 6. 验证

producer 与 layout 的 fixture/golden-file 测试至少覆盖：

- 一个 parent 与多个 child 的清单、相对链接和按 child session ID 排序；
- child 先发布、parent 先发布，以及 parent 缺失后迟到发布；
- child 标题、昵称或角色变化只更新受影响父会话的受管区块；
- `thread_source` 不是 `subagent`、缺少 `parent_thread_id`、缺少 session ID 与冲突 session metadata 均不生成链接；
- child 废弃或关系移除后，parent 清单和 child 回链同步移除；
- 嵌套 subagent 仅生成逐层直接链接；
- `inter_agent_communication` 与 `sub_agent_activity` 不会生成额外关系；
- 关系与 bundle 更新在同一逻辑发布事务中完成，失败时不推进 cursor、不留下单侧导航链接；
- 未知字段、原始 evidence 引用和人工维护区块在增量更新后保持不变。

## 7. 需修改的既有规范

- `session-to-okf-producer.md`：扩展统一记录/标准化工件，新增上述关系投影、冲突规则、发布依赖和 fixture 要求。
- `session-vault-layout.md`：定义 child frontmatter 与回链、parent 受管清单的固定位置/格式，以及跨 bundle 的渲染与原子发布约束；将现有的 `session_meta`、`sub_agent_activity` 和多智能体通信映射与此关系投影明确区分。
- `web-to-obsidian-knowledge-pipeline-design.md`：仅补充一条架构层不变量，即关系图由已发布 child session metadata 投影，父清单是衍生导航而非事实来源。
