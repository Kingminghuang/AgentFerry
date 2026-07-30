# WorkBuddy conversation JSONL Schema

> 本文描述 `~/.workbuddy/projects/<workspace名>/<conversationId>.jsonl` 的实测格式。
> 结论来自本机当前样本，而不是 WorkBuddy 的公开协议定义；实现读取器时应保留未知字段和未知 `type`。

截至 2026-07-30，扫描 `~/.workbuddy/projects`：

| 项目 | 数量 |
| --- | ---: |
| 项目目录 | 55 |
| conversation JSONL 文件 | 153 |
| JSONL 行 | 10,453 |
| JSON 解析错误 | 0 |

当前文件名就是 conversation ID，例如：

```text
~/.workbuddy/projects/Users-huangqingming-Workspace-AgentFerry/
  3a46c68b-69f4-48b9-823d-7ac7466237c0.jsonl
```

对所有样本而言：

- 文件中所有带 `sessionId` 的记录都使用文件名中的 conversation ID。
- 同一文件内 `cwd` 保持不变。
- 文件是 append-only JSON Lines；每行是一个独立 JSON 对象。
- 没有发现统一的 schema/version 字段，也没有 ordinal/行号字段。
- `timestamp` 是 Unix epoch 毫秒，不是 ISO 8601 字符串。
- 追加顺序才是记录顺序；时间戳可以相同，且少量相邻行存在时间戳回退。
- `id` 不是行级唯一键：同一个模型响应产生的 `message` 和一个或多个 `function_call` 可能共享同一个 `id`。
- `callId` 是工具调用与工具结果的主要关联键；被中断的调用可能没有对应的结果行。

## 1. 行级 Envelope

WorkBuddy 没有像 Codex rollout 那样的统一 `{ timestamp, type, payload }` 外壳。每一种记录直接把业务字段放在顶层：

```json
{
  "id": "...",
  "timestamp": 1785136560687,
  "type": "message",
  "role": "user",
  "content": [],
  "providerData": { "agent": "cli" },
  "sessionId": "...",
  "cwd": "/Users/huangqingming/Workspace/AgentFerry"
}
```

所有样本都包含：

```ts
type CommonRecord = {
  timestamp: number; // Unix epoch milliseconds
  type: string;       // discriminant
  cwd: string;
  id?: string;
  sessionId?: string;
  parentId?: string;
  providerData?: Record<string, unknown>;
};
```

字段的实测覆盖率：

| 字段 | 行数 | 说明 |
| --- | ---: | --- |
| `timestamp` | 10,453 | 所有记录都有 |
| `type` | 10,453 | 所有记录都有 |
| `cwd` | 10,453 | 所有记录都有 |
| `id` | 10,375 | `ai-title` 记录没有 |
| `sessionId` | 9,401 | `file-history-snapshot` 记录没有 |
| `parentId` | 9,141 | 主要用于 assistant、reasoning、工具调用和工具结果 |
| `providerData` | 9,323 | 消息、推理、工具调用和工具结果记录使用 |

## 2. 顶层记录类型

当前样本出现的顶层 `type`：

| `type` | 数量 | 作用 |
| --- | ---: | --- |
| `function_call` | 2,928 | 工具调用请求 |
| `function_call_result` | 2,924 | 工具调用结果 |
| `message` | 1,855 | 用户消息或 assistant 最终消息 |
| `reasoning` | 1,616 | assistant 推理过程/摘要 |
| `file-history-snapshot` | 1,052 | 文件历史快照 |
| `ai-title` | 78 | 会话标题 |

未知类型应按可扩展记录处理，而不是直接丢弃。

## 3. `message`

用户消息和 assistant 消息共用同一个结构，通过 `role` 区分：

```json
{
  "id": "...",
  "parentId": "...",
  "timestamp": 1785136560687,
  "type": "message",
  "role": "user",
  "content": [
    { "type": "input_text", "text": "..." }
  ],
  "providerData": { "agent": "cli" },
  "sessionId": "...",
  "cwd": "..."
}
```

实测 `role` 只有 `user` 和 `assistant`。`content` 是内容块数组：

| `content[].type` | 数量 | 字段 |
| --- | ---: | --- |
| `input_text` | 286 | `type`、`text` |
| `output_text` | 1,498 | `type`、`text`，通常还带 `providerData.annotations` |

assistant 消息常见字段：

```ts
type MessageRecord = CommonRecord & {
  type: "message";
  role: "user" | "assistant";
  content: TextContent[];
  status?: "completed" | "incomplete";
  message?: { usage: SnakeCaseUsage };
  logicalParentId?: string;
};

type TextContent = {
  type: "input_text" | "output_text";
  text: string;
  providerData?: { annotations: unknown[] };
};
```

`content[].text` 是不透明文本，可能包含系统上下文、工具返回的结构化 JSON、Markdown 或 XML 片段，不应按普通用户输入格式假设。

### 3.1 消息级 usage

部分 assistant 消息有重复保存的 usage：

```json
{
  "message": {
    "usage": {
      "input_tokens": 51957,
      "output_tokens": 952,
      "total_tokens": 52909,
      "cache_read_input_tokens": 44688
    }
  }
}
```

这是 snake_case 计数对象，字段可能缺失；更完整的模型 usage 位于 `providerData.rawUsage` 和 `providerData.usage`。

## 4. `reasoning`

```json
{
  "id": "...",
  "parentId": "...",
  "timestamp": 1785136563202,
  "type": "reasoning",
  "providerData": {
    "messageId": "...",
    "model": "hy3",
    "requestModelId": "hy3",
    "requestModelName": "Hy3",
    "traceId": "...",
    "conversationRequestId": "...",
    "agent": "cli"
  },
  "content": [],
  "rawContent": [
    { "type": "reasoning_text", "text": "..." }
  ],
  "sessionId": "...",
  "cwd": "..."
}
```

```ts
type ReasoningRecord = CommonRecord & {
  type: "reasoning";
  content: ContentBlock[];       // 样本中几乎总是 []
  rawContent: ReasoningBlock[];
  status?: "incomplete";
};

type ReasoningBlock = {
  type: "reasoning_text";
  text: string;
};
```

少量 reasoning 记录的 `content` 使用 `input_text`，因此读取器不要假设该数组永远为空。

## 5. `function_call`

工具调用记录：

```json
{
  "id": "...",
  "parentId": "...",
  "timestamp": 1785136569273,
  "type": "function_call",
  "providerData": {
    "extra_fields": null,
    "reasoning": "...",
    "messageId": "...",
    "model": "hy3",
    "requestModelId": "hy3",
    "requestModelName": "Hy3",
    "traceId": "...",
    "conversationRequestId": "...",
    "agent": "cli",
    "argumentsDisplayText": "session.json"
  },
  "callId": "chatcmpl-tool-...",
  "name": "Read",
  "arguments": "{\"file_path\":\"/Users/.../session.json\"}",
  "sessionId": "...",
  "message": {
    "usage": {
      "input_tokens": 31981,
      "output_tokens": 46,
      "total_tokens": 32027,
      "cache_read_input_tokens": 288
    }
  },
  "cwd": "..."
}
```

```ts
type FunctionCallRecord = CommonRecord & {
  type: "function_call";
  callId: string;
  name: string;
  arguments: string; // 通常是 JSON 编码字符串，需要二次解析
  message?: { usage: SnakeCaseUsage };
  status?: "incomplete";
};
```

在当前样本中，2,926/2,928 个 `arguments` 可再次解析为 JSON object，2 个记录因中断或异常内容无法解析。因此解析器应保留原始字符串，并允许二次解析失败。

实测工具名包括 `Read`、`Bash`、`DeferExecuteTool`、`Write`、`Edit`、`present_files`、`Grep`、`ToolSearch`、`automation_update`、`TaskUpdate`、`WebSearch`、`Skill`、`Glob`、`TaskCreate`、`WebFetch`、`show_widget`、`read_me` 和 `Agent`。工具名是开放集合，不应写死。

## 6. `function_call_result`

工具结果通过 `callId` 与 `function_call.callId` 配对：

```json
{
  "id": "...",
  "parentId": "<function_call.id>",
  "timestamp": 1785136569292,
  "type": "function_call_result",
  "name": "Read",
  "callId": "chatcmpl-tool-...",
  "status": "completed",
  "output": {
    "type": "text",
    "text": "..."
  },
  "providerData": {
    "messageId": "...",
    "model": "hy3",
    "requestModelId": "hy3",
    "requestModelName": "Hy3",
    "traceId": "...",
    "conversationRequestId": "...",
    "agent": "cli",
    "toolResult": { "content": "..." }
  },
  "sessionId": "...",
  "cwd": "..."
}
```

```ts
type FunctionCallResultRecord = CommonRecord & {
  type: "function_call_result";
  name: string;
  callId: string;
  status: "completed";
  output: ToolOutput | ContentBlock[];
};

type ToolOutput = {
  type: "text";
  text: string;
};
```

`output` 有两种形态：

- 2,648 条是 `{ type: "text", text: string }`。
- 276 条是内容块数组，数组元素当前观测为 `{ type: "input_text", text: string }`。

数组内容经常是工具协议返回的 JSON 字符串，需要视工具而定是否再解析。

当前样本有 2,928 个工具调用和 2,924 个工具结果；少出的 4 个调用没有结果行，不能假设每个调用都完整闭合。

## 7. `file-history-snapshot`

```json
{
  "id": "...",
  "timestamp": 1783923975535,
  "type": "file-history-snapshot",
  "isSnapshotUpdate": false,
  "snapshot": {
    "messageId": "...",
    "trackedFileBackups": {}
  },
  "cwd": "..."
}
```

```ts
type FileHistorySnapshotRecord = CommonRecord & {
  type: "file-history-snapshot";
  isSnapshotUpdate: boolean;
  snapshot: {
    messageId: string;
    trackedFileBackups: Record<string, FileBackup>;
  };
};

type FileBackup = {
  version: number;
  backupTime: number;       // Unix epoch milliseconds
  backupFileName?: string;
};
```

`trackedFileBackups` 的 key 可以是工作区相对路径，也可以是绝对路径；例如 `ma_calc.py`、`.workbuddy/memory/2026-07-13.md` 或 `/Users/.../file.md`。空对象很常见。

## 8. `ai-title`

```json
{
  "timestamp": 1785136563202,
  "type": "ai-title",
  "aiTitle": "Summarize schema of session.json",
  "sessionId": "...",
  "cwd": "..."
}
```

这是唯一一个当前样本中没有 `id` 的记录类型。`aiTitle` 是展示用标题字符串。

## 9. `providerData`

`providerData` 是模型适配层和工具渲染层的扩展对象，不是所有记录都具备完整字段。常见字段如下：

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `agent` | string | 当前样本主要为 `cli` |
| `messageId` | string? | 模型响应/消息分组标识 |
| `model` | string? | 实际模型名 |
| `requestModelId` | string? | 请求模型 ID |
| `requestModelName` | string? | 展示用模型名 |
| `traceId` | string? | trace 标识 |
| `conversationRequestId` | string? | 单次对话请求标识 |
| `reasoning` | string? | 调用发生时附带的推理文本 |
| `argumentsDisplayText` | string? | 工具参数的展示文本 |
| `extra_fields` | object/null? | 供应商扩展字段；常见值为 `null` |
| `rawUsage` | object? | snake_case 的原始 token 统计 |
| `usage` | object? | camelCase 的归一化统计 |
| `toolResult` | object? | 工具结果渲染和原始响应 |
| `error` | object? | 模型或请求错误 |
| `skipRun` | boolean? | 是否跳过运行 |
| `isPartialAborted` | boolean? | 是否部分中断 |
| `isCompacted` / `isCompactInternal` / `isSummary` | boolean? | 压缩/摘要相关标记 |
| `compactType` | string? | 压缩类型 |
| `discard` | boolean? | 是否丢弃 |

### 9.1 usage 结构

`providerData.rawUsage` 通常包含以下 snake_case 计数：

```ts
type RawUsage = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  prompt_cache_hit_tokens?: number;
  prompt_cache_miss_tokens?: number;
  cache_read_input_tokens?: number;
  cache_creation_input_tokens?: number;
  prompt_cache_write_tokens?: number;
  completion_thinking_tokens?: number;
  credit?: number;
  cached_tokens?: number;
  prompt_tokens_details?: Record<string, number>;
  completion_tokens_details?: Record<string, number>;
};

type NormalizedUsage = {
  requests?: number;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  inputTokensDetails?: Array<Record<string, number>>;
  outputTokensDetails?: Array<Record<string, number>>;
};
```

不要把 `rawUsage`、`usage` 或 `message.usage` 当成同一个对象；它们是不同命名风格、不同粒度的重复统计。

### 9.2 `toolResult`

`function_call_result.providerData.toolResult` 的实测结构是开放对象：

```ts
type ToolResult = {
  content?: string;
  title?: string;
  renderer?: {
    type: "text" | "code" | "diff" | "list" | "todo" | string;
    value?: string;
    context?: Record<string, unknown>;
  };
  rawResponse?: Record<string, unknown>;
  mcpMeta?: Record<string, unknown>;
  error?: string | Record<string, unknown>;
  subAgent?: {
    sessionId?: string;
    lastId?: string;
  };
};
```

`rawResponse` 与 `mcpMeta` 依工具/连接器变化。Shell 工具的 `rawResponse` 可能包含 `exitCode`、`signal`、`interrupted`、`sandboxDenied`、截断标记和删除事件；任务工具可能包含 `task` 或 `todos`。这些字段应按 opaque JSON 保留。

## 10. 记录关联与重建

可按下列关系重建一轮对话：

```text
文件名 / sessionId
        │
        ├── parentId：记录树/模型响应的父记录
        ├── id：模型响应下的共享节点标识，不能单独当主键
        └── callId：function_call ↔ function_call_result
```

建议的读取流程：

```text
raw JSONL
  -> 保持原始行顺序读取
  -> 按顶层 type 分派
  -> message/reasoning 解析 content 和 rawContent
  -> function_call.arguments 尝试二次 JSON 解析，失败则保留字符串
  -> 用 callId 配对工具调用和工具结果
  -> 用 parentId / id / providerData.messageId 辅助重建响应树
  -> file-history-snapshot 独立处理，不强行归入消息 turns
```

实现时应注意：

1. 不要按时间戳排序覆盖原始行顺序；时间戳可能相同或局部回退。
2. 不要把 `id` 当作 JSONL 行的唯一主键；同一个 `id` 可以对应 `message` 和多个 `function_call`。
3. `callId` 适合做工具调用关联键，但中断、重试或历史截断时可能只有一侧。
4. `function_call.arguments`、工具结果数组中的 `text` 和 `content` 可能承载第二层 JSON，需要按工具语义决定是否解析。
5. `content[].text`、工具输出和 `rawResponse` 可能包含敏感上下文、文件内容、命令输出或凭据片段；导出或展示前应脱敏。
6. 所有可选字段都应允许缺失；错误路径还可能出现 `null`、部分响应和 `status: "incomplete"`。
7. 保留未知顶层类型、未知内容块类型和未知扩展字段，避免 WorkBuddy 升级后历史文件不可读。
