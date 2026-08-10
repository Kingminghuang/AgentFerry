# 网页来源 Vault 目录与笔记规范

**状态：** 已确认的设计  
**日期：** 2026-08-07  
**所属设计：** [网页与本地会话到 Obsidian 知识管道](web-to-obsidian-knowledge-pipeline-design.md)
**范围：** `01 Sources/Web/` 下由网页抓取、标准化和发布器物化的来源笔记及其允许附件

## 1. 定位与规范层级

本文是网页来源的最终 Vault 物化规范。它定义如何将已验证的 `DocumentNormalized` 写为稳定 source bundle、Markdown、证据链接、附件、日志和版本更新；不定义发现、抓取、正文标准化、提炼或概念解析算法。上游输入、身份、版本和 evidence block 的生产规则由[网页到 OKF Producer 规范](web-to-okf-producer.md)定义。

下列规则由主设计稿定义并在本文中直接适用：Vault 根目录配置、OKF v0.2 合规边界、标识符与 slug 验证、受管区块与人工内容保护、发布事务、安全与保留策略。若本文与主设计稿的共用规则冲突，以主设计稿为准。

## 2. 目录与路径

所有路径均相对于配置的 Vault 根目录：

~~~text
01 Sources/
  Web/
    <domain-slug>/
      <stable-source-key>/
        index.md
        source.md
        log.md
        assets/
~~~

- `domain-slug` 来自已校验 canonical URL 的主机名。
- `stable-source-key` 由稳定 `source_id` 派生为路径安全的目录名，不从标题或显示名称派生；路径一经首次发布不得因标题、显示名称或后续正文变化而改名。
- 每个 source bundle 的 `index.md` 和 `log.md` 均无 frontmatter；`source.md` 是唯一的 `type: Web Article` 概念文档；允许的 bundle 附件写入同目录的 `assets/`。
- 发布器在落盘前必须验证路径仍在 Vault 根目录内，并拒绝路径分隔符、纯点路径段和保留文件名。
- 原始 HTML、清洗全文、HTTP 响应和原始抓取记录属于 Vault 外的 Evidence Store；`01 Sources/Web/` 不是网页全文镜像。

### 2.1 `index.md` 与 `log.md`

`index.md` 是 OKF 保留目录清单，只能链接当前 source bundle：

~~~markdown
# <文章标题>

## Documents

- [来源](source.md)

## Assets

- [<asset-name>](assets/<asset-name>) — `sha256:<hex>`
~~~

空 `Assets` 区块可省略；其他列出的文件不存在时必须阻止发布。

`log.md` 是 OKF 保留的目录更新日志，必须无 frontmatter、日期倒序，并使用结构化散文记录成功事件：

~~~markdown
# Directory Update Log

## 2026-08-10

- **Update** — at: 2026-08-10T12:00:00Z; by: web-knowledge-pipeline/1.0; document_version_id: `docv:...`; changed: [source.md](source.md); reason: canonical content changed.
~~~

事件类型固定为 `Creation`、`Update`、`Metadata Update`、`Source Reset`、`Attachment`、`Deprecation` 和 `Migration`。无变化或失败不写入 source-local `log.md`；失败由 Run Journal 记录。

## 3. 网页来源笔记

每个通过抓取及策略校验的标准化网页工件在 `01 Sources/Web/` 中有一个 source bundle。`source.md` 是 OKF 概念文档，必须有可解析 YAML frontmatter 和非空 `type`。

frontmatter 至少包含：

- `id`、`type: Web Article`、`kind: web-article` 与 `title`；
- `resource`、`canonical_url`、`original_url`、`domain` 与 `source_subscription_id`；
- `published_at`、`captured_at`、`document_version_id`、`content_hash`、`language` 与 `status`；
- `crawl` 中的 robots 判定、HTTP 状态和最终 URL；
- 合规的 `generated.by`、`generated.at` 与可用时的 `prompt_version`；
- 至少一个带 `id` 与 `resource` 的 `sources` 条目；以及 `managed_by: web-knowledge-pipeline`。

`sources[].resource` 是来源文章的 canonical URL。管道特有的来源订阅 ID、文档版本 ID 和 evidence ID 作为同一条目的扩展字段保存，不能替代 `resource`。

### 3.1 Formatter 约束

每篇网页来源笔记必须以 UTF-8 和 LF 换行写入。文件第一行与 frontmatter 结束行均为独占一行的 `---`；不得在 frontmatter 前插入空行、BOM、标题或 HTML 注释。frontmatter 使用可解析 YAML，字符串含 `:`、`#` 或 YAML 可能隐式转换的值时必须加引号。`generated.by` 使用 `<producer>/<version>` actor，`generated.at`、`published_at`、`captured_at` 使用带时区的 ISO-8601 时间。`status` 只能为 `draft`、`stable` 或 `deprecated`。

下列模板是必须产生的字段顺序和正文骨架；尖括号表示 producer 的值，不能原样写入最终文件。未适用的可选字段可省略，未知 frontmatter 字段与受管区块外人工内容必须原样保留：

~~~markdown
---
id: "source:<domain-slug>:<stable-identity>"
type: Web Article
kind: web-article
title: "<文章标题>"
description: "<单句来源描述>"
resource: "<canonical-url>"
canonical_url: "<canonical-url>"
original_url: "<submitted-or-feed-url>"
domain: "<canonical-host>"
source_subscription_id: "<source-id>"
published_at: "<ISO-8601>" # 未知时省略
captured_at: "<ISO-8601>"
document_version_id: "docv:<document-id>:<content-hash-prefix>"
content_hash: "sha256:<hex>"
language: "<BCP-47-or-und>"
status: stable
crawl:
  robots_allowed: true
  http_status: 200
  final_url: "<final-url>"
generated:
  by: web-knowledge-pipeline/1.0
  at: "<ISO-8601>"
sources:
  - id: origin
    resource: "<canonical-url>"
    title: "<文章标题>"
    source_id: "<source-id>"
    document_version_id: "<document-version-id>"
    evidence_ids: ["ev:<stable-id>"]
managed_by: web-knowledge-pipeline
---

# 摘要
<!-- AGENT:BEGIN source-summary -->
<由当前版本 evidence block 支持的摘要。>[^origin]
<!-- AGENT:END source-summary -->

# 证据片段
> <短引文> ^ev-<stable-id>

# 提取出的概念
<!-- AGENT:BEGIN extracted-concepts -->
- [<Concept>](</02 Concepts/<type>/<concept>.md>)
<!-- AGENT:END extracted-concepts -->

# 人工笔记
<用户维护的内容>

[^origin]: [<文章标题>](<canonical-url>)
~~~

`# 摘要`、`# 证据片段`、`# 提取出的概念` 与 `# 人工笔记` 各出现一次，按模板顺序输出。每个证据 block 独占一个引用段落，block ID 置于该段落最后；不得将 block ID、HTML 管理标记或脚注放入 YAML。所有指向 vault 内概念或附件的链接必须使用标准 Markdown 链接；不能以 Obsidian wiki link 作为唯一链接。

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

摘要、证据片段、概念列表及管道拥有的 frontmatter 字段是受管内容。未知 frontmatter 字段、`# 人工笔记` 和全部受管标记之外的内容必须字节级保留；若受管区块被人工编辑，发布器创建冲突报告而不覆盖该区块。

## 4. 证据与链接

标准化器为当前文档版本生成稳定 evidence block。每个 block 至少包含短引文、标准化正文的偏移、片段哈希和 evidence ID；Vault 中短引文的长度受来源策略限制。

证据 block 使用 Obsidian block ID，概念笔记和报告使用标准 Markdown 链接定位，例如：

~~~markdown
[证据](</01 Sources/Web/example/source-example-a1b2c3/source.md#^ev-a1b2c3>)
~~~

概念笔记的 `sources` 条目必须同时记录来源笔记路径、文档版本 ID 和 evidence ID。不得使用 wiki link 作为唯一链接表示，也不得把没有当前提炼请求中 evidence ID 支持的内容发布为概念主张。

## 5. 附件与内容边界

网页来源默认只发布元数据、摘要、短引文和概念链接，不发布受版权保护文章的全文。网页引用的文件也不会默认下载。

仅当来源策略明确允许、资源通过抓取安全检查且保留策略允许时，发布器才能将附件写入同一 source bundle 的 `assets/`。来源笔记必须从原位置链接该附件，并记录其哈希、MIME 类型、获取时间及原始 URL。附件不能承载唯一的来源、证据或概念溯源信息。

## 6. 版本与更新

网页身份、文档版本和 bundle 路径是不同概念：来源 ID 和 bundle 路径用于稳定定位；`document_version_id` 与 `content_hash` 描述一次已标准化的正文版本。

- 内容哈希未变化时，跳过提炼与发布，不生成重复来源笔记。
- 内容变化时，发布器只更新受影响的受管字段和受管区块；旧版本的原始内容、标准化内容与输入哈希保存在 Evidence Store 和 publication manifest 的版本记录中。
- 现有概念到旧证据的链接不得被静默改写为新证据；解析器仅在新提炼结果确有支持时更新受影响概念。
- 来源不可访问时，来源笔记和受影响概念可标为 `stale`，但不得自动删除既有笔记或证据。

每次成功发布均记录输入哈希、前一版本及已发布路径，并在 source bundle 的 `log.md` 写入对应事件，以支持幂等重试、审计和回滚。`index.md`、`source.md`、`assets/` 和 `log.md` 必须作为一个发布事务原子替换。

## 7. 验证要求

网页 Vault 夹具和 golden-file 测试必须验证：稳定 source bundle 路径、`index.md` 与 `log.md` 无 frontmatter、`source.md` 首行 `---` 的可解析 YAML frontmatter、非空 `type`、`sources[].resource`、本规范规定的字段与正文标题顺序、脚注到 `sources[].id` 的归属、证据 block 链接、受管区块保护、未变化输入的幂等性、内容变更的增量更新、`log.md` 日期倒序和事件字段，以及默认不发布全文或未授权附件。
