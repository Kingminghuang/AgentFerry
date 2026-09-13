# Session 跨设备同步：导入/导出设计

> 状态：Draft  
> 目标功能：通过 Dropbox / OneDrive / Google Drive / iCloud 等云盘目录，在多台设备之间同步 DeepSeek Harness Session。  
> 关联包：建议新建 `@deepseek-ai/dsh-session-sync`，不依赖、不扩展 `@deepseek-ai/dsh-session-log-export`。

## 1. 目标与非目标

### 目标

- 把指定 Session（根 Session + 子 Session 树 + 附件）导出到用户指定的云盘同步目录。
- 在另一台设备上导入该同步目录中的 Session。
- 保留：
  - Session header（`id`、`createdAt`、`cwd`、`parentSession`、`origin`、`isSeeded`、`delegationDepth` 等）
  - 完整事件日志、连续 `seq`、精确 `inheritedEventCount`
  - Session 树谱系
  - 被日志引用的图片和通用文件附件
  - 将导入的根 Session 重新绑定到本地 Workspace（在路径允许时）
- 云盘同步特性支持：
  - 文件可能延迟到达
  - 可能只同步到一半
  - 可能出现 Dropbox 风格的 `conflicted copy` 文件
  - 不依赖云盘厂商 API，只依赖普通目录语义
- 幂等、可重试、fail-closed。

### 非目标

- 不做同一 Session 的实时多写合并。
- 不自动解决两端分叉的事件日志；默认隔离并上报冲突。
- 不同步工作区文件本身，只同步 Session 数据。
- 不同步运行时状态：jobs、PTY、终端状态、队列、approval 状态。
- 不同步派生数据：projection cache、SQLite FTS 索引、request-image 缓存。
- 不实现云盘厂商 OAuth；由用户让云盘客户端同步文件夹。
- v1 不做端到端加密、不做增量压缩算法、不做自动垃圾回收。

---

## 2. 必须遵守的现状约束

从现有代码探索得到的硬约束：

1. **Session 日志是 append-only 的物理存储。**
   - 逻辑读取通过 `SessionPersistence.open(id, 'read'|'write')` 和 `SessionHandle`；
   - header 一旦创建不可变；
   - `cwd` 同时决定物理存储路径和 Workspace 归属校验。

2. **`cwd` 是 UI 可见性的关键字段。**
   - `ApiSessionList.list()` 会跳过 `cwd === undefined` 的 cold Session；
   - `SessionHistoryController.sourceFor()` 也会拒绝 `cwd === undefined` 的 Session；
   - 因此导出包必须保留有值的 `cwd`，导入也必须写回有值的 `cwd`。

3. **Workspace 归属是显式账本。**
   - `WorkspaceRegistry` 保存 `sessionIds`；
   - 成员资格要求 `realpath(header.cwd) === workspace.path`，且目录存在；
   - 首次初始化 Workspace 域时会按 cwd bootstrap，之后不会自动把新 Session 追加进已有 Workspace；
   - 导入如果需要分组，必须显式 `workspace.attachSession(sessionId)`。

4. **附件不在 Session 日志里。**
   - Session 事件只包含 `ImageAttachmentRef` / `FileAttachmentRef`；
   - 图片字节在 `<DSH_HOME>/attachments/v1/objects/...`；
   - 通用文件字节在 `<DSH_HOME>/attachments/v1/file-objects/...`，引用路径在 `<DSH_HOME>/attachments/v1/files/...`；
   - 同步包必须单独携带附件对象。

5. **子 Session 默认不出现在顶层列表。**
   - `origin: 'subagent'` 的行由 `ui-workspace` 隐藏；
   - 子 Session 通过父 Session 的 catalog 进入；
   - 同步时应当以根 Session 为单位导出整棵树，而不是只导一个子 Session。

6. **live Session 导出前必须 flush。**
   - 与 `dsh-session-log-export` 一样，需要通过 `ctx.sessions.get(id)` + `sessions.flush(session)` 把内存事件刷到持久化，再通过 read handle 读取。

7. **派生数据可以重建，不应同步。**
   - projection cache、SQLite 全文索引、request-image 缓存都可以在导入后按需重建。

---

## 3. 总体架构

建议新增 Host-only 插件包：

```text
packages/session/session-sync/
  src/
    index.ts          # Cordis 插件入口、ctx.sessionSync 服务
    bundle.ts         # manifest 读写与校验
    export.ts         # 导出算法
    import.ts         # 导入算法
    attachments.ts    # 附件收集与还原
    conflicts.ts      # 前缀比较、冲突分类
```

服务依赖：

```ts
export const inject = [
  'sessionPersistence',
  'sessions',
  'sessionQuery',
  'attachments',
  'workspaceRegistry',
]
```

可选依赖：

- `commands`：提供 `/sync export`、`/sync import`、`/sync status`
- `settings`：Web 设置页配置同步目录
- `connection` / `remote`：若需要 UI 触发导入导出

核心服务接口：

```ts
interface SessionSyncService {
  export(request: SessionSyncExportRequest): Promise<SessionSyncExportResult>
  import(request: SessionSyncImportRequest): Promise<SessionSyncImportResult>
  scan(signal?: AbortSignal): Promise<SessionSyncStatus>
}
```

配置示例：

```yaml
- name: '@deepseek-ai/dsh-session-sync'
  config:
    root: ~/Dropbox/DSH Sync        # 建议显式配置，默认不自动开启
    selection:
      mode: session-tree            # session-tree | all-ordinary
      includeArchived: false
    cwdPolicy: preserve             # preserve | remap
    conflictPolicy: quarantine      # quarantine | keep-local
    importOnStartup: false
    exportOnIdle: false
```

配置校验必须拒绝：

- `root` 为空；
- `root` 与 `sessionPersistence.root` 重叠；
- `root` 位于任意 attachment root 内；
- `root` 位于 `$DSH_HOME/sessions` 内。

---

## 4. 同步目录格式

云盘同步目录中建议采用**内容寻址 + 不可变对象 + manifest 最后落盘**的结构，而不是直接复制 `.jsonl.zstd`。

```text
<syncRoot>/
  dsh-session-sync/
    schema-version.json
    objects/
      events/
        <sha256>.jsonl
      attachments/
        <sha256>
    sessions/
      <sessionId>/
        revisions/
          <revisionHash>.json
    trees/
      <rootSessionId>/
        <treeRevisionHash>.json
    tmp/                         # 写入过程中使用，导入方忽略
```

### 4.1 内容寻址对象

- `objects/events/<sha256>.jsonl`
  - 内容是规范化的当前格式事件行；
  - 每行一个 SessionEvent；
  - 对象内容不可变，路径由内容 SHA-256 决定；
  - 同一个事件块在多个 revision 之间自动去重；
  - 两个设备写同样内容 → 同一路径 → 云盘不会产生有效冲突。

- `objects/attachments/<sha256>`
  - 图片和通用文件都按字节 SHA-256 存放；
  - 引用方在 manifest 中声明该对象的 kind、bytes、mediaType、name；
  - 导入时重新计算摘要并校验。

### 4.2 Session Revision Manifest

每个 Session 的每个导出快照写一个不可变 `revisions/<revisionHash>.json`：

```json
{
  "schema": 1,
  "sessionId": "session-...",
  "header": {
    "id": "session-...",
    "version": 3,
    "createdAt": 1730000000000,
    "cwd": "/Users/alice/project",
    "parentSession": null,
    "isSeeded": false,
    "delegationDepth": 0,
    "origin": null,
    "agentPreset": null
  },
  "headerSha256": "…",
  "inheritedEventCount": 0,
  "sourceFormatVersion": 3,
  "eventCount": 1234,
  "lastSeq": 1233,
  "previousRevision": "sha256:…",
  "segments": [
    {
      "startSeq": 0,
      "endSeq": 1234,
      "sha256": "…",
      "formatVersion": 3
    }
  ],
  "attachments": [
    {
      "kind": "image",
      "attachmentId": "sha256:…",
      "sha256": "…",
      "mediaType": "image/png"
    },
    {
      "kind": "file",
      "attachmentId": "sha256:…",
      "name": "report.csv",
      "bytes": 12345,
      "sha256": "…"
    }
  ],
  "source": {
    "deviceId": "…",
    "harnessVersion": "0.1.5",
    "exportedAt": "2026-09-24T00:00:00.000Z",
    "cwd": "/Users/alice/project"
  }
}
```

### 4.3 Tree Manifest

一次导出的 Session 树写一个不可变 `trees/<rootSessionId>/<treeRevisionHash>.json`：

```json
{
  "schema": 1,
  "rootSessionId": "session-root",
  "exportedAt": "…",
  "workspaceHint": {
    "sourcePath": "/Users/alice/project",
    "title": "project"
  },
  "sessions": [
    {
      "sessionId": "session-root",
      "revision": "sha256:…",
      "parentSession": null,
      "origin": null
    },
    {
      "sessionId": "session-child",
      "revision": "sha256:…",
      "parentSession": "session-root",
      "origin": "subagent"
    }
  ]
}
```

导入方只需要扫描 `trees/**/*.json`，包括被云盘改成 conflict-copy 文件名的 manifest。不要依赖文件名，应该校验内部 JSON。

### 4.4 为什么不用直接复制 Session 存储文件？

不能直接复制 `<DSH_HOME>/sessions`，因为：

- 默认 Web/base 使用 `compression: 'zstd'`；
- 物理 layout 是 `--project--/<encoded-id>/session.vN.jsonl.zstd`；
- 可能是旧 generation，需要迁移；
- 附件不在 sessions 目录；
- 不能表达 revision、冲突状态、附件清单；
- 云盘冲突文件名可能破坏目录名。
- 子 Session 的平铺关系需要从 header 重建，不适合作为同步格式。

---

## 5. 导出设计

### 5.1 导出范围

v1 支持两种模式：

```ts
type SessionSyncExportRequest =
  | { scope: 'session-tree'; rootSessionId: SessionId }
  | { scope: 'all-ordinary'; includeArchived?: boolean }
  | { scope: 'all-sessions'; includeArchived?: boolean }
```

- `session-tree`：默认，从根 Session 出发，包含全部后代。
- `all-ordinary`：导出所有 `origin !== 'subagent'` 的 Session，各自作为树根。
- `all-sessions`：包括 subagent 根，不推荐，除非做完整备份。

### 5.2 导出算法

```text
1. 确保同步根合法，且不与 session root / attachment root 重叠
2. 选择导出集合
3. 对每个 live root / descendant：
   - 如果是 live session：ctx.sessions.flush(session)
4. 对根 Session：
   - ctx.sessionQuery.traceSession(rootId)
   - 校验 trace.complete；不完整时默认失败，除非 allowPartial
5. 对每个 Session（先父后子）：
   - persistence.open(id, 'read')
   - events = handle.read(0, undefined).events
   - header = handle.header
   - inheritedEventCount = handle.inheritedEventCount
   - 生成 revision：
       - header 哈希
       - 事件分段（v1 可以只有一个 0..N 的 segment）
       - 事件 segment 写入 objects/events/<sha256>.jsonl
   - 从事件中收集附件 refs
6. 对每个附件 ref：
   - image: attachments.readImage(ref)
   - file: attachments.readFileStream(ref)
   - 写入 objects/attachments/<sha256>
   - 校验 ref.bytes / 摘要
7. 写所有 objects（内容寻址，天然幂等）
8. 写 revisions/<revisionHash>.json
9. 写 trees/<rootSessionId>/<treeRevisionHash>.json
```

### 5.3 序列化规则

- header：直接来自 `handle.header`，但以 JSON 对象形式写入 revision manifest。
- events：
  - 使用当前 writer 的规范编码；
  - 每行一个事件，保证 `seq` 从 0 连续；
  - 不包含物理 header 行；
  - `segments` 记录 `startSeq/endSeq/sha256/formatVersion`。
- `inheritedEventCount` 必须来自 `handle.inheritedEventCount`，不能从 header 猜。
- `sourceFormatVersion` 用于诊断；目标设备需要能读取或迁移该格式。
- 导出完成后再写 tree manifest；tree manifest 是整棵树“可导入”的提交点。

### 5.4 原子性与云盘友好

- 所有 object 先写 `<syncRoot>/dsh-session-sync/tmp/<uuid>.tmp`；
- `fsync` 后 rename 到最终内容寻址路径；
- 文件不存在才 rename；如果已存在则校验哈希后跳过；
- revision manifest、tree manifest 最后写；
- 导入方只读取 manifest 引用齐全且哈希通过的树；
- 导入方忽略 `tmp/`、`*.tmp`、以 `.` 开头且不含合法 manifest 的目录。

---

## 6. 导入设计

### 6.1 扫描与验证

```text
1. 递归扫描 trees/**/*.json
2. 对每个候选 tree manifest：
   - JSON/schema 解析
   - 找到根 Session 和每个子 Session 的 revision manifest
   - 校验所有 revision manifest 的 headerSha256
   - 校验所有 segment 的 hash、seq 范围、连续性和总 eventCount
   - 校验所有 attachment object 存在且 hash 匹配
3. 只把“完整且验证通过”的 tree 放入可导入集合
4. 不完整的 tree 保留为 pending，不做部分导入
```

### 6.2 导入计划

对每个可导入 tree，逐 Session 生成本地计划：

| 本地状态 | 远端关系 | 动作 |
|---|---|---|
| 不存在 | — | create |
| 存在，header 完全一致 | remote 是 local 的前缀 | no-op（本地领先） |
| 存在，header 完全一致 | local 是 remote 的前缀 | append 远端后缀 |
| 存在，header 完全一致 | local 与 remote 完全相等 | no-op |
| 存在，header 不完全一致 | — | conflict |
| 存在，事件日志分叉 | — | conflict |

“前缀”比较基于完整逻辑事件数组；可以在后续用 segment hash 优化。

### 6.3 写入 Session

#### 目标不存在

```ts
const handle = await ctx.sessionPersistence.create(header, {
  inheritedEventCount,
})
for (const batch of chunk(events, 500)) {
  await handle.append(batch)
}
await handle.flush()
await handle.close()
```

要点：

- `header` 必须来自 bundle，且 `cwd` 有值；
- `inheritedEventCount` 必须来自 bundle；
- 写入前再次校验每个 event 的 `seq === 当前长度`；
- `create` 会抛出 `SessionAlreadyExistsError`，应捕获并转入存在分支；
- 先校验完所有 attachment 再写 session，避免写了一半才发现附件缺失。

#### 目标已存在且远端是本地后缀

```ts
const handle = await ctx.sessionPersistence.open(id, 'write')
const local = await handle.read(0, undefined)
// 再次确认 local.events 是 bundle.events 的前缀
await handle.append(bundle.events.slice(local.events.length))
await handle.flush()
await handle.close()
```

要点：

- 如果本地 Session 是 live（`ctx.sessions.get(id)` 存在），写句柄可能已被占用；
  - v1 直接返回 `SESSION_BUSY`；
  - 或要求调用方先关闭/停稳该 Session。
- 如果 open write 失败，重试或报错，不做破坏性回退。

### 6.4 附件导入

导入 Session 事件之前，先确保所有被引用的附件对象在本地存在：

- 本地已有且摘要一致：跳过；
- 本地缺失：
  - 优先调用新的 attachments import seam：
    ```ts
    attachments.importImage({ ref, data })
    attachments.importFile({ ref, chunks })
    ```
    这些方法只做“字节与 ref 一致性校验”，不重新施加当前 admission 限制；
  - 如果没有该 seam，fallback：
    - 文件：`saveFile` / `saveFileStream`，要求返回 ref 与来源 ref 一致；
    - 图片：`saveImage`，要求返回 ref 与来源 ref 一致；
    - 不一致则视为导入失败，避免历史被重新编码。
- 同一 `attachmentId` 已存在但 bytes 摘要不一致：`SYNC_ATTACHMENT_CORRUPT`，拒绝导入。

> 建议把 attachment import seam 作为这个功能的正式依赖项，而不是把 `$DSH_HOME/attachments/v1` 当成公开文件格式。

### 6.5 Workspace 绑定

所有 Session 导入完成后：

```ts
for (const root of importedRoots) {
  if (root.cwd === undefined) continue
  const workspace = await ctx.workspaceRegistry.resolveByPath(root.cwd)
  if (workspace !== undefined) {
    await workspace.attachSession(root.id)
  }
  // 否则：session 会出现在 Ungrouped
}
```

- 只给普通根 Session 调 `attachSession`。
- 子 Session 不进入顶层 Workspace 分组，谱系由 header `parentSession` 表达。
- 如果 Workspace 不存在：
  - `cwdPolicy: preserve` 时，尝试 `workspaceRegistry.create(cwd)` 再 attach；
  - 如果 cwd 不存在或无法 canonicalize，保持 Ungrouped 并记录 warning。
- 如果 `workspaceRegistry` 的 domain 尚未初始化：
  - 第一次启动时 bootstrap 会自动按 cwd 创建 Workspace 并分配 Session；
  - 但已有 `DSH_HOME` 上通常不会自动追加，因此导入后显式 attach 仍然是必要的。

### 6.6 导入后的通知与派生数据

导入是通过 persistence 直接写入的，不会触发 `session/created`，因此：

- 运行中的 UI 不会收到 `api-session/added`；
- 需要提供刷新机制：
  - 简单方案：提示用户刷新页面；
  - 更好方案：新增 `sessionSync` → `SessionController` 的通知接口，例如：
    ```ts
    SessionController.announceStoredSessions(ids)
    ```
    由 Host 重新生成 cold summary 并 emit `api-session/added`。
- projection cache：
  - 不导入、不复制；
  - 打开 Session 或后续 checkpoint 会重建；
  - 列表在 cache 缺失时仍能显示 fallback title。
- SQLite 全文搜索：
  - 不导入；
  - 下一次 `searchSessions()` 时 `session-query-sqlite` 会在 reconciliation 中列出并索引新增 Session；
  - 因此内容搜索会短暂滞后，但不需要重启。

---

## 7. 冲突处理

### 7.1 冲突定义

以下任一情况视为冲突：

- 同一个 `sessionId`，但不可变 header 字段不一致：
  - `createdAt`、`parentSession`、`isSeeded`、`delegationDepth`、`origin`、`agentPreset`；
- 同一个 `sessionId`，事件日志既非前缀关系，也不是完全相等；
- 同一 tree 内父 Session 和子 Session 的 `parentSession` 关系不一致；
- 同一 `attachmentId` 对应不同字节摘要，或同一 path 对应不同 hash。

`cwd` 是否视为身份字段：

- v1 `cwdPolicy: preserve`：视为身份字段，不一致即冲突；
- 未来 `cwdPolicy: remap`：bundle 额外保存 `sourceCwd`，但该模式需要单独的跨设备身份协议。

### 7.2 默认策略

```text
quarantine（默认）：
  - 不写本地 Session
  - 记录 conflict 报告
  - 保留云端 revision 不动
  - UI/CLI 显示冲突，由用户决定

keep-local：
  - 忽略远端 revision
  - 后续本地导出会形成新的 head

keep-remote：
  - 仅在用户显式确认后可用
  - 先把本地日志归档/备份，再执行覆盖式重建
```

**不要自动拼接两个分叉的后缀。** 两个离线设备各自产生的 `turn/start`、`tool/call` 等事件在 seq 上连续，但语义顺序不唯一，自动拼接会产生非法或不可解释的对话历史。

### 7.3 云盘 conflict copy

- 导入扫描不依赖文件名精确匹配；
- 对 `trees/**` 下所有 `*.json` 尝试解析；
- 相同内容哈希的对象可以安全去重；
- 多个 tree head 指向同一 Session 的不同 revision 时，先做前缀比较；无法判定则进入 conflict。

---

## 8. 跨设备路径问题

这是本功能最重要的设计约束。

### 8.1 问题

- Session header 的 `cwd` 是绝对路径；
- 物理存储路径也由 `cwd` 推导；
- Workspace 绑定要求 `realpath(cwd) === workspace.path`；
- Dropbox 路径通常包含用户名或盘符：
  - A 设备：`/Users/alice/project`
  - B 设备：`/home/alice/project`
  - Windows：`C:\Users\alice\project`

### 8.2 v1 建议：preserve

- bundle 原样保存 `cwd`；
- 导入时写回完全相同的 `cwd`；
- 如果目标设备上该路径存在且是目录：
  - 可以正常绑定 Workspace；
  - 可以继续作为工作目录运行 Agent；
- 如果目标设备上不存在：
  - Session 仍可被 `persistence.list()` 列出（因为 `cwd !== undefined`）；
  - 它不会进入 Workspace，会出现在 Ungrouped；
  - 历史可以查看，但继续对话/恢复 Agent 可能失败或缺少工作区语义。
- 可选 operator workaround：
  - 在目标设备上创建同名路径或 symlink；
  - 如果 symlink realpath 后指向本地 Workspace，`WorkspaceRegistry` 反而可以按其 canonical path 完成绑定。

### 8.3 未来：remap

若必须把 `/old/path` 映射到 `/new/path`：

- bundle 中保留 `source.cwd`；
- 导入端配置 `cwdMap`；
- 目标不存在该 Session 时，用映射后的 `cwd` 创建本地 header；
- 但要注意：
  - 本地 header 与其它设备不再不可变一致；
  - 双向同步时该 Session 会变成 header 冲突；
  - 如果 Session 事件中包含旧路径引用（工具结果、session-reference），它们不会被改写；
- 因此 `remap` 建议只作为一种显式的单向导入模式，而不是默认双向同步模式。
- 长期方案应是 WorkspaceRegistry 支持路径 alias / rebinding，让 header 保持不可变，UI 仍能按本地 Workspace 分组。

---

## 9. UI / UX 集成

### 9.1 Host 命令

建议先做 Host/CLI 路径，不急着改浏览器：

```text
/sync export              # 导出当前 Session 树
/sync export <sessionId>  # 导出指定根 Session
/sync import              # 扫描同步目录并导入可导入的 tree
/sync status              # 显示 pending / conflict / imported
```

配置项提供同步目录，避免斜杠命令接受任意 Host 路径。

### 9.2 Web UI（第二阶段）

可选 UI：

- 设置页新增「Session 同步」：
  - 同步目录
  - import on startup
  - export on session idle
  - conflict policy
- Session Header 更多操作中增加：
  - `同步此 Session`
- 同步状态/冲突对话框。
- 因为 Host 路径选择涉及权限，Web 端建议只编辑配置，不直接选 Host 目录；桌面端可以走原生目录选择器。

### 9.3 自动触发

可考虑但不要 v1 默认开启：

- 启动时扫描并导入；
- Session idle / flush 后 debounce 导出；
- 定期扫描。

自动导入必须遵守：

- 不自动解决 conflict；
- 不自动删除本地 Session；
- 不自动覆盖本地更长的日志；
- 任何写入都要有 stable error code 和日志。

---

## 10. 安全与隐私

Session 日志可能包含：

- 用户与模型对话；
- 工具参数和结果；
- 文件内容摘要；
- 路径、环境变量、凭据意外泄漏的内容。

因此：

- 导出到云盘必须是显式 opt-in；
- 默认不自动开启同步；
- 文档明确提示云盘提供方可能访问数据；
- 本地同步目录权限建议 `0700`，文件 `0600`；
- 不跟随 symlink 写入同步根之外；
- 校验所有 bundle 路径不包含 `..`、绝对路径、NUL；
- 摘要用于完整性，不用于真实性；
- 端到端加密作为未来可选项，不应假装 v1 已安全。

---

## 11. 错误码建议

```ts
type SessionSyncErrorCode =
  | 'SYNC_ROOT_INVALID'
  | 'SYNC_BUNDLE_INCOMPLETE'
  | 'SYNC_BUNDLE_CORRUPT'
  | 'SYNC_HASH_MISMATCH'
  | 'SYNC_HEADER_CONFLICT'
  | 'SYNC_EVENT_DIVERGED'
  | 'SYNC_ATTACHMENT_MISSING'
  | 'SYNC_ATTACHMENT_CORRUPT'
  | 'SYNC_SESSION_BUSY'
  | 'SYNC_FORMAT_UNSUPPORTED'
  | 'SYNC_PATH_UNRESOLVED'
  | 'SYNC_CONFLICT_QUARANTINED'
  | 'SYNC_IMPORT_PARTIAL'
```

日志只记录 Session id、tree id、event count、对象 hash，不记录消息内容。

---

## 12. 测试计划

### 单元测试

- manifest schema / hash 校验；
- 事件 segment 连续性；
- prefix 比较：local-ahead / fast-forward / diverged；
- 附件 ref 与 object 摘要校验；
- 云盘 conflict copy 文件名扫描；
- 不完整 bundle 不产生任何写入；
- 重复导入幂等。

### 集成测试

构建临时 `DSH_HOME` 和临时 sync root：

1. 源端创建 root + child + image + file；
2. 导出 sync bundle；
3. 目标端空状态导入；
4. 断言：
   - `sessionPersistence.list()` 包含所有 Session；
   - `handle.read` 与源端逻辑日志一致；
   - `sessionQuery.traceSession()` 谱系一致；
   - attachments 可读且摘要一致；
   - Workspace 在路径匹配时完成 attach；
   - 不完整对象存在时拒绝导入。

### 双向/冲突测试

- A 导出 → B 导入；
- B 继续追加事件 → B 导出 → A 导入 fast-forward；
- A、B 在共同基线上分别追加 → 双端导出 → 导入方报 `SYNC_EVENT_DIVERGED`；
- 两端修改 header metadata → `SYNC_HEADER_CONFLICT`。

### live Session 测试

- 导出正在运行的 Session；
- 断言导出包含 flush 后的最新事件；
- 导出期间 Session 继续追加事件，不产生部分事件或错误 seq。

### UI 可见性测试

- 导入后 `session.list` 能看到行；
- `cwd` 缺失时验证会被隐藏并报错；
- `cwd` 存在时验证 Workspace / Ungrouped 行为；
- 导入后无需重启 SQLite，下一次搜索能命中新 Session。

---

## 13. 分阶段实施

### Phase 1 - Host 手动导入导出

- 新建 `dsh-session-sync` 包；
- 定义 schema-version 1 bundle；
- 实现 `session-tree` 导出；
- 实现完整校验的导入；
- 支持附件；
- `cwdPolicy: preserve`；
- `/sync export`、`/sync import`、`/sync status`。

### Phase 2 - Workspace 与 UI 刷新

- 导入后调用 `workspaceRegistry.create/resolveByPath` + `attachSession`；
- 增加 Host 通知接口，让运行中的 Client 刷新 session list；
- 状态/错误 UI。

### Phase 3 - 双向与自动同步

- 本地 `lastImportedRevision` / `lastExportedRevision` 状态；
- 启动时导入、idle 导出；
- conflict quarantine 报告；
- 旧 revision 清理命令。

### Phase 4 - 增量与路径重绑定

- events 从单 segment 拆分为固定区间内容寻址 segment；
- attachment 对象共享；
- `cwdPolicy: remap` 或 Workspace alias；
- 端到端加密可选项。

---

## 14. 与 `dsh-session-log-export` 的关系

不要直接依赖或复用 `@deepseek-ai/dsh-session-log-export`：

| 维度 | dsh-session-log-export | session-sync |
|---|---|---|
| 目标 | 浏览器下载 ZIP | 云盘目录长期同步 |
| 数据源 | Host 路由 + 浏览器触发 | Host 服务/命令 |
| 格式 | 一次性 ZIP | 版本化、内容寻址 bundle |
| 方向 | 只导出 | 导入 + 导出 |
| 冲突 | 不涉及 | 必须处理 |
| Workspace | 不涉及 | 必须处理绑定 |
| 派生数据 | 不涉及 | 明确不导出 |
| 传输 | HTTP `Response` | 普通文件系统/云盘 |

可以复用的只有底层概念：

- 通过 `sessionPersistence` 读句柄读取；
- 通过 `sessionQuery.traceSession` 拿谱系；
- 通过 `attachments.readImage` / `readFileStream` 拿附件；
- 通过 `sessions.flush` 保证 live Session 一致。

如果未来发现导出序列化代码重复，可以把这部分抽到一个更底层的公共库，而不是让 `session-sync` 依赖浏览器导出包。

---

## 15. 开放问题

1. **跨设备 cwd 重绑定**：v1 preserve，长期是否需要 Workspace alias/rebinding 协议？
2. **冲突后的用户体验**：冲突远端是丢弃、隔离、还是自动 fork 成新 Session？
3. **revision 保留策略**：云端 revision 是否需要有界保留？谁来 GC？
4. **大 Session 增量**：event segment 的分块策略和云盘成本需要实测。
5. **附件导入 seam**：是否正式给 `AttachmentStore` 增加 `import*`，还是 fallback 到 `saveImage` / `saveFile`？
6. **多设备身份**：是否需要设备 id、签名、加密，还是 v1 只依赖受信任云盘目录？
7. **自动导出触发点**：session idle、flush、dispose 还是定时？
8. **是否同步归档/删除状态**：v1 建议不删除，后续单独设计 tombstone。

---

这份设计的核心原则可以概括为：

> 不复制物理 Session 日志，导出**逻辑 Session 树 + 附件**；  
> 不依赖云盘锁，依赖**内容寻址 + manifest 最后提交 + 哈希校验**；  
> 不自动合并分叉日志，冲突**隔离并上报**；  
> 导入后通过 persistence API 重建 Session，并显式修复 Workspace 绑定与 UI 刷新。
