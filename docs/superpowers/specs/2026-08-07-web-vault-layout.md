# 网页来源 Vault 目录与笔记规范

**状态：** 已确认的设计  
**日期：** 2026-08-07  
**所属设计：** [网页与本地会话到 Obsidian 知识管道](2026-08-03-web-to-obsidian-knowledge-pipeline-design.md)  
**范围：** `01 Sources/Web/` 下由网页抓取、标准化和发布器物化的来源笔记及其允许附件

## 1. 定位与规范层级

本文是网页来源的最终 Vault 物化规范。它定义如何将已验证的 `DocumentNormalized` 写为路径、Markdown、证据链接、附件和版本更新；不定义发现、抓取、正文标准化、提炼或概念解析算法。上游输入、身份、版本和 evidence block 的生产规则由[网页到 OKF Producer 规范](2026-08-07-web-to-okf-producer.md)定义。

下列规则由主设计稿定义并在本文中直接适用：Vault 根目录配置、OKF v0.2 合规边界、标识符与 slug 验证、受管区块与人工内容保护、发布事务、安全与保留策略。若本文与主设计稿的共用规则冲突，以主设计稿为准。

## 2. 目录与路径

所有路径均相对于配置的 Vault 根目录：

~~~text
01 Sources/
  Web/
    <domain-slug>/
      <YYYY>/
        <source-slug>--<short-hash>.md
05 Attachments/
  <source-id>/
    <permitted-asset-file>
~~~

- `domain-slug` 来自已校验 canonical URL 的主机名。
- `YYYY` 优先取文章发布日期的年份；发布日期未知时取 `captured_at` 的年份。
- `source-slug` 由稳定来源 ID 或 canonical URL 生成；`short-hash` 为同一稳定身份导出的短哈希。路径一经首次发布不得因标题、显示名称或后续正文变化而改名。
- 发布器在落盘前必须验证路径仍在 Vault 根目录内，并拒绝路径分隔符、纯点路径段和保留文件名。
- 原始 HTML、清洗全文、HTTP 响应和原始抓取记录属于 Vault 外的 Evidence Store；`01 Sources/Web/` 不是网页全文镜像。

## 3. 网页来源笔记

每个通过抓取及策略校验的标准化网页工件在 `01 Sources/Web/` 中有一篇来源笔记。笔记是 OKF 概念文档，必须有可解析 YAML frontmatter 和非空 `type`。

frontmatter 至少包含：

- `id`、`type: Web Article`、`kind: web-article` 与 `title`；
- `resource`、`canonical_url`、`original_url`、`domain` 与 `source_subscription_id`；
- `published_at`、`captured_at`、`document_version_id`、`content_hash`、`language` 与 `status`；
- `crawl` 中的 robots 判定、HTTP 状态和最终 URL；
- 合规的 `generated.by`、`generated.at` 与可用时的 `prompt_version`；
- 至少一个带 `id` 与 `resource` 的 `sources` 条目；以及 `managed_by: web-knowledge-pipeline`。

`sources[].resource` 是来源文章的 canonical URL。管道特有的来源订阅 ID、文档版本 ID 和 evidence ID 作为同一条目的扩展字段保存，不能替代 `resource`。

正文按以下顺序组织：

~~~markdown
# 摘要
<!-- AGENT:BEGIN source-summary -->
由证据支持的简洁来源摘要。[^origin]
<!-- AGENT:END source-summary -->

# 证据片段
> 可归因的短引文。 ^ev-<stable-id>

# 提取出的概念
<!-- AGENT:BEGIN extracted-concepts -->
- [Concept](</02 Concepts/<type>/<concept>.md>)
<!-- AGENT:END extracted-concepts -->

# 人工笔记
此处由用户维护。
~~~

摘要、概念列表及管道拥有的 frontmatter 字段是受管内容。未知 frontmatter 字段、`# 人工笔记` 和全部受管标记之外的内容必须字节级保留；若受管区块被人工编辑，发布器创建冲突报告而不覆盖该区块。

## 4. 证据与链接

标准化器为当前文档版本生成稳定 evidence block。每个 block 至少包含短引文、标准化正文的偏移、片段哈希和 evidence ID；Vault 中短引文的长度受来源策略限制。

证据 block 使用 Obsidian block ID，概念笔记和报告使用标准 Markdown 链接定位，例如：

~~~markdown
[证据](</01 Sources/Web/example/2026/example--a1b2.md#^ev-a1b2c3>)
~~~

概念笔记的 `sources` 条目必须同时记录来源笔记路径、文档版本 ID 和 evidence ID。不得使用 wiki link 作为唯一链接表示，也不得把没有当前提炼请求中 evidence ID 支持的内容发布为概念主张。

## 5. 附件与内容边界

网页来源默认只发布元数据、摘要、短引文和概念链接，不发布受版权保护文章的全文。网页引用的文件也不会默认下载。

仅当来源策略明确允许、资源通过抓取安全检查且保留策略允许时，发布器才能将附件写入 `05 Attachments/<source-id>/`。来源笔记必须从原位置链接该附件，并记录其哈希、MIME 类型、获取时间及原始 URL。附件不能承载唯一的来源、证据或概念溯源信息。

## 6. 版本与更新

网页身份、文档版本和文件路径是不同概念：来源 ID 和笔记路径用于稳定定位；`document_version_id` 与 `content_hash` 描述一次已标准化的正文版本。

- 内容哈希未变化时，跳过提炼与发布，不生成重复来源笔记。
- 内容变化时，发布器只更新受影响的受管字段和受管区块；旧版本的原始内容、标准化内容与输入哈希保存在 Evidence Store 和 publication manifest 的版本记录中。
- 现有概念到旧证据的链接不得被静默改写为新证据；解析器仅在新提炼结果确有支持时更新受影响概念。
- 来源不可访问时，来源笔记和受影响概念可标为 `stale`，但不得自动删除既有笔记或证据。

每次成功发布均记录输入哈希、前一版本及已发布路径，以支持幂等重试、审计和回滚。

## 7. 验证要求

网页 Vault 夹具和 golden-file 测试必须验证：确定性路径、完整 frontmatter、非空 `type`、`sources[].resource`、证据 block 链接、受管区块保护、未变化输入的幂等性、内容变更的增量更新，以及默认不发布全文或未授权附件。
