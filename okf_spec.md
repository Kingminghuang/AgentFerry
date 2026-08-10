 

# 开放知识格式（OKF）

**版本 0.2**

OKF 是一种开放的、对人类和智能体都友好的格式，用于表示*知识*：围绕数据与系统的元数据、上下文和经过整理的洞察。它被设计为由人类编写、由智能体生成、在组织间交换，并同时被两者消费。

该格式刻意保持极简：一个包含 YAML frontmatter 的 markdown 文件目录。没有 schema 注册表，没有中央权威机构，也没有必需的工具链。如果你能 `cat` 一个文件，你就能阅读 OKF；如果你能 `git clone` 一个仓库，你就能发布它。

本文档是自包含的：它规定了生成和消费 OKF v0.2 所需的一切。v0.1 到 v0.2 的变更摘要见 §13。

---

## 1. 动机

AI 智能体的知识表示领域正在快速发展，许多不兼容的约定正在涌现。OKF 认为，知识最好以通用、成熟的格式来表示，这些格式应当：

- **可读**——人类无需工具即可阅读。
- **可解析**——智能体无需定制 SDK 即可解析。
- **可比较**——可在版本控制中进行 diff。
- **可移植**——可跨工具、组织和时间使用。

越来越多的知识语料库不再是一次编写然后阅读：它们**由智能体持续编写和维护**。当大部分概念由机器生成时，消费者需要一个简单的 markdown + frontmatter 约定无法直接回答的问题：

1. 这是从什么创建的，又是如何验证的？（**溯源**）
2. 我应该多大程度上信任它？（**信任**）
3. 它现在仍然正确吗？（**新鲜度**）
4. 它是当前版本吗？（**生命周期**）
5. 这个数字是按照我们规定的方式生成的吗？（**认证**）

OKF v0.2 将溯源、信任、生命周期和认证作为一等公民，同时保持格式的极简性。该格式只标准化了使知识语料库具备自描述能力所需的一小部分结构约定——超出此范围的内容由生产者自行决定。

### 目标

1. 定义一种通用格式，**生产者**（人类、智能体、导出管道）可以写入。
2. 指导**消费者**（智能体、UI、搜索索引、确定性代码）如何读取和遍历它。
3. 促进跨系统和组织的知识**交换**。
4. 标准化一小部分 frontmatter 字段，使智能体维护的语料库**可信赖**，而不规定任何运行时。

### 非目标

- 定义固定的概念类型分类体系。
- 规定存储、服务或查询基础设施。
- 替代领域特定的 schema（Avro、Protobuf、OpenAPI 等）。OKF *引用*它们，而非取代它们。
- 为执行器或认证器指向的代码指定打包或调用标准。OKF 固定的是接口，而非打包方式。

---

## 2. 术语

- **知识包**（Knowledge Bundle，简称 **bundle**）：一个自包含的、层次化的知识文档集合。它是分发的基本单位。
- **概念**（Concept）：包内的单个知识单元，以一个 markdown 文档表示。它可以描述一个具体的资产（一张表、一个 API）、一个抽象的概念（一个指标、一个业务流程），或介于两者之间的任何事物。
- **概念 ID**（Concept ID）：概念文件在包内的路径，去掉 `.md` 后缀。
- **Frontmatter**：markdown 文件顶部由 `---` 分隔的 YAML 元数据块。
- **正文**（Body）：文件中 frontmatter 之后的所有内容。
- **链接**（Link）：从一个概念到另一个概念的标准 markdown 链接，用于表达隐式父子层级之外的关系。
- **来源**（Source）：概念所衍生的材料，可以是包外部的或包内部的，记录在 `sources` frontmatter 字段中。
- **溯源**（Provenance）：概念所衍生的来源集合。
- **可信度信号**（Credibility signal）：一个客观的、按来源记录的事实（`author`、`usage_count`、`last_modified`），用于推断信任度；OKF 记录的是信号，而非判定结果（见 §5.1）。
- **行为者**（Actor）：一个标识谁或什么执行了某个操作的字符串，使用约定 `<producer>/<version>` 表示智能体，`human:<id>` 表示人类，`process:<id>` 表示自动化流程（见 §7）。
- **信任等级**（Trust tier）：从概念的 `verified` 字段派生的等级：未验证、机器确认或人类审核（见 §5.3）。
- **认证计算**（Attested Computation）：一种概念（`type: Attested Computation`），携带一种经过认可的计算值的方式，使消费者可以确认该值是通过运行该计算产生的（见 §10）。
- **执行器**（Executor）：执行计算并返回凭证的运行指令或代码（见 §10.2）。
- **凭证**（Receipt）：运行返回的证据，由 `executor.receipt` 定义形状；它是一个运行时产物，不存储在包中（见 §10）。
- **认证器**（Attester）：确定性的（非 LLM）代码，检查凭证并返回判定结果（见 §10.2）。

---

## 3. 包结构

包是一个 markdown 文件的目录树。目录结构独立于领域：生产者可以按照对被捕获的知识有意义的方式组织概念。

```
path/to/bundle/
  index.md                      # 可选。用于渐进式展示的目录列表。
  log.md                        # 可选。按时间顺序记录的更新历史。
  <concept>.md                  # 包根目录下的一个概念。
  <subdirectory>/               # 子目录将概念组织为分组。
    index.md
    <concept>.md
    <subdirectory>/
      ...
```

包可以以以下方式分发：

- 一个 git 仓库（推荐，因为它提供历史、归属和 diff）。
- 目录的 tarball 或 zip 归档。
- 一个较大仓库中的子目录。

### 3.1 保留文件名

以下文件名在层级的任何层级都有定义的含义，不得用于概念文档：

| 文件名       | 用途               |
| ------------ | ------------------ |
| `index.md` | 目录列表。见 §8。 |
| `log.md`   | 更新历史。见 §9。 |

所有其他 `.md` 文件都是概念文档。

标签通过 `tags` frontmatter 字段（§4.1）保持为一等公民。OKF 不指定按标签聚合文档的单独文件格式；需要标签浏览视图的消费者可以在消费时通过扫描 frontmatter 来合成一个。

---

## 4. 概念文档

每个概念都是一个 UTF-8 编码的 markdown 文件，包含两部分：

1. 一个 **YAML frontmatter 块**，由文件开头的 `---` 和结尾的 `---` 各自独占一行来分隔。
2. 一个 **markdown 正文**，包含自由格式的内容。

### 4.1 Frontmatter

```yaml
---
type: <类型名称>                  # 必填
title: <可选的显示名称>
description: <可选的单行摘要>
resource: <可选的底层资产规范 URI>
tags: [<标签>, <标签>, ...]       # 可选
# ... 信任、生命周期、溯源和计算系列（见 §5、§10）
# ... 其他生产者定义的键值对
---
```

**必填：**

- `type`：一个短字符串，标识概念的种类。消费者用它来进行路由、过滤和展示。示例值：`BigQuery Table`、`BigQuery Dataset`、`API Endpoint`、`Metric`、`Playbook`、`Reference`、`Attested Computation`。

  类型值**不**进行中央注册。生产者应当（SHOULD）选择具有描述性和自解释性的值；消费者必须（MUST）优雅地容忍未知类型，通常将其视为通用概念。

`type` 是唯一始终必填的键；仅包含 `type` 的概念也是完全合规的（§11）。

**推荐：**

- `title`：人类可读的显示名称。如果省略，消费者可以（MAY）从文件名派生标题。
- `description`：一句话概括概念。用于 `index.md` 生成器、搜索摘要和预览。
- `resource`：唯一标识概念所描述的底层资产的 URI。对于描述抽象概念而非物理资源的概念则省略。
- `tags`：一个用于横向分类的短字符串 YAML 列表。

可选的**溯源**、**信任**和**生命周期**系列（§5）以及认证计算概念的**计算**字段（§10）也可以出现。

**扩展：** 生产者可以（MAY）包含任何额外的键。消费者应当（SHOULD）在往返处理时保留未知键，并且不得（MUST NOT）拒绝包含未识别字段的文档。

### 4.2 正文

正文是标准的 markdown。生产者应当（SHOULD）优先使用结构化 markdown（标题、列表、表格、围栏代码块）而非自由格式的散文，因为结构有助于人类阅读和智能体检索。

没有必需的正文章节。以下标题具有**约定**含义，适用时应当（SHOULD）使用：

| 标题              | 用途                               |
| ----------------- | ---------------------------------- |
| `# Schema`      | 资产的列/字段的结构化描述。        |
| `# Examples`    | 具体的使用示例，通常为围栏代码块。 |
| `# Computation` | 认证计算的经认可的计算。见 §10。  |

对外部来源的逐条归属使用 markdown 脚注，脚注标签对应 `sources` 条目，而非正文引用列表（§5.1）。

### 4.3 示例：绑定到资源的概念

```markdown
---
type: BigQuery Table
title: Customer Orders
description: One row per completed customer order across all channels.
resource: https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders
tags: [sales, orders, revenue]
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-05-28T14:30:00Z }
---

# Schema

| Column        | Type      | Description                              |
|---------------|-----------|------------------------------------------|
| `order_id`    | STRING    | Globally unique order identifier.        |
| `customer_id` | STRING    | Foreign key into [customers](/tables/customers.md). |
| `total_usd`   | NUMERIC   | Order total in US dollars.               |
| `placed_at`   | TIMESTAMP | When the customer submitted the order.   |

# Joins

Joined with [customers](/tables/customers.md) on `customer_id`.
```

### 4.4 示例：未绑定到资源的概念

```markdown
---
type: Playbook
title: "Incident response: data freshness alert"
description: Steps to triage a freshness alert on the orders pipeline.
tags: [oncall, incident]
generated: { by: human:ahormati, at: 2026-04-12T09:00:00Z }
---

# Trigger

A freshness alert fires when `orders` lags more than 30 minutes behind its
expected SLA. See the [orders table](/tables/orders.md).

# Steps

1. Check the [ingestion job dashboard](https://example.com/dash).
2. ...
```

---

## 5. 溯源、信任和生命周期

这些 frontmatter 系列使"这从哪里来"、"我应该多大程度上信任它"以及"它是否仍然有效"可以从 frontmatter 中得到回答。所有都是可选的。它们的缺失本身就有含义：一个未验证的概念可以与已验证的概念区分开来，但永远不会被拒绝（§11）。

### 5.1 溯源：`sources`

`sources` 记录概念所衍生的材料，可以是包外部的或包内部的。

```yaml
sources:
  - id: ga4-schema
    resource: https://developers.google.com/analytics/bigquery/export-schema
    title: GA4 BigQuery Export schema
    author: team:ga4-docs
    usage_count: 5000
    last_modified: 2026-05-30
usage_window: { from: 2026-06-01, to: 2026-06-30 }
```

每个 `sources` 条目：

- `resource`：条目内必填。命名一个消费者可以跟踪的具体产物（一个绝对 URL、一个包相对路径、或一个指向 `references/` 子目录的路径，§6），或者一个它无法跟踪的总体或范围描述符（例如 `all queries in BigQuery project X`）。
- `id`：可选。一个用于归属单个声明的稳定键（见下文）。当正文引用该来源时应当（SHOULD）存在。
- `title`：可选。来源的人类可读标签。
- 可选的可信度信号 `author`、`usage_count` 和 `last_modified`，如下所述。

**来源可信度信号。** OKF 记录客观的、按来源的信号，使消费者可以通过判断其提取来源来判断对概念的信任程度。它不存储可信度分数：分数是主观的、不可跨消费者移植的，并且会过时。可信度是从信号中*推断*出来的，与信任等级（§5.3）的方式相同，而非存储。每个信号都是可选的，位于 `sources` 条目上：

- `author`：谁或什么产生了该来源，使用行为者约定（§7）。权威性信号。
- `usage_count`：在 `usage_window` 期间 `resource` 被使用的频率（仪表板查看、查询执行、页面阅读）。采用和活跃度信号。对于单个产物，它是该产物自身的使用计数；对于范围描述符，它是范围内涉及该概念的使用次数。
- `last_modified`：来源本身最后更改的时间（`YYYY-MM-DD`）。新鲜度信号，区别于 `generated.at`（§5.2），后者记录概念何时被编写。
- `usage_window`：作为 `sources` 的同级写入一次，为每个 `usage_count` 提供 `{ from, to }` 日期范围。单个条目可以（MAY）携带自己的 `usage_window` 来覆盖共享的。

`usage_count` 是一个粗粒度的信号。它在活跃 vs 不活跃和数量级层面是可比较的，也可以与来源自身随时间的历史进行比较，但不能作为精确的跨类型排名：定时查询的执行次数和人类有意的仪表板查看不具有同等的权重。消费者应当（SHOULD）将其解读为活跃度和趋势，而非分数。

谱系通过链接表达，而非专用字段。当一个 `resource` 指向另一个 OKF 概念时，派生边已经存在于包图中（§6），因此消费者可以（MAY）递归进入该来源自身的 `sources` 并让可信度传播。外部叶来源仅携带其固有信号。更深层的谱系（显式的外部 `derived_from` 或数据谱系）不在 v0.2 的范围内。

**逐条归属。** 要归属特定声明，使用 markdown 脚注，其标签为 `sources[].id`：

```markdown
The `events_` table is sharded daily as `events_YYYYMMDD`.[^ga4-schema]

[^ga4-schema]: GA4 BigQuery Export schema
```

脚注标签是连接到 `sources` 的键；消费者通过匹配的条目解析归属，而非解析脚注文本。标签是基于键而非位置的（`sources[0]`），因为智能体会不断重写这些文档：位置索引在列表重新排序时会静默地错误归属，而稳定的 `id` 可以在重新排序后继续存在。

### 5.2 信任：`generated` 和 `verified`

`generated` 记录当前内容是如何产生的。`verified` 记录谁或什么已根据来源或 `resource` 确认了内容。它们被分开是因为*编写*概念的人不必是*确认*它的人。

```yaml
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-20T22:53:05Z }
```

- `generated.by`：`generated` 内必填。一个行为者（§7）。
- `generated.at`：一个 ISO 8601 日期时间，标记内容的最后一次有意义的更改。消费者用它来区分最近的编辑和过时的事实。

```yaml
verified:
  - { by: human:ahormati, at: 2026-06-25T09:00:00Z }
  - { by: process:finance-nightly, at: 2026-06-26T02:00:00Z }
```

- `verified`：一个验证事件列表，每个事件包含 `by`（一个行为者）和 `at`（一个 ISO 8601 日期时间）。多个条目捕获独立的检查，例如人类签核加上夜间流程。"最近程度"取最新的 `at`。
- `verified` 独立于 `generated.at`：内容可以在没有重新确认的情况下更改，事实也可以在没有重新生成的情况下被重新确认。
- 单个验证者可以（MAY）写成一个不带列表短横线的 `{ by, at }` 映射。消费者必须（MUST）将裸映射视为单元素列表：

```yaml
verified: { by: human:ahormati, at: 2026-06-25T09:00:00Z }
```

### 5.3 信任等级

消费者从 `verified` 派生信任等级，从低到高：

- 没有 `verified` 键 ⇒ **未验证**（unverified）。
- 仅由非 `human:` 行为者 `verified` ⇒ **机器确认**（machine-confirmed）。
- 由 `human:<id>` 行为者 `verified` ⇒ **人类审核**（human-reviewed）。

没有信任 frontmatter 的概念仍然可以被消费；消费者不得（MUST NOT）拒绝它（§11）。信任等级是建议性信号，不是访问控制。

### 5.4 生命周期：`status`

```yaml
status: stable        # draft | stable | deprecated
```

- `draft`：尚未审核；可能不完整。
- `stable`：默认值；可供消费。
- `deprecated`：为链接和历史而保留；不再是当前的。

缺少 `status` ⇒ `stable`。

### 5.5 生命周期：`stale_after`

```yaml
stale_after: 2026-09-23   # 绝对日期；内容在此日或之后过时
```

可选。一个绝对日期（`YYYY-MM-DD`）。当 `today >= stale_after` 时概念过时。使用绝对日期而非相对 TTL，使过时判断成为一个简单的日期比较，无需引用概念被读取的时间。

---

## 6. 交叉链接和路径

### 6.1 概念之间的链接

概念可以（MAY）使用标准 markdown 链接到其他概念。支持两种形式：

- **绝对（包相对）：** 以 `/` 开头，相对于包根目录解释。这是**推荐**的形式，因为当文档在其子目录内移动时它是稳定的。

  ```markdown
  See the [customers table](/tables/customers.md) for the join key.
  ```
- **相对：** 标准的 markdown 相对路径。

  ```markdown
  See the [neighboring concept](./other.md).
  ```

从概念 A 到概念 B 的链接断言一种*关系*。具体的种类（父子、引用、连接、依赖）由周围的散文传达，而非链接本身。构建图视图的消费者通常将所有链接视为无类型关系的有向边。

消费者必须（MUST）容忍断开的链接：目标不存在于包中的链接不是格式错误的；它可能只是表示尚未编写的知识。

### 6.2 路径值字段

多个字段命名一个路径或 URI：`resource`、`sources[].resource`、`computation`、`executor.resource` 和 `attester.resource`（§10）。`sources[].resource` 可以是一个范围描述符（§5.1），在这种情况下它不是路径。每个路径值字段接受：

- 一个绝对 URL（例如 `https://...`），
- 一个以 `/` 开头的包相对路径，或
- 一个相对路径（例如 `../computations/revenue.md`）。

### 6.3 `references/` 约定

`references/` 子目录按约定将外部材料、运行指令或代码作为包内的一等概念进行镜像。来源、执行器和认证器通常指向其中（例如 `references/attesters/revenue.py`）。这是一个命名约定，不是要求。

---

## 7. 行为者约定

记录身份的字段（`generated.by`、`verified[].by`）使用统一的行为者约定：

- `<producer>/<version>` 用于智能体和工具，例如 `reference_agent/gemini-2.5-pro`。
- `human:<id>` 用于人类，例如 `human:ahormati`。
- `process:<id>` 用于自动化流程，例如 `process:finance-nightly`。

对信任进行分类的消费者（§5.3）依赖 `human:` 前缀，因此生产者必须（MUST）对手工编写或人类确认的内容使用它。

---

## 8. 索引文件

`index.md` 文件可以（MAY）出现在任何目录中，包括包根目录。它枚举目录的内容以支持**渐进式展示**：让人类或智能体在打开单个文档之前看到有什么可用。

索引文件不包含 frontmatter，一个例外：包根目录的 `index.md` 可以（MAY）携带 `okf_version` 键（§12）。正文使用一个或多个章节，每个章节在标题下对概念进行分组：

```markdown
# Section / Group Heading

* [Title 1](relative-url-1) - short description of item 1
* [Title 2](relative-url-2) - short description of item 2

# Another Section

* [Subdirectory](subdir/) - short description of the subdirectory
```

条目应当（SHOULD）包含来自链接概念的 frontmatter 的描述。生产者可以（MAY）自动生成 `index.md`；消费者可以（MAY）在没有时即时合成一个。

---

## 9. 日志文件

`log.md` 文件可以（MAY）出现在层级的任何位置，以记录该范围的变更历史。格式是一个扁平的、按日期分组的条目列表，最新的在前：

```markdown
# Directory Update Log

## 2026-05-22
* **Update**: Added a BigQuery table reference for [Customer Metrics](/tables/customer-metrics.md).
* **Creation**: Established the [Dataplex Playbook](/playbooks/dataplex.md).

## 2026-05-15
* **Initialization**: Created foundational directory structure.
```

日期标题必须（MUST）使用 ISO 8601 `YYYY-MM-DD` 格式。日志条目是散文；开头的加粗词（`**Update**`、`**Creation**`、`**Deprecation**`）是约定，不是要求。

---

## 10. 认证计算概念

认证计算概念不仅携带一个值*意味着什么*，还携带一种经过认可的*计算*方式，使消费者可以确认智能体运行了经过认可的计算，而不是自行即兴发挥。溯源（§5.1）回答"这个声明从哪里来"；认证回答"这个数字是按照我们说的方式生成的吗"。OKF 记录计算和检查它的手段；它本身不执行任何东西。

### 10.1 计算本身就是一个概念

一个经过认可的计算是一个独立的概念，类型为 `type: Attested Computation`。需要该值的概念（`Metric`、`BigQuery Table`）通过普通的 markdown 链接（§6）链接到它。三个属性支持将其作为独立概念：

- **`runtime` 定义了 `parameters` 的含义。** 参数是 SQL 绑定变量、dbt var 还是 Python 参数取决于运行时。将 `runtime` 和 `parameters` 放在一个 frontmatter 中使绑定语义不言自明。
- **一个计算，多个消费者。** 同一个计算可以支撑一个指标、一个仪表板概念和一个报告；作为一个概念它被引用一次并重复使用。
- **信任状态按计算独立。** `verified`、`stale_after` 和单个 `attester` 描述的是一个东西。收入、利润和利润率各自独立验证和认证，这是三个概念，而非一个 frontmatter 中的三个条目。

### 10.2 合约字段

合约是概念的顶层 frontmatter。除了溯源、信任和生命周期系列（§5）之外，认证计算概念还携带：

- `runtime`：此类型必填。唯一说明如何运行计算的字段，因此执行器和认证器如何解释它以及 `parameters` 的含义。示例值：`bigquery`、`postgres`、`dbt`、`python`、`Looker`。
- `parameters`：智能体可以填充的类型化、命名空位的列表。每个条目：`{ name, type, required }`。绑定语义遵循 `runtime`。
- `computation`：可选。一个指向持有计算的文件的路径（§6.2），用于替代内联正文围栏（见 §10.3）。缺失 ⇒ 正文 `# Computation` 围栏即为计算。
- `executor`：计算如何运行。`resource` 命名运行指令或代码；运行者（智能体或确定性消费者代码）遵循它。`receipt` 声明运行必须返回的字段，即认证器检查的证据（例如 BigQuery 的 `job_id` 和作业实际执行的 SQL）。
- `attester`：确定性检查。`resource` 命名代码（非 LLM），接受凭证并返回判定。它旨在消费者端运行。

`resource` 背后的内容（Skill、脚本、容器）是打包选择；OKF 固定的是接口，而非打包方式（§1）。

```markdown
---
type: Attested Computation
title: Revenue for fiscal year
description: Recognized revenue for a fiscal year, per Finance's definition.
status: stable
runtime: bigquery
parameters:
  - { name: year, type: integer, required: true }
executor:
  resource: references/skills/run-on-bq.md
  receipt: [job_id, executed_sql, result]
attester:
  resource: references/attesters/revenue.py
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-20T22:53:05Z }
verified: { by: human:ahormati, at: 2026-06-25T09:00:00Z }
stale_after: 2026-09-23
sources:
  - id: rev-policy
    resource: https://wiki.acme/finance/revenue-recognition
    title: Revenue recognition policy
---

# Computation

    SELECT SUM(amount) AS revenue
    FROM finance.recognized_revenue
    WHERE fiscal_year = @year

The computation binds only the declared `parameters`, per the recognition
policy.[^rev-policy]

[^rev-policy]: Revenue recognition policy
```

### 10.3 计算

以两种方式之一提供计算：

- **内联：** 正文中 `# Computation` 下的单个围栏代码块。最适合与合约一起审核的短计算。
- **文件：** 将 `computation` 设置为路径（§6.2）并省略正文围栏。最适合长或生成的计算，或者已经作为与非 OKF 工具共享的真实文件维护的计算。

```yaml
runtime: bigquery
computation: references/computations/lib/revenue.sql
parameters:
  - { name: year, type: integer, required: true }
```

智能体只可以（MAY）为声明的 `parameters` 提供*值*；它不得（MUST NOT）编写或编辑计算。将 `computation` 与参数值绑定到可执行产物是消费者的工作，认证器独立地重新派生相同的绑定以与实际运行的内容进行比较。因为比较是在凭证携带的展开、编译后的产物（`executed_sql`、`compiled_sql`）上进行的，所以重写的查询、替换的计算文件或变异的依赖都会使检查失败。类型化的、仅参数的表面使"是否运行了经认可的东西"成为机械比较而非判断。

### 10.4 使用计算的概念

一个文档很少是单个计算。一个讨论收入、利润和利润率的损益表概览保持为一个可读的概念，并为每个数字链接到一个认证计算：

```markdown
---
type: Metric
title: Revenue
description: Recognized revenue for a fiscal year.
tags: [finance, revenue]
status: stable
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-20T22:53:05Z }
---

# Definition

Recognized revenue sums `amount` over rows booked to the fiscal year,
computed by [the revenue computation](../computations/revenue.md).
```

因为每个计算都是独立的概念，收入可以是新鲜的而利润已过其 `stale_after`，并且每次运行各自认证。将它们放在一起是一个目录选择（一个带有 `index.md` 的 `computations/` 文件夹），而非 frontmatter 选择。

### 10.5 消费者如何使用它（参考性）

本小节是参考性的，不是规范性的。以下运行时产物**不**存储在包中。

1. **发现**：通过 `type: Attested Computation`，一个可以提升到 `index.md` 的 frontmatter 信号；消费者可以直接到达或通过跟踪使用它的概念中的链接到达。
2. **加载**：从 frontmatter 加载合约，从正文（或 `computation` 命名的文件）加载计算。
3. **参数化**：智能体为声明的参数提供值。
4. **执行**：执行器运行绑定的计算并返回由 `executor.receipt` 定义形状的凭证。
5. **认证**：消费者在凭证上运行认证器。它确认溯源（运行的计算等于 `computation` 与声明的参数绑定，而非智能体编写的 SQL）和保真度（显示的值与凭证的权威来源匹配，通过作业 ID 重新读取而非取自智能体的文本）。
6. **门控**：拒绝显示认证失败的結果；当 `today >= stale_after` 时警告或拒绝。成功时，展示判定结果（例如作业日志的链接），使信任可见。

### 10.6 验证与认证

`verified`（§5.2）和认证是不同的，两者都存在：

- `verified` 确认*定义*仍然符合策略。它是文档级的、缓慢的，并记录在包中。
- 认证确认单次*运行*以经认可的方式产生了值。它是每次调用的、运行时的，不存储在包中。

一个定义已过时的概念仍然可以干净地认证，一个刚验证的定义仍然需要每次运行时认证，这就是为什么两者都需要。

---

## 11. 合规性

一个包在以下条件下**合规**于 OKF v0.2：

1. 树中每个非保留的 `.md` 文件包含一个可解析的 YAML frontmatter 块。
2. 每个 frontmatter 块包含一个非空的 `type` 字段。
3. 每个保留文件名（`index.md`、`log.md`）在存在时遵循 §8 和 §9 的结构。

当信任、生命周期、溯源或计算系列存在时，生产者应当（SHOULD）遵循 §5 到 §10，消费者：

- 必须（MUST）将裸 `verified` 映射视为单元素列表（§5.2）。
- 不得（MUST NOT）因缺少任何可选系列而拒绝概念（§5.3）。
- 应当（SHOULD）仅从本文档指定的字段派生信任等级和过时状态，并且应当（SHOULD）展示而非静默丢弃认证失败（§10.5）。

消费者应当（SHOULD）将所有其他约束视为软性指导。特别是，消费者不得（MUST NOT）因为以下原因拒绝包：

- 缺少可选的 frontmatter 字段。
- 未知的 `type` 值。
- 未知的额外 frontmatter 键。
- 断开的交叉链接。
- 缺少 `index.md` 文件。

---

## 12. 版本控制

本文档规定 OKF 版本 **0.2**。修订按 `<major>.<minor>` 版本化：

- **次版本**升级引入向后兼容的添加（新的可选字段、新的约定章节标题）。
- **主版本**升级可能进行破坏性更改（重命名必填字段、更改保留文件名）。

包可以（MAY）在包根目录的 `index.md` frontmatter 块中（`index.md` 中唯一允许 frontmatter 的地方）使用 `okf_version: "0.2"` 声明它们的目标版本。不理解声明版本的消费者应当（SHOULD）尝试尽力消费而非拒绝包。

### 已考虑并推迟

以下内容被有意留到未来修订：

- 完整的运行时协议：凭证和判定的线路格式，以及围绕运行的认证生命周期。
- 认证器 ABI、可移植性和沙箱化，可能与未来关于服务和 Skill 的工作一起打包。
- 认证缓存。
- 语义层模板（Looker、dbt），其中认证器比较从 SQL 相等性转变为模型和绑定相等性。

---

## 13. 自 v0.1 的变更

v0.2 取代 OKF v0.1，在 §12 下是次版本升级，但有两个故意的破坏性变更在下面列出，因为它们重命名或淘汰了 v0.1 字段。v0.1 包在本文注明的回退条件下可被 v0.2 消费者消费。

### 13.1 破坏性变更

- **`timestamp` 被 `generated.at` 取代。** 概念的最后一次内容更改现在记录为 `generated: { by, at }`（§5.2）。消费者可以（MAY）在 `generated` 缺失时回退到遗留的 `timestamp`。
- **正文 `# Citations` 列表被 `sources` 取代。** 溯源移至 frontmatter（§5.1）。消费者应当（SHOULD）读取 `sources`，并且可以（MAY）仍然为 v0.1 文档解析遗留的 `# Citations` 正文列表。

### 13.2 新增变更

以下所有都是新增的：新的可选键、一个新的概念类型和一个新的约定标题。它们的缺失产生一个普通的 v0.1 概念。

- 新的 frontmatter 系列：`sources` 及其按来源的可信度信号（`author`、`usage_count`、`last_modified`）和同级 `usage_window`；`generated`、`verified`；`status`、`stale_after`（§5）。
- 新概念类型 `Attested Computation` 及其计算键 `runtime`、`parameters`、`computation`、`executor`、`attester`（§10）。
- 新的约定正文标题 `# Computation`（§4.2）。
- `generated.by` 和 `verified[].by` 的行为者约定（§7）。

其他所有内容（包结构、保留文件名、必填的 `type`、推荐的 `title`/`description`/`resource`/`tags`、交叉链接、索引文件、日志文件、宽松的合规性）均不变地延续。

---

## 附录 A：完整示例——损益表

一个使用所有系列的包，展示为损益表的 v0.1 到 v0.2 迁移，包含两个数字：收入和毛利润。

### v0.1 形式

单个文档：两个数字在一个概念中，SQL 以散文形式存在（智能体可以读取、忽略或重写），引用是一个扁平列表，唯一的时间戳是 `timestamp`。

```markdown
---
type: Metric
title: Income statement (fiscal year)
description: Headline income-statement figures for a fiscal year.
tags: [finance, income-statement]
timestamp: '2026-05-28T22:53:05+00:00'
---

# Definition
The income statement reports revenue and gross profit for a fiscal year.

# Revenue
Recognized revenue sums `amount` over rows booked to the fiscal year:

    SELECT SUM(amount) AS revenue
    FROM finance.recognized_revenue
    WHERE fiscal_year = <year>

# Gross profit
Gross profit by segment, per the cost-allocation standard:

    SELECT gross_profit FROM fct_income_statement
    WHERE fiscal_year = <year> AND segment = <segment>

# Citations
- https://wiki.acme/finance/fpa-handbook
- https://wiki.acme/finance/revenue-recognition
- https://wiki.acme/finance/cost-allocation
```

### v0.2 形式

两个数字拆分为认证计算，从一个叙述性概念链接。每个系列都已填充，两个计算故意处于不同的状态，使一个消费者得出两个判定。

```
bundles/finance/
  metrics/income-statement.md      type: Metric  (叙述，链接两者)
  computations/revenue.md          type: Attested Computation  (runtime: bigquery)
  computations/profit.md           type: Attested Computation  (runtime: dbt)
  references/skills/run-on-bq.md, run-dbt.md
  references/attesters/sql-equality.py, dbt-binding.py
```

`metrics/income-statement.md`，可读的文档；信任存在于它链接的内容上，而非此处：

```markdown
---
type: Metric
title: Income statement (fiscal year)
description: Headline income-statement figures for a fiscal year.
tags: [finance, income-statement]
status: stable
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-20T22:53:05Z }
verified: { by: human:ahormati, at: 2026-06-25T09:00:00Z }
stale_after: 2026-12-31
sources:
  - id: fpa-handbook
    resource: https://wiki.acme/finance/fpa-handbook
    title: FP&A reporting handbook
---

# Definition
The income statement reports [revenue](../computations/revenue.md) and
[gross profit](../computations/profit.md) for a fiscal year, per the FP&A
reporting handbook.[^fpa-handbook] Each figure is produced by a sanctioned,
attestable computation; this concept only narrates them.

[^fpa-handbook]: FP&A reporting handbook
```

`computations/revenue.md`，BigQuery SQL，人类验证，新鲜，并由携带可信度信号的活跃仪表板来源佐证：

```markdown
---
type: Attested Computation
title: Revenue for fiscal year
description: Recognized revenue for a fiscal year, per Finance's definition.
tags: [finance, revenue]
status: stable
runtime: bigquery
parameters:
  - { name: year, type: integer, required: true }
executor:
  resource: references/skills/run-on-bq.md
  receipt: [job_id, executed_sql, result]
attester:
  resource: references/attesters/sql-equality.py
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-28T14:00:00Z }
verified: { by: human:ahormati, at: 2026-06-25T09:00:00Z }
stale_after: 2026-12-31
sources:
  - id: rev-policy
    resource: https://wiki.acme/finance/revenue-recognition
    title: Revenue recognition policy
    author: team:finance-fpa
    last_modified: 2026-04-02
  - id: exec-rev-dash
    resource: dashboards/exec-revenue
    title: Executive revenue dashboard
    author: team:finance-fpa
    usage_count: 5000
    last_modified: 2026-06-18
usage_window: { from: 2026-06-01, to: 2026-06-30 }
---

# Computation

    SELECT SUM(amount) AS revenue
    FROM finance.recognized_revenue
    WHERE fiscal_year = @year

Recognized revenue per the recognition policy,[^rev-policy] corroborated by
the executive revenue dashboard.[^exec-rev-dash]

[^rev-policy]: Revenue recognition policy
[^exec-rev-dash]: Executive revenue dashboard
```

`computations/profit.md`，一个 dbt 模型，流程验证，已过 `stale_after`：

```markdown
---
type: Attested Computation
title: Gross profit for fiscal year
description: Gross profit by segment for a fiscal year, per the cost-allocation standard.
tags: [finance, profit]
status: stable
runtime: dbt
parameters:
  - { name: year, type: integer, required: true }
  - { name: segment, type: string, required: true }
executor:
  resource: references/skills/run-dbt.md
  receipt: [run_id, compiled_sql, result]
attester:
  resource: references/attesters/dbt-binding.py
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-06-14T14:00:00Z }
verified: { by: process:finance-nightly, at: 2026-06-12T08:00:00Z }
stale_after: 2026-06-15
sources:
  - id: cost-alloc
    resource: https://wiki.acme/finance/cost-allocation
    title: Cost allocation standard
---

# Computation

    SELECT gross_profit
    FROM {{ ref('fct_income_statement') }}
    WHERE fiscal_year = {{ var('year') }}
      AND segment = {{ var('segment') }}

Gross profit by segment per the cost-allocation standard.[^cost-alloc]

[^cost-alloc]: Cost allocation standard
```
