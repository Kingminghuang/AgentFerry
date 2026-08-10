# 本地会话到 OKF Producer 规范

**状态：** 已确认的设计  
**日期：** 2026-08-07  
**所属设计：** [网页与本地会话到 Obsidian 知识管道](web-to-obsidian-knowledge-pipeline-design.md)  
**范围：** Codex rollout 与 WorkBuddy conversation JSONL 如何增量读取、归并、证据化并生产会话 OKF 来源 bundle

## 1. 定位与规范层级

本文是本地会话来源的 producer 契约，规定从获授权的追加式 JSONL 到 `ConversationNormalized` 的过程、状态和不变量。生产的最终 Vault 表示由[本地会话 Vault 目录与 Bundle 规范](session-vault-layout.md)定义；该 layout 规范是本文的唯一 OKF 落盘输出契约。

本文不定义提炼器、解析器、检索器或 UI 如何消费会话 OKF，也不将会话内容解释为外部事实。通用事件信封、Evidence Store、发布事务、OKF v0.2 合规边界和共享安全/保留策略由主设计稿定义；冲突时以主设计稿为准。

## 2. 输入、输出与游标状态

会话 producer 只在来源注册表授权的本地根目录读取 append-only JSONL。来源必须显式声明 `source_id`、provider、`root_path`、`mode: tail` 与 `include_reasoning`、`include_system_context`、`include_raw_tool_output`、`publish_mode` 策略。路径是部署配置，不能写死在协议或代码中。

每个文件维护独立游标：file identity、字节偏移、最后完整行哈希和已处理行序号。只读取游标之后完整的 JSON 行；尾部无法解析行留待下一轮，绝不当作记录或跳过。不得按时间戳排序，因为 WorkBuddy 时间可能相同或回退。file identity 只用于内部检测文件替换，不进入公开记录身份或 Vault 路径。

文件截断、替换或 identity 变化时，producer 必须从新文件起点重新生产当前 session bundle，并产生新的 `document_version_id`；旧版本由 Evidence Store 保留，Vault 不创建新的历史目录。

## 3. 统一记录模型与身份

每一条被接收的原始 JSONL 行投影为以下统一模型；未知字段必须以 structured opaque JSON 保留，并保留原始行引用：

```json
{
  "provider": "codex | workbuddy",
  "session_id": "稳定会话 ID",
  "record_key": "provider:session_id:line_number:record_hash",
  "record_hash": "sha256:<hex>",
  "sequence": 42,
  "occurred_at": "ISO-8601 或 null",
  "kind": "user_message | assistant_message | reasoning | system_context | tool_call | tool_result | lifecycle | file_snapshot | session_metadata | unknown",
  "turn_key": "可空的 turn 或父消息 ID",
  "call_id": "可空的工具调用关联键",
  "status": "completed | incomplete | unknown",
  "content": "原始文本或结构化投影",
  "raw_evidence_ref": "原始 JSONL 行引用"
}
```

`record_key`、`sequence` 和 evidence ID 均以读取顺序与规范化记录内容为基础，不能依赖可复用的 provider `id` 或不单调时间。`record_hash` 是规范化记录的 SHA-256 值；每条归并后的记录必须有稳定 evidence ID：`ev:<provider>:<session-id>:<line-number>:<record-hash>`。相同 session、行号和记录 hash 再次出现时复用相同 evidence ID，这是纯内容/行号寻址的明确取舍。

## 4. Provider 映射与归并

### 4.1 Codex rollout

- `session_meta` 产生 `session_metadata`，优先使用 `payload.session_id`，缺失时使用 `payload.id`。
- `response_item` 中 `message`、`agent_message` 产生消息；`function_call`、`custom_tool_call`、`local_shell_call` 产生 `tool_call`；对应 output 产生 `tool_result`。
- `event_msg` 的用户/agent 消息与 `response_item` 的重复表示，按 turn ID、call ID、角色、规范化文本和相邻 sequence 去重；去重不能删除任一原始行引用。
- `base_instructions`、`turn_context`、`world_state` 产生 `system_context`；`compacted` 与 `replacement_history` 只维护连续性，已出现的消息不能再次成为独立证据。
- `inter_agent_communication` 产生带 author/recipient 的 `assistant_message` 或 `lifecycle`。

### 4.2 WorkBuddy conversation

- 文件名 conversation ID 与记录 `sessionId` 共同构造稳定 session ID；行级主键不能使用 `id`。
- `message` 依 role 产生 `user_message` 或 `assistant_message`；`function_call` 与 `function_call_result` 通过 `callId` 配对；缺少结果的调用以 `incomplete` 保留。
- `reasoning.rawContent` 产生 `reasoning`；`file-history-snapshot` 仅产生快照元数据，不能读取备份文件内容。
- `ai-title` 只更新展示标题及 provider 级 session 索引中的对应映射；`providerData`、`rawResponse`、`mcpMeta` 和未知字段以 opaque JSON 生产。

归并器按原始行序重建会话、turn 与调用配对。不得为便于显示而重排记录；不能配对的记录仍以原始 sequence、状态和来源引用保留。

## 5. 标准化工件与证据仓库

`ConversationNormalized` 是当前读取范围的不可变标准化来源工件，至少包含 provider、session ID、已处理行范围、展示标题、工作目录的安全显示值、按原始顺序归并的记录、内容哈希与 evidence blocks。其 `document_id` 是稳定会话工件 ID；`document_version_id` 绑定本次归并内容哈希，并作为 `session.md` 的 canonical document version。

完整原始 JSONL、结构化归并结果与过大内容由 Evidence Store 按版本保存。原始工作目录不得作为资源 URI 或输出机器绝对路径；layout 只可使用 `cwd_display`。二进制、不能安全内嵌的内容或超过块上限的工具输出必须带原始行引用、SHA-256、长度和 MIME 类型（若已知）转交 layout 层以写为 assets 或受管分片，不能截断或按类型省略。

## 6. 从标准化工件到会话 OKF

producer 仅在当前读取范围的全部必备记录通过结构校验后请求 Vault 物化。它向 layout 层提供会话身份、完整 user/assistant 消息、reasoning、system context、工具调用/结果、其他事件、记录范围、来源引用、锚点、内容哈希、`document_version_id` 和保留策略判定。

layout 层必须将当前读取范围物化为稳定 session 目录 bundle：一个 session-local `index.md`、`log.md`、主 `session.md`、`reasoning.md`、`system.md`、`tools.md`、`events.md` 以及需要时的 `assets/` 或受管分片；并维护 `<provider>/index.md`，将每个已发布 session 的稳定 ID 映射到当前标题。所有发生变化的 session bundle 文件和 provider 索引必须在同一逻辑发布事务中完成；只有两者一致后才能确认发布。除保留文件 `index.md` 与 `log.md` 外的 Markdown 必须为 OKF 概念文档，且每个 `sources` 条目都有 `resource`。`resource` 与 `source_file_ref` 采用稳定的 `evidence://<provider>/<session-id>`，不是本机路径。

追加的完整行只能添加新记录或更新受影响尾部 turn，不得改变既有记录顺序、文件名、锚点或既有 evidence ID。受影响的 Markdown 生成新的 `document_version_id`；发布器同时写入 `Update` 日志。

## 7. 更新、失败与可重放性

- 相同 `event_id` 与相同 `record_key` 必须幂等；重新扫描已处理范围不得重复证据。
- 游标仅在完整行被持久化并生成相应工件后前进；发布失败时从最后成功阶段重试。
- 追加行导致内容哈希变化时，创建受影响 Markdown 的新 `document_version_id`；没有新增完整行或其他实质变更时不发布、不写入 source-local `log.md`。
- 文件截断、替换或 identity 变化时在原 session 目录重建当前 bundle，产生新的 `document_version_id` 并写入 `Source Reset` 日志；不创建新的历史目录。
- 成功发布必须在同一逻辑事务中替换所有发生变化的当前 Markdown、session-local `index.md`、`log.md` 以及 provider `index.md`；概念文档和附件集合未变化时不得重写 session-local `index.md`。任一步失败都不得推进 cursor 或留下与已发布 session 不一致的 provider 索引。
- JSON 解析失败尾行、暂时不可读文件和短暂 I/O 错误保留游标并有上限重试；不兼容 schema 记录为 `unknown`，而不是静默丢弃。
- 本规范的默认保留策略是完整保留 reasoning、system context、原始工具输出与 provider 扩展字段。部署若禁止任一类别，必须在来源策略中显式声明，并在标准化工件中记录判定和替代 evidence 引用。

## 8. Producer 验证夹具

会话 producer 的 fixture 与 golden-file 测试必须覆盖：游标与不完整尾行、同时间戳和重复 ID、Codex 重复消息去重、工具调用配对与不完整调用、WorkBuddy 标题更新、provider 索引的 ID/标题/主文档映射、仅标题变化时 session-local `index.md` 字节不变、未知 opaque 字段、纯内容/行号 evidence ID、追加不重排、截断/替换重建同一 session 目录并产生 `Source Reset` 日志、超大/二进制内容的引用，以及从 `ConversationNormalized` 到[会话 Vault layout](session-vault-layout.md)所需字段的完整传递。
