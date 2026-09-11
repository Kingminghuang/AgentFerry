#!/usr/bin/env python3
"""Export a Codex legacy rollout JSONL file to a session OKF bundle.

The exporter deliberately treats the JSONL append order as canonical. Timestamps
are metadata only and are never used to sort records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


TOOL_CALL_TYPES = {
    "function_call",
    "custom_tool_call",
    "local_shell_call",
    "tool_search_call",
    "web_search_call",
    "image_generation_call",
}
TOOL_RESULT_TYPES = {"function_call_output", "custom_tool_call_output", "tool_search_output"}
MESSAGE_KINDS = {"user_message", "assistant_message"}
VALID_STATUSES = {"completed", "incomplete", "unknown"}
PRODUCER = "agentferry-session-producer/1.1"
CHUNK_BYTES = 32 * 1024
INJECTED_CONTEXT_PREFIXES = (
    "<environment_context>",
    "<recommended_plugins>",
    "<app-context>",
    "<skills_instructions>",
    "<permissions instructions>",
    "<collaboration_mode>",
    "<apps_instructions>",
    "<plugins_instructions>",
    "<model_switch>",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, sequence: int, record_hash: str) -> str:
    return f"{prefix}-{sequence:06d}-{record_hash.split(':', 1)[-1][:12]}"


def safe_heading(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_.:-]+", "-", value).strip("-")
    return value or "unknown"


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_mapping(mapping: dict[str, Any], indent: int = 0) -> list[str]:
    lines: list[str] = []
    padding = " " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            lines.append(f"{padding}{key}:")
            lines.extend(yaml_mapping(value, indent + 2))
        elif isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            lines.append(f"{padding}{key}:")
            for item in value:
                first_key, first_value = next(iter(item.items()))
                if isinstance(first_value, (dict, list)):
                    lines.append(f"{padding}  - {first_key}:")
                    if isinstance(first_value, dict):
                        lines.extend(yaml_mapping(first_value, indent + 6))
                    else:
                        lines.append(f"{padding}      {yaml_scalar(first_value)}")
                else:
                    lines.append(f"{padding}  - {first_key}: {yaml_scalar(first_value)}")
                remaining = dict(list(item.items())[1:])
                lines.extend(yaml_mapping(remaining, indent + 4))
        elif isinstance(value, list):
            lines.append(f"{padding}{key}: [{', '.join(yaml_scalar(item) for item in value)}]")
        else:
            lines.append(f"{padding}{key}: {yaml_scalar(value)}")
    return lines


def make_frontmatter(fields: dict[str, Any]) -> str:
    return "---\n" + "\n".join(yaml_mapping(fields)) + "\n---\n"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"blank JSONL line at {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL line at {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            rows.append(value)
    return rows


def _session_id(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("type") == "session_meta":
            payload = row.get("payload") or {}
            value = payload.get("session_id") or payload.get("id")
            if value:
                return str(value)
    raise ValueError("rollout contains no session_meta.session_id or session_meta.id")


def _turn_key(payload: dict[str, Any], sequence: int, record_key: str) -> str | None:
    passthrough = payload.get("internal_chat_message_metadata_passthrough")
    value = payload.get("turn_id")
    if value is None and isinstance(passthrough, dict):
        value = passthrough.get("turn_id")
    return str(value) if value else None


def _message_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                chunks.append(block["text"])
            elif isinstance(block, dict):
                chunks.append(pretty_json(block))
            else:
                chunks.append(str(block))
        return "\n".join(chunks)
    for key in ("message", "text", "raw_content", "rawContent", "content"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _status(payload: dict[str, Any], default: str = "unknown") -> str:
    value = payload.get("status")
    return value if value in VALID_STATUSES else default


def _is_injected_context(payload: dict[str, Any], content_text: str) -> bool:
    """Identify provider runtime messages that are not authored by the end user."""

    if payload.get("role") in {"developer", "system"}:
        return True
    return content_text.lstrip().startswith(INJECTED_CONTEXT_PREFIXES)


def _kind_for_row(row: dict[str, Any], sequence: int, record_key: str) -> tuple[str, str | None, str, str]:
    outer_type = str(row.get("type", "unknown"))
    payload = row.get("payload")
    payload = payload if isinstance(payload, dict) else {"value": payload}
    payload_type = payload.get("type")
    subtype = str(payload_type or outer_type)
    turn_key = _turn_key(payload, sequence, record_key)
    content_text = _message_text(payload)

    if outer_type == "session_meta":
        return "system_context", None, "session_metadata", content_text
    if outer_type in {"turn_context", "world_state"}:
        return "system_context", str(payload.get("turn_id")) if payload.get("turn_id") else None, subtype, content_text
    if outer_type == "inter_agent_communication_metadata":
        return "lifecycle", None, subtype, content_text
    if outer_type == "compacted":
        return "compacted", None, subtype, content_text
    if outer_type == "event_msg":
        if payload_type == "user_message":
            return "user_message", turn_key, subtype, content_text
        if payload_type == "agent_message":
            return "assistant_message", turn_key, subtype, content_text
        if payload_type in {"agent_reasoning", "agent_reasoning_raw_content"}:
            return "reasoning", turn_key, subtype, content_text
        return "lifecycle", turn_key if payload.get("turn_id") else None, subtype, content_text
    if outer_type == "response_item":
        if payload_type == "message" and _is_injected_context(payload, content_text):
            return "system_context", turn_key, "injected_context", content_text
        if payload_type == "message" and payload.get("role") == "user":
            return "user_message", turn_key, subtype, content_text
        if payload_type in {"message", "agent_message"} and payload.get("role") == "assistant" or payload_type == "agent_message":
            return "assistant_message", turn_key, subtype, content_text
        if payload_type == "reasoning":
            return "reasoning", turn_key, subtype, content_text
        if payload_type in TOOL_CALL_TYPES:
            return "tool_call", turn_key if payload.get("turn_id") else None, subtype, content_text
        if payload_type in TOOL_RESULT_TYPES:
            return "tool_result", turn_key if payload.get("turn_id") else None, subtype, content_text
        if payload_type in {"compaction", "context_compaction"}:
            return "compaction", turn_key if payload.get("turn_id") else None, subtype, content_text
        return "unknown", turn_key if payload.get("turn_id") else None, subtype, content_text
    return "unknown", None, subtype, content_text


def normalize_rollout(rows: list[dict[str, Any]], provider: str = "codex") -> list[dict[str, Any]]:
    """Project rows into normalized records without changing their input order."""

    session_id = _session_id(rows)
    records: list[dict[str, Any]] = []
    for sequence, row in enumerate(rows, 1):
        record_hash = "sha256:" + sha256_text(canonical_json(row))
        record_key = f"{provider}:{session_id}:{sequence}:{record_hash}"
        raw_ref = f"ev:{provider}:{session_id}:{sequence}:{record_hash}"
        payload = row.get("payload")
        payload = payload if isinstance(payload, dict) else {"value": payload}
        kind, turn_key, subtype, content_text = _kind_for_row(row, sequence, record_key)
        call_id = payload.get("call_id")
        if kind in {"tool_call", "tool_result"} and not call_id:
            call_id = payload.get("id") or record_key
        default_status = "completed" if kind in MESSAGE_KINDS else "unknown"
        if kind == "tool_result":
            default_status = "completed"
        records.append(
            {
                "provider": provider,
                "session_id": session_id,
                "record_key": record_key,
                "record_hash": record_hash,
                "sequence": sequence,
                "occurred_at": row.get("timestamp"),
                "kind": kind,
                "subtype": subtype,
                "turn_key": turn_key,
                "call_id": str(call_id) if call_id else None,
                "status": _status(payload, default_status),
                "content_text": content_text,
                "content": payload.get("content"),
                "payload": payload,
                "raw": row,
                "raw_evidence_refs": [raw_ref],
                "source_sequences": [sequence],
            }
        )

    deduped: list[dict[str, Any]] = []
    mirrors: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    adjacent_mirrors: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if record["kind"] in MESSAGE_KINDS | {"reasoning"}:
            dedupe_text = record["content_text"] or canonical_json(record["payload"])
            key = (record["kind"], record["turn_key"], dedupe_text)
            existing = mirrors.get(key)
            if existing is None:
                adjacent = adjacent_mirrors.get((record["kind"], dedupe_text))
                if adjacent and record["sequence"] - adjacent["source_sequences"][-1] <= 1:
                    if adjacent["turn_key"] in {None, record["turn_key"]} or record["turn_key"] is None:
                        existing = adjacent
            if existing is not None:
                existing["raw_evidence_refs"].extend(record["raw_evidence_refs"])
                existing["source_sequences"].extend(record["source_sequences"])
                if existing["turn_key"] is None and record["turn_key"] is not None:
                    existing["turn_key"] = record["turn_key"]
                continue
            mirrors[key] = record
            adjacent_mirrors[(record["kind"], dedupe_text)] = record
        deduped.append(record)
    return deduped


def _range_for(records: Iterable[dict[str, Any]], total_lines: int) -> list[int | None]:
    sequences = [record["sequence"] for record in records]
    return [min(sequences), max(sequences)] if sequences else [1, total_lines]


def _fence(text: str, language: str = "text") -> list[str]:
    marker = "~~~~" if "~~~" in text else "~~~"
    return [f"{marker}{language}", text, marker]


def _raw_refs(record: dict[str, Any]) -> str:
    return ", ".join(f"`{ref}`" for ref in record["raw_evidence_refs"])


def _record_anchor(record: dict[str, Any], prefix: str) -> str:
    return stable_id(prefix, record["sequence"], record["record_hash"])


def _details(summary: str, content: list[str]) -> list[str]:
    return ["<details>", f"<summary>{summary}</summary>", "", *content, "", "</details>", ""]


def _evidence_lines(record: dict[str, Any]) -> list[str]:
    return [
        f"- 原始 JSONL 行：{_raw_refs(record)}",
        f"- 记录序号：{record['sequence']}",
    ]


def _display_turn(record: dict[str, Any]) -> str:
    return record["turn_key"] or "会话级"


def _tool_name(record: dict[str, Any]) -> str:
    payload = record["payload"]
    return str(payload.get("name") or payload.get("action") or payload.get("type") or "unknown-tool")


def _tool_category(name: str) -> str:
    lowered = name.lower()
    if "search" in lowered:
        return "搜索"
    if "exec" in lowered or "shell" in lowered or "command" in lowered:
        return "命令执行"
    if "github" in lowered:
        return "GitHub"
    if "image" in lowered:
        return "图像"
    return "工具调用"


def _split_utf8(text: str, limit: int = CHUNK_BYTES) -> list[str]:
    """Split text without cutting a UTF-8 code point, preserving byte-exact joins."""

    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for char in text:
        char_size = len(char.encode("utf-8"))
        if current and current_size + char_size > limit:
            chunks.append("".join(current))
            current = []
            current_size = 0
        current.append(char)
        current_size += char_size
    if current or not chunks:
        chunks.append("".join(current))
    return chunks


@dataclass
class AttachmentChunk:
    filename: str
    anchor: str
    record: dict[str, Any]
    content: str
    content_hash: str
    total_bytes: int
    mime_type: str
    index: int
    count: int


class AttachmentStore:
    def __init__(self) -> None:
        self.chunks: list[AttachmentChunk] = []

    def reference(self, record: dict[str, Any], label: str, content: str, mime_type: str) -> list[str] | None:
        total_bytes = len(content.encode("utf-8"))
        if total_bytes <= CHUNK_BYTES:
            return None
        content_hash = "sha256:" + sha256_text(content)
        pieces = _split_utf8(content)
        base = f"{_record_anchor(record, 'chunk')}-{safe_heading(label)}"
        links: list[str] = []
        for index, piece in enumerate(pieces, 1):
            filename = f"{base}-{index:03d}.md"
            anchor = f"chunk-{safe_heading(base)}-{index:03d}"
            self.chunks.append(
                AttachmentChunk(
                    filename=filename,
                    anchor=anchor,
                    record=record,
                    content=piece,
                    content_hash=content_hash,
                    total_bytes=total_bytes,
                    mime_type=mime_type,
                    index=index,
                    count=len(pieces),
                )
            )
            links.append(f"[附件分片 {index}](assets/{filename})")
        return [
            f"完整内容（{total_bytes} bytes，{mime_type}，`{content_hash}`）：" + "；".join(links),
            f"原始 JSONL 行：{_raw_refs(record)}",
        ]


def _render_large_value(
    record: dict[str, Any],
    label: str,
    value: Any,
    attachments: AttachmentStore,
    *,
    language: str = "text",
) -> list[str]:
    text = value if isinstance(value, str) else pretty_json(value)
    mime_type = "text/plain" if isinstance(value, str) else "application/json"
    reference = attachments.reference(record, label, text, mime_type)
    return reference if reference is not None else _fence(text, language)


def _body_hash(body: str) -> str:
    return "sha256:" + sha256_text(body)


def _version_id(role: str, content_hash: str) -> str:
    return f"docv:{role}:{content_hash.split(':', 1)[-1][:16]}"


def _common_fields(
    *,
    role: str,
    type_name: str,
    kind: str,
    title: str,
    description: str,
    provider: str,
    session_id: str,
    body: str,
    captured_at: str | None,
    line_range: list[int | None],
    canonical_version: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content_hash = _body_hash(body)
    fields: dict[str, Any] = {
        "id": f"source:session:{provider}:{session_id}:{role}",
        "type": type_name,
        "kind": kind,
        "title": title,
        "description": description,
        "resource": f"evidence://{provider}/{session_id}",
        "source_file_ref": f"evidence://{provider}/{session_id}",
        "provider": provider,
        "session_id": session_id,
        "document_version_id": _version_id(role, content_hash),
        "content_hash": content_hash,
        "captured_at": captured_at,
        "line_range": line_range,
        "status": "stable",
        "generated": {"by": PRODUCER, "at": captured_at},
        "sources": [
            {
                "id": "session-jsonl",
                "resource": f"evidence://{provider}/{session_id}",
                "title": f"{provider} session JSONL",
                "document_version_id": canonical_version,
            }
        ],
        "managed_by": "web-knowledge-pipeline",
    }
    if extra:
        insertion = list(fields.items())
        fields = dict(insertion[:14] + list(extra.items()) + insertion[14:])
    return fields


def _message_block(record: dict[str, Any], role_label: str) -> list[str]:
    anchor = _record_anchor(record, "msg")
    lines = [f"### {role_label} ^{anchor}", "", record["content_text"], ""]
    lines.extend(_details("来源与原始记录", _evidence_lines(record)))
    return lines


def _summary(messages: list[dict[str, Any]]) -> str:
    for record in messages:
        if record["kind"] == "user_message" and record["content_text"].strip():
            text = " ".join(record["content_text"].strip().split())
            if text.startswith("<recommended_plugins>") or text.startswith("<environment_context>"):
                continue
            return text if len(text) <= 220 else text[:217] + "..."
    return "该会话没有可展示的用户消息。"


def _turn_anchor(turn_key: str) -> str:
    return "turn-" + sha256_text(turn_key)[:16]


def _tool_groups(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for record in records:
        if record["kind"] == "tool_call":
            current.append(record)
            continue
        if current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _activity_block(calls: list[dict[str, Any]], completed_call_ids: set[str]) -> list[str]:
    labels = ", ".join(dict.fromkeys(_tool_category(_tool_name(call)) for call in calls))
    completed = sum(
        1
        for call in calls
        if call["status"] == "completed" or (call["call_id"] or call["record_key"]) in completed_call_ids
    )
    incomplete = len(calls) - completed
    links = []
    for call in calls:
        call_id = call["call_id"] or call["record_key"]
        links.append(f"[{_tool_name(call)}](tools.md#^tool-{safe_heading(call_id)})")
    state = f"完成 {completed}" + (f"；未完成 {incomplete}" if incomplete else "")
    return [
        f"> [!note]- 工具活动 · {labels}（{len(calls)} 项）",
        f"> {state}；{'、'.join(links)}",
        "",
    ]


def build_session_body(records: list[dict[str, Any]], title: str) -> str:
    messages = [record for record in records if record["kind"] in MESSAGE_KINDS]
    system_records = [record for record in records if record["kind"] == "system_context"]
    reasoning_records = [record for record in records if record["kind"] == "reasoning"]
    tool_calls = [record for record in records if record["kind"] == "tool_call"]
    completed_call_ids = {
        record["call_id"] or record["record_key"]
        for record in records
        if record["kind"] == "tool_result"
    }
    injected = [record for record in system_records if record["subtype"] == "injected_context"]
    turns: dict[str, list[dict[str, Any]]] = {}
    turn_order: list[str] = []
    message_turn_keys = {
        record["turn_key"] or f"message-{record['sequence']}"
        for record in messages
    }
    current_turn: str | None = None
    for record in [record for record in records if record["kind"] in MESSAGE_KINDS | {"tool_call"}]:
        if record["kind"] in MESSAGE_KINDS:
            key = record["turn_key"] or f"message-{record['sequence']}"
            current_turn = key
        else:
            key = record["turn_key"] if record["turn_key"] in message_turn_keys else current_turn
            key = key or "会话准备"
        if key not in turns:
            turns[key] = []
            turn_order.append(key)
        turns[key].append(record)

    lines = [
        "# 会话概览",
        "",
        "## 阅读卡片",
        "",
        f"- 真实 Turn：{len(message_turn_keys)}",
        f"- 用户消息：{sum(record['kind'] == 'user_message' for record in messages)}",
        f"- 助手消息：{sum(record['kind'] == 'assistant_message' for record in messages)}",
        f"- 工具调用：{len(tool_calls)}",
        f"- 推理记录：{len(reasoning_records)}",
        "- 导航：[推理](reasoning.md) · [运行上下文](system.md) · [工具](tools.md) · [事件](events.md)",
        "",
        "<!-- AGENT:BEGIN session-summary -->",
        f"{_summary(messages)}[^session-jsonl]",
        "<!-- AGENT:END session-summary -->",
        "",
        "# 完整会话",
        "",
        "会话开端上下文：",
    ]
    if system_records:
        metadata = next((record for record in system_records if record["subtype"] == "session_metadata"), None)
        if metadata:
            lines.append(f"- [会话元数据](system.md#^context-{_record_anchor(metadata, 'context')})")
        base = next(
            (
                record
                for record in system_records
                if record["subtype"] == "session_metadata" and record["payload"].get("base_instructions")
            ),
            None,
        )
        if base:
            base_id = "context-base-instructions-" + sha256_text(canonical_json(base["payload"].get("base_instructions")))[:16]
            lines.append(f"- [系统提示](system.md#^{base_id})")
    lines.append("")
    if injected:
        lines.extend(
            _details(
                f"运行时注入上下文已移至 system.md（{len(injected)} 条）",
                ["这些记录不是终端用户消息。", "", "[查看完整运行时注入上下文](system.md#注入上下文)"],
            )
        )

    for turn_key in turn_order:
        turn_records = turns[turn_key]
        heading = "## 会话准备" if turn_key == "会话准备" else f"## Turn {turn_key} ^{_turn_anchor(turn_key)}"
        lines.extend([heading, ""])
        current_calls: list[dict[str, Any]] = []
        for record in turn_records:
            if record["kind"] == "tool_call":
                current_calls.append(record)
                continue
            if current_calls:
                lines.extend(_activity_block(current_calls, completed_call_ids))
                current_calls = []
            lines.extend(_message_block(record, "用户" if record["kind"] == "user_message" else "助手"))
        if current_calls:
            lines.extend(_activity_block(current_calls, completed_call_ids))
        related: list[str] = []
        related_records = [
            record
            for record in records
            if record["turn_key"] == turn_key and record["kind"] in {"reasoning", "tool_call", "system_context"}
        ]
        for record in related_records:
            if record["kind"] == "reasoning":
                related.append(f"- [本轮推理](reasoning.md#^{_record_anchor(record, 'reasoning')})")
            elif record["kind"] == "system_context":
                related.append(f"- [本轮运行上下文](system.md#^{_record_anchor(record, 'context')})")
        if related:
            lines.extend(["关联记录：", *dict.fromkeys(related), ""])

    lines.extend(
        [
            "# 提取出的概念",
            "<!-- AGENT:BEGIN extracted-concepts -->",
            "<!-- AGENT:END extracted-concepts -->",
            "",
            "# 人工笔记",
            "",
            "[^session-jsonl]: codex session JSONL",
            "",
        ]
    )
    return "\n".join(lines)


def _context_record_block(record: dict[str, Any], attachments: AttachmentStore) -> list[str]:
    anchor = _record_anchor(record, "context")
    lines = [f"### {record['subtype']} ^{anchor}", ""]
    lines.extend(
        [
            f"- 关联 Turn：{record['turn_key'] or 'null'}",
            f"- 时间：{record['occurred_at'] or 'null'}",
            "- 来源角色：system_context",
            "",
        ]
    )
    details = [*_evidence_lines(record), "", *_render_large_value(record, "context", record["payload"], attachments, language="json")]
    lines.extend(_details("完整原始上下文", details))
    return lines


def build_system_body(records: list[dict[str, Any]], attachments: AttachmentStore) -> str:
    injected_records = [record for record in records if record["subtype"] == "injected_context"]
    session_records = [record for record in records if record["turn_key"] is None and record not in injected_records]
    turn_records = [record for record in records if record["turn_key"] is not None and record not in injected_records]
    lines = ["# 运行上下文", "", "> 返回主会话：[session.md](session.md)", "", "## 概览", "", f"- 会话级记录：{len(session_records)}", f"- 运行时注入记录：{len(injected_records)}", f"- Turn 级记录：{len(turn_records)}", ""]
    lines.extend(["## 会话级上下文", ""])
    seen_base: set[str] = set()
    for record in session_records:
        lines.extend(_context_record_block(record, attachments))
        base = record["payload"].get("base_instructions")
        if record["subtype"] == "session_metadata" and base:
            base_hash = sha256_text(canonical_json(base))
            if base_hash in seen_base:
                continue
            seen_base.add(base_hash)
            base_id = f"context-base-instructions-{base_hash[:16]}"
            lines.extend(
                [
                    f"### base_instructions ^{base_id}",
                    "",
                    "- 关联 Turn：null",
                    f"- 时间：{record['occurred_at'] or 'null'}",
                    "- 来源角色：system_context",
                    "",
                ]
            )
            lines.extend(_details("完整系统提示", [*_evidence_lines(record), "", *_render_large_value(record, "base-instructions", base, attachments, language="json")]))
    if injected_records:
        lines.extend(["## 注入上下文 ^注入上下文", ""])
        for record in injected_records:
            lines.extend(_context_record_block(record, attachments))
    for turn_key in dict.fromkeys(record["turn_key"] for record in turn_records):
        lines.extend([f"## Turn {turn_key}", ""])
        for record in turn_records:
            if record["turn_key"] == turn_key:
                lines.extend(_context_record_block(record, attachments))
    return "\n".join(lines)


def build_reasoning_body(records: list[dict[str, Any]]) -> str:
    lines = ["# 推理", "", "> 返回主会话：[session.md](session.md)", "", "## 概览", "", f"- 推理记录：{len(records)}", ""]
    by_turn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_turn[_display_turn(record)].append(record)
    for turn_key, turn_records in by_turn.items():
        lines.extend([f"## Turn {turn_key}", ""])
        for record in turn_records:
            lines.extend(
                [
                    f"### 推理记录 ^{_record_anchor(record, 'reasoning')}",
                    "",
                    f"- 时间：{record['occurred_at'] or 'null'}",
                    "- 来源角色：reasoning",
                    "",
                ]
            )
            if record["content_text"]:
                lines.extend([record["content_text"], ""])
            lines.extend(_details("完整原始记录", [*_evidence_lines(record), "", *_fence(pretty_json(record["payload"]), "json")]))
    return "\n".join(lines)


def _tool_entries(records: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    calls = [record for record in records if record["kind"] == "tool_call"]
    results_by_call: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["kind"] == "tool_result":
            results_by_call[record["call_id"] or ""].append(record)
    entries: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    used_result_ids: set[int] = set()
    for call in calls:
        call_id = call["call_id"] or call["record_key"]
        results = results_by_call.get(call_id, [])
        used_result_ids.update(id(result) for result in results)
        entries.append((call, results))
    for result in records:
        if result["kind"] == "tool_result" and id(result) not in used_result_ids:
            entries.append((result, [result]))
    return entries


def build_tools_body(records: list[dict[str, Any]], attachments: AttachmentStore) -> str:
    entries = _tool_entries(records)
    completed = sum(1 for call, results in entries if call["kind"] == "tool_call" and results)
    lines = ["# 工具", "", "> 返回主会话：[session.md](session.md)", "", "## 概览", "", f"- 工具记录：{len(entries)}", f"- 已配对：{completed}", f"- 未完成或未知：{len(entries) - completed}", ""]
    by_turn: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]] = defaultdict(list)
    for entry in entries:
        by_turn[_display_turn(entry[0])].append(entry)
    for turn_key, turn_entries in by_turn.items():
        lines.extend([f"## Turn {turn_key}", ""])
        for call, results in turn_entries:
            call_id = call["call_id"] or call["record_key"]
            status = "completed" if results and call["kind"] == "tool_call" else ("incomplete" if call["kind"] == "tool_call" else "unknown")
            lines.extend(
                [
                    f"### {_tool_name(call)} ^tool-{safe_heading(call_id)}",
                    "",
                    f"- 类别：{_tool_category(_tool_name(call))}",
                    f"- Call ID：`{call_id}`",
                    f"- 状态：{status}",
                    f"- 时间：{call['occurred_at'] or 'null'}",
                    "",
                ]
            )
            raw_args, parsed_args = _tool_arguments(call["payload"])
            details: list[str] = [*_evidence_lines(call), "", "#### 原始参数", "", *_fence(raw_args), "", "#### 解析参数", "", *_fence(pretty_json(parsed_args), "json"), "", "#### 结果", ""]
            if not results:
                details.append("（未发现对应的工具结果。）")
            for result in results:
                details.extend(_evidence_lines(result))
                details.extend(_render_large_value(result, "tool-result", _result_value(result), attachments, language="json" if not isinstance(_result_value(result), str) else "text"))
                details.append("")
            lines.extend(_details("原始参数、结果与来源", details))
    return "\n".join(lines)


def build_events_body(records: list[dict[str, Any]], attachments: AttachmentStore) -> str:
    lines = ["# 事件", "", "> 返回主会话：[session.md](session.md)", "", "## 概览", "", f"- 事件记录：{len(records)}", "", "## 时间线", "", "| 序号 | 类型 | 关联键 | 时间 |", "| ---: | --- | --- | --- |"]
    for record in records:
        key = record["turn_key"] or record["call_id"] or "null"
        lines.append(f"| {record['sequence']} | {record['subtype']} | {key} | {record['occurred_at'] or 'null'} |")
    lines.extend(["", "## 完整记录", ""])
    for record in records:
        lines.extend(
            [
                f"### {record['subtype']} ^{_record_anchor(record, 'event')}",
                "",
                f"- 序号：{record['sequence']}",
                f"- 关联键：{record['turn_key'] or record['call_id'] or 'null'}",
                f"- 时间：{record['occurred_at'] or 'null'}",
                "",
            ]
        )
        lines.extend(_details("完整原始事件", [*_evidence_lines(record), "", *_render_large_value(record, "event", record["raw"], attachments, language="json")]))
    return "\n".join(lines)


def _tool_arguments(payload: dict[str, Any]) -> tuple[str, Any]:
    for key in ("arguments", "input", "action", "execution"):
        if key in payload:
            value = payload[key]
            raw = value if isinstance(value, str) else pretty_json(value)
            try:
                parsed = json.loads(value) if isinstance(value, str) else value
            except json.JSONDecodeError:
                parsed = None
            return raw, parsed
    return "", None


def _result_value(record: dict[str, Any]) -> Any:
    payload = record["payload"]
    for key in ("output", "result", "tools"):
        if key in payload:
            return payload[key]
    return payload


def _doc_fields(
    *,
    role: str,
    type_name: str,
    kind: str,
    title: str,
    description: str,
    provider: str,
    session_id: str,
    body: str,
    captured_at: str | None,
    records: list[dict[str, Any]],
    total_lines: int,
    canonical_version: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _common_fields(
        role=role,
        type_name=type_name,
        kind=kind,
        title=title,
        description=description,
        provider=provider,
        session_id=session_id,
        body=body,
        captured_at=captured_at,
        line_range=_range_for(records, total_lines),
        canonical_version=canonical_version,
        extra=extra,
    )


def write_concept(path: Path, fields: dict[str, Any], body: str) -> None:
    path.write_text(make_frontmatter(fields) + "\n" + body, encoding="utf-8", newline="\n")


def _write_text_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8", newline="\n")


def write_attachment_chunks(
    bundle: Path,
    attachments: AttachmentStore,
    *,
    title: str,
    provider: str,
    session_id: str,
    canonical_version: str,
) -> None:
    asset_dir = bundle / "assets"
    expected_names = {chunk.filename for chunk in attachments.chunks}
    if asset_dir.exists():
        for candidate in asset_dir.glob("*.md"):
            if candidate.name in expected_names:
                continue
            existing = candidate.read_text(encoding="utf-8")
            if 'kind: "agent-session-attachment-chunk"' in existing and 'managed_by: "web-knowledge-pipeline"' in existing:
                candidate.unlink()
    if not attachments.chunks:
        return
    asset_dir.mkdir(exist_ok=True)
    for chunk in attachments.chunks:
        body = "\n".join(
            [
                "# 附件分片",
                "",
                f"- 原记录：`{chunk.record['record_key']}`",
                f"- SHA-256：`{chunk.content_hash}`",
                f"- 字节长度：{chunk.total_bytes}",
                f"- MIME 类型：{chunk.mime_type}",
                f"- 分片：{chunk.index}/{chunk.count}",
                f"- 原始 JSONL 行：{_raw_refs(chunk.record)}",
                "",
                f"## 内容 ^{chunk.anchor}",
                "",
                *_fence(chunk.content),
                "",
            ]
        )
        fields = _common_fields(
            role=f"chunk:{chunk.anchor}",
            type_name="Session Attachment Chunk",
            kind="agent-session-attachment-chunk",
            title=f"{title} — 附件分片 {chunk.index}/{chunk.count}",
            description="会话原始内容的受管分片。",
            provider=provider,
            session_id=session_id,
            body=body,
            captured_at=chunk.record["occurred_at"],
            line_range=[chunk.record["sequence"], chunk.record["sequence"]],
            canonical_version=canonical_version,
        )
        write_concept(asset_dir / chunk.filename, fields, body)


def _first_metadata(records: list[dict[str, Any]]) -> dict[str, Any]:
    return next((record for record in records if record["subtype"] == "session_metadata"), {})


def export_rollout(source: Path, output: Path, *, title: str, provider: str = "codex") -> Path:
    rows = read_jsonl(source)
    records = normalize_rollout(rows, provider=provider)
    session_id = _session_id(rows)
    metadata_record = _first_metadata(records)
    metadata = metadata_record.get("payload", {})
    captured_at = next((row.get("timestamp") for row in reversed(rows) if row.get("timestamp")), None)
    started_at = metadata.get("timestamp") or (rows[0].get("timestamp") if rows else None)
    root = output / "01 Sources" / "Sessions" / provider
    bundle = root / session_id
    bundle.mkdir(parents=True, exist_ok=True)

    messages = [record for record in records if record["kind"] in MESSAGE_KINDS]
    system_records = [record for record in records if record["kind"] == "system_context"]
    reasoning_records = [record for record in records if record["kind"] == "reasoning"]
    tool_records = [record for record in records if record["kind"] in {"tool_call", "tool_result"}]
    event_records = [record for record in records if record["kind"] in {"lifecycle", "unknown", "compaction", "compacted"}]
    attachments = AttachmentStore()

    session_body = build_session_body(records, title)
    session_content_hash = _body_hash(session_body)
    session_version = _version_id("session", session_content_hash)
    session_kind = "subagent" if metadata.get("thread_source") == "subagent" and metadata.get("parent_thread_id") else (
        "root" if metadata.get("thread_source") else "unknown"
    )
    session_extra: dict[str, Any] = {
        "cwd_display": "Workspace/" + str(metadata.get("cwd", "")).rstrip("/").split("/")[-1] if metadata.get("cwd") else "redacted",
        "bundle_files": ["session.md", "reasoning.md", "system.md", "tools.md", "events.md"],
        "started_at": started_at,
        "session_kind": session_kind,
        "ingestion": {
            "schema": "codex-rollout-legacy",
            "reasoning_included": True,
            "system_context_included": True,
            "raw_tool_output_included": True,
        },
    }
    if session_kind == "subagent":
        parent_id = str(metadata["parent_thread_id"])
        session_extra["parent_session"] = {
            "provider": provider,
            "session_id": parent_id,
            "relation_id": f"rel:{provider}:{parent_id}:{provider}:{session_id}",
            "raw_evidence_ref": metadata_record["raw_evidence_refs"][0],
        }
    session_extra["status"] = "stable"
    session_fields = _doc_fields(
        role="session",
        type_name="Agent Session",
        kind="agent-session",
        title=title,
        description="Codex 会话的完整消息、运行上下文与工具证据。",
        provider=provider,
        session_id=session_id,
        body=session_body,
        captured_at=captured_at,
        records=records,
        total_lines=len(rows),
        canonical_version=session_version,
        extra=session_extra,
    )
    write_concept(bundle / "session.md", session_fields, session_body)

    attached = [
        ("reasoning", "Session Reasoning", "agent-session-reasoning", "推理", "完整 reasoning 记录。", build_reasoning_body(reasoning_records), reasoning_records, {}),
        ("system", "Session Context", "agent-session-context", "运行上下文", "session metadata、系统提示、turn context 与 world state。", build_system_body(system_records, attachments), system_records, {}),
        ("tools", "Session Tools", "agent-session-tools", "工具", "工具调用、配对结果与原始参数。", build_tools_body(tool_records, attachments), tool_records, {}),
        ("events", "Session Events", "agent-session-events", "事件", "生命周期、多智能体通信、压缩与未知记录。", build_events_body(event_records, attachments), event_records, {}),
    ]
    for role, type_name, kind, label, description, body, role_records, extra in attached:
        fields = _doc_fields(
            role=role,
            type_name=type_name,
            kind=kind,
            title=f"{title} — {label}",
            description=description,
            provider=provider,
            session_id=session_id,
            body=body,
            captured_at=captured_at,
            records=role_records,
            total_lines=len(rows),
            canonical_version=session_version,
            extra=extra,
        )
        write_concept(bundle / f"{role}.md", fields, body)

    write_attachment_chunks(
        bundle,
        attachments,
        title=title,
        provider=provider,
        session_id=session_id,
        canonical_version=session_version,
    )

    index_lines = [
        "# Session Bundle\n\n## Documents\n\n"
        "- [会话](session.md)\n"
        "- [推理](reasoning.md)\n"
        "- [运行上下文](system.md)\n"
        "- [工具](tools.md)\n"
        "- [事件](events.md)\n",
    ]
    if attachments.chunks:
        index_lines.append("\n## Assets\n\n")
        index_lines.extend(f"- [assets/{chunk.filename}](assets/{chunk.filename}) — `{chunk.content_hash}`\n" for chunk in attachments.chunks)
    _write_text_if_changed(bundle / "index.md", "".join(index_lines))
    (bundle / "log.md").write_text(
        "# Directory Update Log\n\n"
        f"## {(captured_at or 'unknown')[:10]}\n\n"
        "- **Creation** — "
        f"at: {captured_at or 'null'}; by: {PRODUCER}; document_version_id: `{session_version}`; "
        "changed: [session.md](session.md), [reasoning.md](reasoning.md), [system.md](system.md), "
        "[tools.md](tools.md), [events.md](events.md); reason: exported Codex rollout JSONL.\n",
        encoding="utf-8",
        newline="\n",
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.md").write_text(
        f"# {provider} Sessions\n\n## Sessions\n\n- [{title}]({session_id}/session.md) — `{session_id}`\n",
        encoding="utf-8",
        newline="\n",
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--provider", default="codex")
    args = parser.parse_args()
    bundle = export_rollout(args.source, args.output, title=args.title, provider=args.provider)
    print(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
