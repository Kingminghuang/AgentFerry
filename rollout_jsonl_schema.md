# Codex rollout JSONL Schema

> 本文只描述本机 ~/.codex/sessions 实际使用的 legacy history mode。

## 0. History mode 结论

扫描当前 ~/.codex/sessions：

| 项目 | 数量 |
| --- | ---: |
| rollout 文件 | 323 |
| 显式 history_mode: "legacy" | 223 |
| 缺少 history_mode、按源码默认值解释为 legacy | 100 |

ThreadHistoryMode 的默认值是 legacy，见
[protocol.rs#L693](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L693)。
因此本文以下内容均按 legacy 文件格式描述。

对本机实际 rollout 文件而言：

- 每行没有 ordinal 字段。
- session_meta.history_mode 要么是 "legacy"，要么缺失而按默认值解释为 legacy。
- 用户/助手消息主要以 response_item 或 legacy event_msg 形式持久化。
- 工具调用和工具结果以 response_item 形式持久化。

源码版本：406dc9239。

## 1. 行级 Envelope

rollout 是 append-only JSON Lines 文件，每行是一个独立 JSON 对象。正常由 Codex 创建的文件首行是 session_meta。

源码中的 RolloutLine 见
[protocol.rs#L3388](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3388)：

    {
      "timestamp": "2026-07-30T02:41:41.139Z",
      "type": "response_item",
      "payload": {
        "type": "message",
        "role": "assistant",
        "content": [
          { "type": "output_text", "text": "..." }
        ]
      }
    }

legacy rollout 的有效行结构：

    type LegacyRolloutLine = {
      timestamp: string; // UTC RFC3339
      type:
        | "session_meta"
        | "response_item"
        | "event_msg"
        | "inter_agent_communication"
        | "inter_agent_communication_metadata"
        | "compacted"
        | "turn_context"
        | "world_state";
      payload: object;
    };

外层 RolloutItem 使用 type + payload 的 adjacent tagging，定义见
[protocol.rs#L3193](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3193)。

## 2. 外层记录类型

| type | payload | 用途 |
| --- | --- | --- |
| session_meta | SessionMetaLine | 会话元信息，通常是首行 |
| response_item | ResponseItem | 消息、推理、工具调用、工具结果 |
| event_msg | EventMsg | turn 生命周期和 legacy 历史事件 |
| turn_context | TurnContextItem | 当前轮次的运行配置快照 |
| world_state | WorldStateItem | 工作区和运行环境状态 |
| compacted | CompactedItem | 上下文压缩记录 |
| inter_agent_communication | InterAgentCommunication | 多智能体消息 |
| inter_agent_communication_metadata | { trigger_turn } | 多智能体调度元数据 |

## 3. session_meta

定义见
[protocol.rs#L3060](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3060)。
SessionMetaLine 会把 SessionMeta 展平，并在同一 payload 下附加可选的 git。

    {
      "type": "session_meta",
      "payload": {
        "session_id": "019...",
        "id": "019...",
        "timestamp": "2026-07-30T02:41:36.109Z",
        "cwd": "/Users/huangqingming/Workspace/AgentFerry",
        "originator": "Codex Desktop",
        "cli_version": "0.146.0-alpha.3.1",
        "source": "vscode",
        "thread_source": "user",
        "model_provider": "openai",
        "base_instructions": { "text": "..." },
        "selected_capability_roots": [],
        "history_mode": "legacy",
        "git": {
          "commit_hash": "...",
          "branch": "main",
          "repository_url": "..."
        }
      }
    }

主要字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| session_id | string | session ID，通常是 UUIDv7 |
| id | string | thread ID，通常与 session_id 相同 |
| forked_from_id | string? | fork 来源线程 |
| parent_thread_id | string? | 父线程，常用于子智能体 |
| timestamp | string | 会话创建时间，不等同于行级时间 |
| cwd | string | 会话工作目录 |
| originator | string | 启动来源，例如 Codex Desktop |
| cli_version | string | Codex CLI 版本 |
| source | string/object | cli、vscode、exec、mcp 等 |
| thread_source | string? | 例如 user、subagent |
| agent_nickname | string? | 子智能体昵称 |
| agent_role | string? | 子智能体角色；输入时兼容旧别名 agent_type |
| agent_path | string? | 子智能体路径 |
| model_provider | string/null | 模型提供商 |
| base_instructions | object/null | 通常为 { text: string } |
| dynamic_tools | array? | 动态工具规格 |
| selected_capability_roots | array | capability roots |
| memory_mode | string? | memory 配置 |
| history_mode | "legacy" | 本机所有 rollout 的有效值 |
| multi_agent_version | string? | 多智能体版本 |
| context_window | object? | 通常为 { window_id: string } |
| git | object? | commit、branch 和 repository URL |

旧文件如果缺少 session_id，反序列化时会使用 id 回填，见
[protocol.rs#L3164](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3164)。

## 4. response_item

ResponseItem 是第二层判别联合，定义见
[models.rs#L809](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/models.rs#L809)：

    #[serde(tag = "type", rename_all = "snake_case")]
    pub enum ResponseItem { ... }

因此 payload.type 与字段处于同一层。legacy rollout 中可持久化的类型：

| payload.type | 主要字段 |
| --- | --- |
| message | id?、role、content[]、phase? |
| agent_message | id?、author、recipient、content[] |
| reasoning | id?、summary[]、content?、encrypted_content |
| local_shell_call | id?、call_id?、status、action |
| function_call | id?、name、namespace?、arguments、call_id |
| function_call_output | id?、call_id、output |
| custom_tool_call | id?、status?、call_id、name、input |
| custom_tool_call_output | id?、call_id、name?、output |
| tool_search_call | id?、call_id?、status?、execution、arguments |
| tool_search_output | id?、call_id?、status、execution、tools[] |
| web_search_call | id?、status?、action? |
| image_generation_call | id?、status、revised_prompt?、result |
| compaction | id?、encrypted_content |
| context_compaction | id?、encrypted_content? |

message.content 是第三层联合，定义见
[models.rs#L713](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/models.rs#L713)：

    input_text  -> { type, text }
    input_image -> { type, image_url, detail? }
    input_audio -> { type, audio_url }
    output_text -> { type, text }

function_call.arguments 是 JSON 编码的字符串，需要二次解析。工具调用和工具结果通过 call_id 配对。跨 turn 关联通常使用：

    "internal_chat_message_metadata_passthrough": {
      "turn_id": "019..."
    }

additional_tools、compaction_trigger 和未知类型 other 可以被协议解析，但当前持久化策略不会将它们写入 rollout，见
[policy.rs#L37](https://github.com/openai/codex/tree/main/codex-rs/rollout/src/policy.rs#L37)。

## 5. event_msg

EventMsg 定义见
[protocol.rs#L1275](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L1275)，同样采用 payload.type 判别。

legacy 模式下始终持久化：

    token_count
    thread_goal_updated
    thread_rolled_back
    turn_aborted
    task_started
    task_complete
    thread_settings_applied

legacy 模式下持久化的消息/结果事件：

    user_message
    agent_message
    agent_reasoning
    agent_reasoning_raw_content
    entered_review_mode
    exited_review_mode
    patch_apply_end
    context_compacted
    mcp_tool_call_end
    web_search_end
    image_generation_end
    sub_agent_activity

item_completed 在 legacy 模式下只保留 Plan 和 Extension(Sleep) 两类 item。其他实时增量或交互事件，例如命令输出 delta、审批请求、输入请求、MCP 启动进度和消息 delta，不是稳定历史内容，通常不会持久化。筛选规则见
[policy.rs#L85](https://github.com/openai/codex/tree/main/codex-rs/rollout/src/policy.rs#L85)。

典型事件：

    {
      "type": "event_msg",
      "payload": {
        "type": "task_complete",
        "turn_id": "019...",
        "last_agent_message": "...",
        "started_at": 1720000000,
        "completed_at": 1720000012,
        "duration_ms": 12000,
        "time_to_first_token_ms": 800
      }
    }

源码变体名是 TurnStarted / TurnComplete，线上名称是 task_started / task_complete，同时兼容读取 turn_started / turn_complete。

## 6. turn_context

定义见
[protocol.rs#L3267](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3267)。它记录某一轮实际生效的运行环境：

    turn_id?
    cwd
    workspace_roots?
    current_date?
    timezone?
    approval_policy
    approvals_reviewer?
    sandbox_policy
    permission_profile?
    network?
    file_system_sandbox_policy?
    model
    comp_hash?
    personality?
    collaboration_mode?
    multi_agent_version?
    multi_agent_mode?
    realtime_active?
    effort?
    summary

其中 sandbox_policy、permission_profile 和 collaboration_mode 还各自拥有协议定义；导出时应保留完整 JSON。

## 7. world_state

定义见
[protocol.rs#L3210](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3210)：

    {
      "type": "world_state",
      "payload": {
        "full": true,
        "state": {
          "agents_md": [],
          "skills": [],
          "permissions": {},
          "environments": []
        }
      }
    }

full 表示是否为完整状态基线；state 是自由 JSON，字段集合随运行环境变化。

## 8. compacted

定义见
[protocol.rs#L3228](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3228)：

    {
      "type": "compacted",
      "payload": {
        "message": "...",
        "replacement_history": [
          { "type": "message", "role": "user", "content": [] }
        ],
        "window_number": 2,
        "first_window_id": "019...",
        "previous_window_id": "019...",
        "window_id": "019..."
      }
    }

replacement_history 内嵌 ResponseItem[]，因此该记录可能包含多层嵌套的判别联合。

## 9. 多智能体记录

inter_agent_communication 的 payload：

    {
      "id": "...",
      "author": "...",
      "recipient": "...",
      "other_recipients": [],
      "content": "...",
      "encrypted_content": "...",
      "trigger_turn": true
    }

inter_agent_communication_metadata 的 payload 是：

    { "trigger_turn": true }

## 10. 解析建议

    raw JSONL
      -> 按外层 type 分派
      -> response_item / event_msg 按 payload.type 分派
      -> 用 turn_id 关联 turn
      -> 用 call_id 关联工具调用和工具结果
      -> 生成 session.json 或 HTML

实现时应注意：

1. rollout 是事件日志，不是已经归并好的 session.json.turns。
2. function_call.arguments 是 JSON 字符串，需要二次解析。
3. legacy 模式下 response_item 和 event_msg 可能同时表达消息，需要根据 turn_id、call_id 和事件类型归并或去重。
4. 可选字段可能缺失，也可能出现 null，不要假设所有可选字段都一定省略。
5. 保留未知字段，避免 Codex 新增事件类型后无法读取旧文件。

## 11. 参考源码

| 内容 | 源码 |
| --- | --- |
| history mode 默认值 | [protocol.rs#L693](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L693) |
| SessionMeta / SessionMetaLine | [protocol.rs#L3060](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3060) |
| RolloutItem | [protocol.rs#L3193](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3193) |
| WorldStateItem / CompactedItem | [protocol.rs#L3210](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3210) |
| TurnContextItem | [protocol.rs#L3267](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3267) |
| RolloutLine | [protocol.rs#L3388](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L3388) |
| ResponseItem / ContentItem | [models.rs#L809](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/models.rs#L809) / [models.rs#L713](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/models.rs#L713) |
| EventMsg | [protocol.rs#L1275](https://github.com/openai/codex/tree/main/codex-rs/protocol/src/protocol.rs#L1275) |
| legacy 持久化筛选策略 | [policy.rs#L85](https://github.com/openai/codex/tree/main/codex-rs/rollout/src/policy.rs#L85) |
| JSONL 写入器 | [recorder.rs#L1893](https://github.com/openai/codex/tree/main/codex-rs/rollout/src/recorder.rs#L1893) |
