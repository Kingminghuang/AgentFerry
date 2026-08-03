# Web-to-Obsidian Knowledge Pipeline

**Status:** Approved design
**Date:** 2026-08-03
**Scope:** Public web URLs and RSS feeds to an Obsidian vault

## 1. Summary

Build a language-agnostic pipeline that discovers public web pages, captures and normalizes their content, uses an LLM to extract linked knowledge concepts, and publishes those concepts directly into an Obsidian vault. The system preserves source provenance and evidence for every generated claim, supports incremental updates, and protects human-authored note content during later synchronizations.

The system is **contract-first**: independently deployable components communicate only through versioned JSON messages and Markdown files. No component requires a shared programming language, runtime, or internal SDK.

## 2. Goals

- Accept a manually submitted public \`http\` or \`https\` URL.
- Subscribe to RSS or Atom feeds and periodically discover new article URLs.
- Generate and update a graph of Obsidian concept notes rather than merely saving one raw note per source page.
- Publish successful results automatically into the production Obsidian vault.
- Retain a canonical source URL, capture timestamp, evidence fragment, and confidence signal for every generated concept claim.
- Preserve human-authored sections in published notes across automatic updates.
- Permit any component to be replaced by an implementation in another language.

## 3. Non-goals for the first version

- Crawling authenticated sites, paywalled content, CAPTCHAs, or browser-only applications that require a logged-in session.
- Publishing full copies of copyright-protected articles into the vault by default.
- Treating LLM output as authoritative without evidence in the fetched source.
- Building a general-purpose search UI; Obsidian provides the primary user interface.

## 4. Architecture choice

### Considered approaches

| Approach | Advantages | Drawbacks | Decision |
| --- | --- | --- | --- |
| Monolithic crawler | Simple initial deployment | Fetching, LLM extraction, and publishing become tightly coupled | Rejected |
| Event-driven modular pipeline | Components are replaceable, testable, and independently scalable | Needs explicit contracts and a state store | **Selected** |
| Free-form agent orchestration | Flexible exploration | Low determinism and weak auditability | Use only inside the extraction component, if needed |

### Logical flow

\`\`\`mermaid
flowchart LR
  A["URL / RSS subscription"] --> B["Discovery"]
  B --> C["Fetcher"]
  C --> D["Normalizer"]
  D --> E["Evidence Store"]
  E --> F["LLM Extractor"]
  F --> G["Concept Resolver"]
  G --> H["Obsidian Publisher"]
  H --> I["Obsidian vault"]
  B --> J["Run journal / state store"]
  C --> J
  F --> J
  H --> J
\`\`\`

## 5. Components

| Component | Input | Output | Responsibility |
| --- | --- | --- | --- |
| Source registry | User URL or feed configuration | \`SourceRegistered\` | Stores source policy, schedule, and crawl state |
| Discovery adapter | URL or RSS/Atom response | \`DocumentDiscovered\` | Finds candidate article links and deduplicates feed entries |
| Fetcher | Candidate URL | \`DocumentFetched\` | Fetches safely, enforces robots and rate limits, records HTTP metadata |
| Normalizer | Raw response | \`DocumentNormalized\` | Extracts readable article content, title, date, canonical URL, and content hash |
| Evidence store | Normalized document | \`EvidenceStored\` | Retains source material and stable evidence fragments |
| Knowledge extractor | Document plus evidence | \`KnowledgeExtracted\` | Uses an LLM to emit concepts, relations, summaries, and evidence bindings |
| Concept resolver | Extracted knowledge plus existing graph | \`ConceptUpsertRequested\` | Resolves duplicates, creates links, and decides whether concepts changed |
| Obsidian publisher | Source and concept documents | \`PublicationCompleted\` | Writes vault files atomically and protects human content |
| Run journal | Events from all components | Queryable run record | Provides retries, auditability, checkpoints, and observability |

Each component may be deployed as a process, container, serverless function, or local command. An adapter translates its transport (HTTP, queue, local JSONL, or CLI stdout) into the common event envelope.

## 6. Interchange contracts

### 6.1 Common event envelope

All inter-component messages use a versioned JSON document:

\`\`\`json
{
  "schema_version": "1.0",
  "event_id": "uuid",
  "trace_id": "uuid",
  "occurred_at": "2026-08-03T12:00:00Z",
  "producer": "fetcher/1.0",
  "type": "DocumentNormalized",
  "payload": {}
}
\`\`\`

\`event_id\` is unique, while \`trace_id\` connects one crawl run across all components. Consumers must ignore duplicate \`event_id\` values and process a message idempotently.

### 6.2 Essential payloads

\`DocumentDiscovered\` contains a source identifier, discovered URL, feed entry identifier when available, canonical URL hint, and discovery timestamp.

\`DocumentNormalized\` contains a stable document identifier, canonical URL, title, publication date if known, cleaned Markdown or structured text, content hash, language, and HTTP provenance.

\`KnowledgeExtracted\` contains a schema-validated list of concepts and relations. Every fact includes an evidence reference:

\`\`\`json
{
  "claim": "Example conclusion",
  "confidence": 0.86,
  "evidence": {
    "document_id": "doc:...",
    "start": 120,
    "end": 260,
    "quote": "Short supporting excerpt"
  }
}
\`\`\`

The exact JSON Schemas are implementation artifacts, but must be published with semantic versions. Compatibility is defined by these schemas, not by a shared class library.

## 7. Data model and Obsidian representation

### 7.1 Vault layout

\`\`\`text
Vault/
  Sources/
    <domain>/
      <year>/
        <source-id>.md
  Concepts/
    <type>/
      <concept-slug>.md
  Reports/
    crawl-runs/
      <run-id>.md
  .crawler/
    manifest.json
    checkpoints.json
\`\`\`

Source notes retain provenance and a compact source summary. Concept notes aggregate statements from one or more source notes and express relations using Obsidian wiki links.

### 7.2 Concept note format

\`\`\`markdown
---
id: concept:technology:ai-infrastructure
type: Technology
title: AI Infrastructure
aliases: [AI 基础设施]
tags: [technology, ai]
status: active
sources:
  - source_id: source:example
    url: https://example.com/article
    captured_at: 2026-08-03T12:00:00Z
confidence: 0.86
managed_by: web-knowledge-pipeline
---

# 摘要

<!-- AGENT:BEGIN summary -->
System-generated, evidence-backed content.
<!-- AGENT:END summary -->

# 证据与来源

- [[Sources/example.com/2026/source-example|原始文章]]

# 人工笔记

This section is never overwritten by the pipeline.
\`\`\`

The publisher owns only fields explicitly declared as managed and the content inside \`AGENT:BEGIN\` / \`AGENT:END\` markers. All other frontmatter and content belongs to the user.

## 8. Crawl and synchronization behavior

### 8.1 Manual URLs

A submitted URL enters the pipeline as \`DocumentDiscovered\`. It shares the fetch, normalization, extraction, resolution, and publication path with feed items.

### 8.2 RSS and Atom feeds

An RSS adapter polls each subscription on its configured schedule. It uses \`ETag\` and \`Last-Modified\` conditional requests where available. It identifies entries by this priority:

1. Feed \`guid\` or Atom \`id\`.
2. Canonical article URL.
3. Normalized article content hash.

The supplied Omdia feed is an example of such a discovery source. Its article URLs are processed individually; the architecture does not depend on any Omdia-specific parsing beyond a feed adapter configuration.

### 8.3 Incremental updates

- If the normalized content hash is unchanged, downstream extraction is skipped.
- If content changes, the system computes a document diff and extracts knowledge again.
- The resolver updates only affected concepts and relations.
- A source that becomes unavailable is marked \`stale\`; existing notes are not deleted automatically.
- Every publication records input hashes and the previous output version, making rollback possible.

## 9. LLM extraction rules

The LLM is a replaceable implementation behind the \`KnowledgeExtractor\` contract. It must return structured, schema-valid output, not free-form text.

Rules:

- Treat all fetched content as untrusted data, never as system instructions.
- Require evidence bindings for every generated factual statement.
- Reject or quarantine output without valid evidence spans.
- Use deterministic validation for URLs, dates, duplicate identifiers, and internal links before publication.
- Publish source notes when extraction fails, but do not update concept notes with invalid or low-confidence extracted claims.
- Record model identifier, prompt version, and extraction timestamp in the run journal.

## 10. Publishing and conflict policy

The system publishes directly to the production vault, but it does so safely:

1. Render output outside the vault.
2. Validate frontmatter, links, and managed markers.
3. Read the existing file, preserve user-owned content, and replace only managed blocks.
4. Write a temporary file on the same filesystem and atomically replace the target.
5. Update the publication manifest only after the file write succeeds.

If a managed block has been manually edited, the publisher records a conflict in the run report and uses the configured policy: preserve user changes and leave the old generated block intact until a human resolves it. It never silently overwrites user-owned text.

## 11. Safety, compliance, and content retention

- Allow only \`http\` and \`https\` URLs.
- Block localhost, loopback, private, link-local, and cloud metadata IP ranges; repeat the check after every redirect to prevent SSRF.
- Respect robots.txt, per-domain concurrency, rate limits, maximum body size, maximum link depth, and maximum pages per run.
- Store credentials only in deployment secrets; never publish them to the vault or log them in events.
- By default, publish metadata, short attributable excerpts, and summaries—not a full article copy. Keep cleaned full text only in a private evidence store if the source terms and retention policy permit it.

## 12. Failure handling

| Failure | Behavior |
| --- | --- |
| Temporary network or 5xx error | Retry with bounded exponential backoff; then record failure |
| 4xx, robots denial, or policy denial | Do not retry automatically; report source status |
| Parse failure | Publish an error status to the run journal; retain raw response only if permitted |
| LLM timeout or schema failure | Retry a bounded number of times; publish source note only if evidence is valid |
| Publication failure | Do not update checkpoint; retry idempotently from the last successful event |
| User edit conflict | Preserve user text and emit a conflict report |

## 13. Verification strategy

- **Contract tests:** every component validates its emitted and consumed JSON Schemas.
- **Fixture tests:** deterministic HTML, RSS, malformed feed, redirect, and robots fixtures.
- **Golden-file tests:** fixed normalized text and Obsidian Markdown output.
- **Idempotency tests:** running the same event twice produces no duplicate note or relation.
- **Update tests:** a source change updates only the relevant managed blocks.
- **Conflict tests:** manual sections remain byte-for-byte unchanged after a sync.
- **Security tests:** attempted private-network URLs, redirect chains, oversized payloads, and prompt-injection text are rejected or contained.
- **End-to-end tests:** a feed item produces a source note, linked concept notes, and a complete run report.

## 14. Acceptance criteria

1. A new RSS item produces a source note and evidence-backed, linked concept notes in one scheduled run.
2. Reprocessing an unchanged URL does not create duplicate files, links, or LLM work.
3. A changed page updates only relevant auto-generated content.
4. Human-authored text persists across every synchronization.
5. Replacing any one component with another-language implementation succeeds when it passes the published contract tests.
6. Every published factual concept claim can be traced to a source URL and a captured evidence fragment.
