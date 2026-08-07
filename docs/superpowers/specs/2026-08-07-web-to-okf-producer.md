# 网页到 OKF Producer 规范

**状态：** 已确认的设计  
**日期：** 2026-08-07  
**所属设计：** [网页与本地会话到 Obsidian 知识管道](2026-08-03-web-to-obsidian-knowledge-pipeline-design.md)  
**范围：** 公开 URL、RSS 与 Atom 条目如何经发现、抓取、标准化和证据化，生产网页 OKF 来源工件

## 1. 定位与规范层级

本文是网页来源的 producer 契约，规定从外部网页数据到已验证的 `DocumentNormalized` 工件的过程、状态和不变量。生产的最终 Vault 表示由[网页来源 Vault 目录与笔记规范](2026-08-07-web-vault-layout.md)定义；该 layout 规范是本文的唯一 OKF 落盘输出契约。

本文不定义知识提炼、概念解析、检索或 UI 如何消费网页来源。通用事件信封、发布事务、Evidence Store、OKF v0.2 合规边界和共享安全策略由主设计稿定义；冲突时以主设计稿为准。

## 2. 输入、输出与状态边界

允许的输入只有三类：用户提交的 `http`/`https` URL、已登记 RSS/Atom 来源的响应、以及来源注册表中的策略与运行状态。网页 producer 不接受本地文件路径、浏览器登录态、`file:`、`data:` 或未登记的网络协议。

生产阶段及其持久化边界如下：

| 阶段 | 输入 | 持久化输出 | 不可变性 |
| --- | --- | --- | --- |
| 发现 | URL 或 feed 响应 | `DocumentDiscovered` | 同一发现身份可幂等重发 |
| 抓取 | 待抓取 URL 与来源策略 | `DocumentFetched`、原始响应引用 | 原始响应按版本保存 |
| 标准化 | 已抓取响应 | `DocumentNormalized`、证据块 | 内容哈希决定版本 |
| 物化 | `DocumentNormalized` | 网页 OKF 来源笔记 | 必须符合 layout 规范 |

Control Store 保存来源、运行、租约、去重键和发布状态；Evidence Store 保存原始响应、清洗正文和标准化版本。Vault 不是原始网页或工作流状态的权威副本。

## 3. 来源注册与发现

来源注册表是网页 producer 的控制面唯一事实来源。每个来源必须包含 `source_id`、`kind`、`entry_url`、启用状态和策略。RSS/Atom 来源还必须声明 schedule；手动 URL 创建一次性来源或任务。

策略至少覆盖：允许主机、最大页面数、最大链接深度、是否遵守 robots、每主机速率、并发数、最大响应字节数、证据短引文长度和附件保留开关。默认不跟随页面内链接；只有 `max_depth > 0` 时，才允许在同主机、受策略限制下继续发现。

RSS 2.0 与 Atom 条目统一投影为：

```json
{
  "external_entry_id": "feed guid 或 atom id",
  "url": "文章 URL",
  "title": "文章标题",
  "published_at": "ISO-8601 或 null",
  "updated_at": "ISO-8601 或 null"
}
```

适配器保存 ETag、Last-Modified 与条目指纹，并按 `source_id` 以下列优先级去重：外部条目 ID、已验证的 canonical URL、标准化内容哈希。feed 描述仅用于发现，不能成为知识证据。手动 URL 最多经历五次安全重定向，且只产生一个候选文档。

`DocumentDiscovered` 至少携带 `source_id`、发现 URL、可用时的外部条目 ID、规范 URL 提示、发现时间和发现身份。相同发现身份可重发，消费者必须幂等处理。

## 4. 安全抓取与原始响应

Fetcher 是无状态 worker，只能通过注入式 HTTP transport 访问网络。每次请求及每次重定向必须依序：验证 `http`/`https` scheme、解析 DNS、在连接前拒绝禁用 IP 范围、验证 HTTPS 证书，并重新执行上述检查。随后读取并执行 robots 判定（除非来源策略明确授权例外），应用每主机令牌桶和并发限制，以流式方式读取响应且在超出字节上限时中止。

抓取成功或可审计失败均生成 `DocumentFetched`，至少保存请求 URL、最终 URL、状态码、响应头、MIME 类型、抓取时间、正文 SHA-256 和 Evidence Store 原始响应引用。不得把正文直接作为事件唯一副本。策略拒绝、robots 拒绝、非成功响应、MIME 不支持或超限响应不能进入标准化阶段。

## 5. 标准化与稳定证据

Normalizer 按 MIME 类型选择解析器。HTML 必须移除脚本、导航、广告、cookie 弹窗和隐藏元素；采用可替换 readability 算法选择主内容；以最终 URL 解析相对链接；仅采用有效 canonical link。标题、段落、列表与表格转换为 Markdown；发布日期按 JSON-LD、OpenGraph、meta 标签、可见文本启发式的优先级取得。

规范化正文采用 UTF-8、统一换行和确定性 Markdown 序列化后计算 `sha256:<hex>`。同一 canonical identity 的内容哈希不变时不得创建新文档版本；变化时必须创建新的不可变版本，并保留此前版本的 Evidence Store 引用。

每个证据块至少包含：`evidence_id`、标准化正文的半开区间 `[start_offset, end_offset)`、短引文、片段 SHA-256 和正文版本引用。证据 ID 必须由 `document_version_id`、偏移与片段哈希确定性导出，在同一版本中稳定；短引文受来源策略限制，不能代替 Evidence Store 中的完整正文。

`DocumentNormalized` 至少包含：

```json
{
  "document_id": "doc:<stable-source-identity>",
  "document_version_id": "docv:<document-id>:<content-hash-prefix>",
  "source_id": "source:...",
  "canonical_url": "https://example.com/article",
  "title": "文章标题",
  "published_at": "ISO-8601 或 null",
  "captured_at": "ISO-8601",
  "language": "BCP-47 或 und",
  "content_hash": "sha256:...",
  "normalized_content_ref": "evidence://...",
  "evidence_blocks": [],
  "http_provenance": {}
}
```

事件正文可包含有大小上限的结构化预览，但 `normalized_content_ref` 与 `evidence_blocks` 是可重放的权威入口。`document_id` 由稳定来源身份导出，不能因标题或一次重定向改变；`document_version_id` 绑定内容哈希。

## 6. 从标准化工件到网页 OKF

仅当 `DocumentNormalized` 已完成策略与结构校验时，producer 才能请求 Vault 物化。它向 layout 层提供 canonical/original URL、来源订阅 ID、标题、发布日期、抓取溯源、语言、内容哈希、文档版本、受限短引文和 evidence blocks。

layout 层必须使用这些输入产生 `type: Web Article` 的 OKF 概念文档，且 `sources` 至少有一条以 canonical URL 为 `resource` 的来源。`source_id`、`document_version_id`、`evidence_ids` 等是该条目的扩展字段，不能替代 `resource`。网页全文、HTTP 响应及抓取日志仍在 Evidence Store；未经显式附件策略授权，不得发布附件。

## 7. 更新、失败与可重放性

- 同一 `event_id` 必须去重；同一语义事件必须幂等处理。
- 抓取、标准化、物化的检查点只在各阶段完成后写入；发布失败从最后成功阶段重试。
- 内容哈希不变时，跳过证据重新生成、提炼和来源笔记重复发布。
- canonical URL 变化但稳定来源身份未变时，保存为同一来源的新版本；身份无法安全判定时，创建新来源而非合并。
- 网络临时错误与 5xx 使用有上限的指数退避；4xx、robots 或策略拒绝不自动重试；解析/MIME 错误写入运行报告。
- 来源暂不可访问时，保留既有证据与来源笔记，可标为 stale，但不得自动删除。

## 8. Producer 验证夹具

网页 producer 的 fixture 与 golden-file 测试必须覆盖：RSS 与 Atom 条目去重、手动 URL 重定向上限、SSRF/禁用 IP 拒绝、robots 与大小限制、canonical URL 选择、确定性 Markdown 和内容哈希、证据偏移/ID 稳定性、未变化输入幂等性、内容变化的新版本，以及从 `DocumentNormalized` 到[网页 Vault layout](2026-08-07-web-vault-layout.md)所需字段的完整传递。
