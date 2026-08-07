# 本地会话 Vault 目录与 Bundle 规范

**状态：** 已确认的设计  
**日期：** 2026-08-07  
**所属设计：** [网页与本地会话到 Obsidian 知识管道](2026-08-03-web-to-obsidian-knowledge-pipeline-design.md)  
**范围：** Codex rollout 与 WorkBuddy conversation JSONL 的会话来源 bundle 在 `01 Sources/Sessions/` 中的物化

## 1. 定位与规范层级

本文是会话来源的最终 Vault 物化规范。它定义如何将已验证的 `ConversationNormalized` 写为目录、generation 隔离、bundle 文件、锚点、原始内容和增量发布；不定义 JSONL 的读取、provider schema 映射、记录归并或知识提炼算法。上游输入、游标、provider 映射和 evidence block 的生产规则由[本地会话到 OKF Producer 规范](2026-08-07-session-to-okf-producer.md)定义。

主设计稿中的 Vault 根目录配置、OKF v0.2 合规边界、标识符与 slug 验证、受管区块保护、发布事务、安全与保留策略均直接适用。由会话 producer 产出的 `ConversationNormalized` 是本文唯一的上游输入。

## 2. 目录与 generation 隔离

每个 session generation 是一个独立的、原子发布的来源 bundle：

~~~text
01 Sources/
  Sessions/
    <provider>/
      <YYYY>/
        <session-id>_<session-title>/
          index.md                         # 会话目录清单；无 frontmatter
          generations/
            <generation>/
              index.md                     # generation bundle 清单；无 frontmatter
              session.md                   # type: Agent Session
              reasoning.md                 # type: Session Reasoning
              system.md                    # type: Session Context
              tools.md                     # type: Session Tools
              events.md                    # type: Session Events
              assets/
                <managed attachment or chunk>
~~~

- `provider` 只能是已配置且受支持的 provider，例如 `codex` 或 `workbuddy`。
- `YYYY` 取会话首次观察到的时间；`session-id` 是稳定主键；`session-title` 是仅供可读性的 slug。首次发布后，上层会话目录不得因标题变化自动改名；标题为空时使用 `untitled`。
- `<generation>` 使用适配器的 generation 标识，并以可排序的规范形式写入，例如 `generation-000003`。它是路径的一部分，不能只出现在 frontmatter、manifest 或 evidence ID 中。
- 上层 `index.md` 只列出各 generation 的链接和当前 generation 指针。generation 内的 `index.md` 只列出该 bundle 的 `session.md`、附属文档及 `assets/`，均不含 frontmatter。
- 任何文件截断、替换或 file identity 变化都会创建新的 generation 目录。旧 generation 的目录及其证据不可覆盖、移动或混入新 generation。

## 3. Bundle 的原子性与必备文件

`session.md`、`reasoning.md`、`system.md`、`tools.md`、`events.md` 和 generation `index.md` 共同构成一个来源工件，发布器必须在同一发布事务中更新它们。只有整组文件原子替换成功后，才能写入 `PublicationCompleted`。

除两个 `index.md` 外，每个 Markdown 文件都是 OKF 概念文档：开头具有可解析 YAML frontmatter 和非空 `type`。所有文件共享 session 来源身份、provider、session ID、generation、文档版本与内容哈希；每份附属文件还声明自身的 `type`、记录范围和 `sources`。`sources` 必须指向 `session.md` 或 `source_file_ref`，且每项均包含 `resource`。

`source_file_ref` 使用 `evidence://<provider>/<session-id>/generation-<n>` 形式，是 Evidence Store 引用，绝不是本机绝对路径。原始工作目录只以 `cwd_display` 保存。

## 4. session.md：消息主文档

`session.md` 是主会话笔记，frontmatter 至少包含：

- `id`、`type: Agent Session`、`kind: agent-session`、`provider`、`session_id`、`session_generation`、`title` 与 `description`；
- `resource`、`source_file_ref`、`cwd_display`、`bundle_files`、`started_at`、`captured_at`、`line_range`、`content_hash` 与 `status`；
- `ingestion`（schema 与 reasoning/system context/raw tool output 是否纳入）；
- 合规的 `generated`，至少有 `by` 和 `at`；
- 至少一项含 `id` 与 `resource` 的 `sources`，以及 `managed_by: web-knowledge-pipeline`。

正文必须依次包含 `# 会话概览`、`# 完整会话`、`# 提取出的概念` 与 `# 人工笔记`。概览和概念列表是受管区块，不能取代完整消息。完整会话按 JSONL 原始行序保存所有 `user_message` 与 `assistant_message`，每轮使用稳定锚点，并链接同轮的附属记录：

~~~markdown
## Turn <turn-key> ^turn-<stable-id>

### 用户
<完整用户消息正文> ^msg-<stable-id>

### 助手
<完整 assistant 消息正文> ^msg-<stable-id>

关联记录：
- [本轮推理](./reasoning.md#^reasoning-<stable-id>)
- [工具调用与结果](./tools.md#^tool-<call-id>)
- [本轮运行上下文](./system.md#^context-<stable-id>)
~~~

会话中没有对应记录时，发布器省略该链接而不是制造空 evidence block。标准 Markdown 相对链接是规范链接形式；Obsidian wiki link 不能作为唯一表示。

## 5. 附属文档与原始内容

每条已归并记录都以稳定 evidence block 写入以下唯一归属位置，并保留原始 JSONL 行引用：

| 文件 | 必须物化的记录 | 最低内容要求 |
| --- | --- | --- |
| `reasoning.md` | reasoning | 按 turn 分节、原始 `rawContent`、时间、来源角色与 block ID |
| `system.md` | session metadata、system/base instructions、turn context、world state | 完整结构、来源角色、关联 turn 与 block ID |
| `tools.md` | tool call 与 tool result | 工具名称、状态、原始参数字符串、可解析 JSON、结果、call ID、时间、provider 扩展字段与 block ID |
| `events.md` | lifecycle、多智能体通信、压缩、文件快照和未知记录 | 原始结构、序号、时间、关联键、record kind 与 block ID |

`file-history-snapshot` 只保存元数据，不读取备份文件正文。`providerData`、`rawResponse`、`mcpMeta` 和未知字段保留为结构化 opaque JSON，保留其原始行引用。

不能安全内嵌为 Markdown 的二进制内容、超过单块上限的工具输出或过大的 opaque JSON，写入同 generation 的 `assets/` 或受管分片 Markdown。原位置必须保留链接、SHA-256、长度、MIME 类型（若已知）和原始 JSONL 行引用；不得静默截断或按内容类型省略记录。任何受管分片 Markdown 也必须有 YAML frontmatter 和非空 `type`。

## 6. 追加、替换与重发

同一 generation 内，新增完整 JSONL 行只能追加新记录或更新受影响尾部 turn；既有记录的原始行序、文件名、锚点和 evidence ID 不得重排。`publication-manifest.json` 管理附属文件路径和 generation 内的链接目标。

适配器发现文件截断、替换或 identity 改变时，必须保留旧 generation 原样并在新的 generation 路径发布完整新 bundle。新 generation 不得修改旧 generation 的 `session.md`、附属文件或证据链接。会话目录上层的 `index.md` 可更新当前 generation 指针，但历史 generation 链接必须保留。

所有会话内容，包括 reasoning、系统上下文、完整工具输出、world state 和 provider 扩展字段，默认按主设计稿的保留策略原样物化、发布并作为有来源角色的模型输入。若部署策略禁止某项内容发布，必须在来源注册表中显式声明；发布器记录策略判定和替代 evidence 引用，而不能隐式删除。

## 7. 验证要求

会话 bundle 测试必须验证：

- 每个 generation 同时存在 generation `index.md`、五个必备 Markdown 文件和需要时的附件或分片；
- 所有非保留 Markdown 均有 frontmatter 与非空 `type`，全部 `sources` 条目均有 `resource`；
- `session.md` 完整保留 user/assistant 原始消息，并可跳转到相应 turn、推理、工具与上下文；
- 新增行只追加或更新受影响尾部 turn，不改变历史锚点；
- 截断或替换创建新目录且旧 generation 不变；
- 超大或二进制记录以带哈希和引用的附件/分片表示，不丢失来源链。
