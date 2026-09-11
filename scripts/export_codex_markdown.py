#!/usr/bin/env python3
"""Export Codex Desktop session files as native Markdown.

This is intentionally independent from the OKF bundle exporter in this
repository.  It produces the single-file Markdown format used by the
codex-export skill, without an HTML rendering path or third-party packages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


PROMPT_PREVIEW_LENGTH = 180
LONG_TEXT_THRESHOLD = 300
TOOL_CALL_TYPES = {
    "function_call",
    "custom_tool_call",
    "local_shell_call",
    "tool_search_call",
    "web_search_call",
    "image_generation_call",
}
TOOL_RESULT_TYPES = {
    "function_call_output",
    "custom_tool_call_output",
    "tool_search_output",
}
HIDDEN_MESSAGE_PREFIXES = (
    "<environment_context>",
    "<permissions instructions>",
    "<app-context>",
    "<collaboration_mode>",
    "<apps_instructions>",
    "<skills_instructions>",
    "<plugins_instructions>",
    "<turn_aborted>",
)
MIRRORED_EVENT_TYPES = {
    "agent_message",
    "user_message",
    "token_count",
    "item_completed",
    "thread_settings_applied",
}
COMMIT_PATTERN = re.compile(r"\[[\w\-/]+ ([a-f0-9]{7,})\] (.+?)(?:\n|$)")


@dataclass
class SessionInfo:
    path: Path
    session_id: str
    thread_name: str
    updated_at: str
    summary: str
    cwd: str
    workspace_name: str
    size: int
    is_agent: bool = False


@dataclass
class TranscriptEntry:
    timestamp: str
    role_class: str
    role_label: str
    content: str
    index_text: str = ""


@dataclass
class CommitEvent:
    timestamp: str
    commit_hash: str
    commit_message: str


@dataclass
class Turn:
    turn_id: str
    started_at: str
    entries: list[TranscriptEntry] = field(default_factory=list)
    prompt_preview: str = "(no prompt)"
    tool_calls: int = 0
    long_texts: list[str] = field(default_factory=list)
    commits: list[CommitEvent] = field(default_factory=list)
    status: str = "in_progress"
    completed_at: str | None = None


def _json_text(value: Any, *, indent: int | None = None) -> str:
    try:
        if indent is None:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return json.dumps(value, indent=indent, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def fenced_code_block(text: Any, language: str = "") -> str:
    """Return a Markdown fence that cannot be closed by the body text."""

    body = str(text).rstrip("\n")
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{body}\n{fence}"


def _code_language_for(text: str) -> str:
    try:
        json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ""
    return "json"


def github_slug(heading: str) -> str:
    """Return the heading slug used by common GitHub-style Markdown renderers."""

    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    return re.sub(r"\s+", "-", slug.strip())


def first_line(text: str, max_length: int = PROMPT_PREVIEW_LENGTH) -> str:
    candidate = text.strip().splitlines()[0] if text.strip() else "(no prompt)"
    return candidate if len(candidate) <= max_length else candidate[: max_length - 3] + "..."


def _timestamp_sort_key(value: str, fallback: float) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (AttributeError, TypeError, ValueError):
        return fallback


def _local_date(value: str) -> date | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.date()
    return parsed.astimezone().date()


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date: {value!r}. Expected YYYY-MM-DD."
        ) from exc


def read_session_index(index_path: Path) -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    if not index_path.exists():
        return results
    with index_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            session_id = item.get("id") or item.get("session_id")
            if session_id:
                results[str(session_id)] = item
    return results


def load_session_items(filepath: Path) -> list[dict[str, Any]]:
    """Load JSONL or the JSON container shapes accepted by codex-export."""

    if filepath.suffix.lower() == ".jsonl":
        items: list[dict[str, Any]] = []
        with filepath.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    items.append(item)
        return items

    with filepath.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "events", "entries", "loglines"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if "type" in data:
            return [data]
    return []


def extract_session_meta(filepath: Path) -> dict[str, Any]:
    try:
        items = load_session_items(filepath)
    except (OSError, json.JSONDecodeError):
        return {}
    for item in items:
        if item.get("type") == "session_meta" and isinstance(item.get("payload"), dict):
            return item["payload"]
    return {}


def session_id_from_meta(meta: dict[str, Any], filepath: Path) -> str:
    return str(meta.get("id") or meta.get("session_id") or filepath.stem)


def session_summary_from_meta(meta: dict[str, Any], filepath: Path) -> str:
    cwd = meta.get("cwd")
    if cwd:
        originator = meta.get("originator") or "Codex"
        return f"{originator} · {Path(str(cwd)).name}"
    return filepath.stem


def is_agent_session_meta(meta: dict[str, Any]) -> bool:
    source = meta.get("source")
    if isinstance(source, dict) and "subagent" in source:
        return True
    return bool(meta.get("agent_role") or meta.get("agent_nickname"))


def workspace_name_from_meta(meta: dict[str, Any]) -> str:
    cwd = meta.get("cwd", "")
    if cwd:
        return Path(str(cwd)).name or "unknown-workspace"
    return "unknown-workspace"


def _session_updated_at(path: Path, session_id: str, index: dict[str, dict[str, str]]) -> str:
    indexed = index.get(session_id, {})
    indexed_value = indexed.get("updated_at")
    if indexed_value:
        return str(indexed_value)
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def find_local_sessions(
    source_dir: Path,
    *,
    include_agents: bool = False,
    session_date: date | None = None,
    session_index_path: Path | None = None,
) -> list[SessionInfo]:
    index = read_session_index(session_index_path or (Path.home() / ".codex" / "session_index.jsonl"))
    results: list[SessionInfo] = []
    for path in source_dir.glob("**/*.jsonl"):
        meta = extract_session_meta(path)
        is_agent = is_agent_session_meta(meta)
        if is_agent and not include_agents:
            continue
        session_id = session_id_from_meta(meta, path)
        updated_at = _session_updated_at(path, session_id, index)
        session = SessionInfo(
            path=path,
            session_id=session_id,
            thread_name=str(index.get(session_id, {}).get("thread_name") or path.stem),
            updated_at=updated_at,
            summary=session_summary_from_meta(meta, path),
            cwd=str(meta.get("cwd") or ""),
            workspace_name=workspace_name_from_meta(meta),
            size=path.stat().st_size,
            is_agent=is_agent,
        )
        if session_date is not None and _local_date(session.updated_at) != session_date:
            continue
        results.append(session)

    results.sort(
        key=lambda item: _timestamp_sort_key(item.updated_at, item.path.stat().st_mtime),
        reverse=True,
    )
    return results


def find_all_sessions(
    source_dir: Path,
    *,
    include_agents: bool = False,
    session_date: date | None = None,
    session_index_path: Path | None = None,
) -> list[dict[str, Any]]:
    sessions = find_local_sessions(
        source_dir,
        include_agents=include_agents,
        session_date=session_date,
        session_index_path=session_index_path,
    )
    grouped: dict[str, dict[str, Any]] = {}
    for session in sessions:
        project = grouped.setdefault(
            session.workspace_name,
            {"name": session.workspace_name, "sessions": []},
        )
        project["sessions"].append(session)

    projects = list(grouped.values())
    for project in projects:
        project["sessions"].sort(
            key=lambda item: _timestamp_sort_key(item.updated_at, item.path.stat().st_mtime),
            reverse=True,
        )
    projects.sort(
        key=lambda item: _timestamp_sort_key(
            item["sessions"][0].updated_at,
            item["sessions"][0].path.stat().st_mtime,
        ),
        reverse=True,
    )
    return projects


def _message_text(payload: dict[str, Any]) -> str:
    content = payload.get("content", [])
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def should_skip_message(payload: dict[str, Any]) -> bool:
    if payload.get("role") == "developer":
        return True
    text = _message_text(payload).strip()
    return bool(text) and text.startswith(HIDDEN_MESSAGE_PREFIXES)


def render_response_message(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    role = str(payload.get("role") or "assistant")
    blocks = payload.get("content", [])
    if isinstance(blocks, str):
        blocks = [{"type": "text", "text": blocks}]
    rendered: list[str] = []
    index_parts: list[str] = []
    if not isinstance(blocks, list):
        blocks = [blocks]
    for block in blocks:
        if isinstance(block, dict) and block.get("type") in {"input_text", "output_text", "text"}:
            text = str(block.get("text") or "")
            if text:
                rendered.append(text.strip())
                index_parts.append(text.strip())
        elif isinstance(block, dict):
            rendered.append(fenced_code_block(_json_text(block, indent=2), "json"))
        else:
            rendered.append(fenced_code_block(block))

    role_map = {
        "user": ("user", "User"),
        "assistant": ("assistant", "Assistant"),
        "developer": ("system", "Developer"),
        "system": ("system", "System"),
    }
    role_class, role_label = role_map.get(role, ("system", role.title()))
    return role_class, role_label, "\n\n".join(rendered).strip(), "\n".join(index_parts)


def _tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("name") or payload.get("action") or payload.get("type") or "Tool")


def _tool_input(payload: dict[str, Any]) -> Any:
    for key in ("arguments", "input", "action", "execution"):
        if key in payload:
            return payload[key]
    return "{}"


def render_tool_call(payload: dict[str, Any]) -> tuple[str, str]:
    name = _tool_name(payload)
    raw_input = _tool_input(payload)
    input_text = raw_input if isinstance(raw_input, str) else _json_text(raw_input, indent=2)
    rendered = f"**{name}**\n\n{fenced_code_block(input_text, _code_language_for(input_text))}"
    return rendered, f"{name} {input_text}".strip()


def _tool_result_value(payload: dict[str, Any]) -> Any:
    for key in ("output", "result", "tools"):
        if key in payload:
            return payload[key]
    return payload


def render_tool_result(payload: dict[str, Any]) -> tuple[str, str]:
    value = _tool_result_value(payload)
    if isinstance(value, str):
        text = value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        if isinstance(parsed, dict) and "output" in parsed:
            text = str(parsed["output"])
    else:
        text = _json_text(value, indent=2)
    return fenced_code_block(text), str(text)


def extract_commit_events(text: str, timestamp: str) -> list[CommitEvent]:
    try:
        parsed: Any = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = text
    if isinstance(parsed, dict) and "output" in parsed:
        text = str(parsed["output"])
    else:
        text = str(parsed)
    if "\n" not in text and any(token in text for token in ("\\r\\n", "\\n", "\\r")):
        text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    return [
        CommitEvent(timestamp, match.group(1), match.group(2).strip())
        for line in text.splitlines()
        if (match := COMMIT_PATTERN.match(line.strip()))
    ]


def render_reasoning(payload: dict[str, Any]) -> tuple[str, str]:
    summary = payload.get("summary") or []
    if not summary:
        return "*Reasoning captured privately.*", ""
    text = "\n".join(
        item if isinstance(item, str) else _json_text(item)
        for item in summary
    )
    quoted = "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
    return quoted, text


def _event_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload")
    return payload if isinstance(payload, dict) else {"value": payload}


def parse_session_file(filepath: Path) -> tuple[dict[str, Any], list[Turn]]:
    meta: dict[str, Any] = {}
    turns: list[Turn] = []
    current_turn: Turn | None = None

    for item in load_session_items(filepath):
        item_type = item.get("type")
        timestamp = str(item.get("timestamp") or "")
        payload = _event_payload(item)

        if item_type == "session_meta":
            meta = payload
            continue

        if item_type == "event_msg" and payload.get("type") == "task_started":
            if current_turn and current_turn.entries:
                turns.append(current_turn)
            current_turn = Turn(
                turn_id=str(payload.get("turn_id") or f"turn-{len(turns) + 1}"),
                started_at=timestamp,
            )
            continue

        if current_turn is None:
            current_turn = Turn(turn_id="bootstrap", started_at=timestamp)

        if item_type == "response_item":
            payload_type = payload.get("type")
            if payload_type == "message":
                if should_skip_message(payload):
                    continue
                role_class, role_label, content, index_text = render_response_message(payload)
                if role_class == "assistant" and payload.get("phase") == "commentary":
                    role_class, role_label = "commentary", "Commentary"
                current_turn.entries.append(
                    TranscriptEntry(timestamp, role_class, role_label, content, index_text)
                )
                if role_class == "user" and current_turn.prompt_preview == "(no prompt)" and index_text.strip():
                    current_turn.prompt_preview = first_line(index_text)
                if role_class == "assistant" and len(index_text.strip()) >= LONG_TEXT_THRESHOLD:
                    current_turn.long_texts.append(index_text.strip())
            elif payload_type in TOOL_CALL_TYPES:
                current_turn.tool_calls += 1
                content, index_text = render_tool_call(payload)
                current_turn.entries.append(TranscriptEntry(timestamp, "tool", "Tool Call", content, index_text))
            elif payload_type in TOOL_RESULT_TYPES:
                content, index_text = render_tool_result(payload)
                current_turn.entries.append(TranscriptEntry(timestamp, "tool-reply", "Tool Result", content, index_text))
                current_turn.commits.extend(extract_commit_events(index_text, timestamp))
            elif payload_type == "reasoning":
                content, index_text = render_reasoning(payload)
                current_turn.entries.append(TranscriptEntry(timestamp, "thinking", "Reasoning", content, index_text))
            elif payload_type == "agent_message":
                role_class, role_label, content, index_text = render_response_message({**payload, "role": "assistant"})
                current_turn.entries.append(TranscriptEntry(timestamp, role_class, role_label, content, index_text))
            continue

        if item_type == "event_msg":
            payload_type = str(payload.get("type") or "event")
            if payload_type in MIRRORED_EVENT_TYPES or payload_type == "task_started":
                continue
            if payload_type == "task_complete":
                current_turn.status = "completed"
                current_turn.completed_at = timestamp
                continue
            if payload_type == "turn_aborted":
                current_turn.status = "aborted"
                current_turn.completed_at = timestamp
                current_turn.entries.append(
                    TranscriptEntry(
                        timestamp,
                        "system",
                        "Turn Aborted",
                        "*This turn was interrupted before completion.*",
                        "turn aborted",
                    )
                )
                continue
            current_turn.entries.append(
                TranscriptEntry(
                    timestamp,
                    "system",
                    payload_type.replace("_", " ").title(),
                    fenced_code_block(_json_text(payload, indent=2), "json"),
                    payload_type,
                )
            )
            continue

        if item_type not in {"session_meta", "response_item"}:
            current_turn.entries.append(
                TranscriptEntry(
                    timestamp,
                    "system",
                    str(item_type or "Event").replace("_", " ").title(),
                    fenced_code_block(_json_text(item, indent=2), "json"),
                    str(item_type or "event"),
                )
            )

    if current_turn and current_turn.entries:
        turns.append(current_turn)
    return meta, turns


def render_entry(entry: TranscriptEntry) -> str:
    heading = f"### {entry.role_label}"
    if entry.timestamp:
        heading += f" · {entry.timestamp}"
    body = entry.content.strip()
    return f"{heading}\n\n{body}\n\n"


def summarize_hidden_entries(entries: list[TranscriptEntry]) -> str:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.role_label] = counts.get(entry.role_label, 0) + 1
    parts = [label if count == 1 else f"{count} {label}" for label, count in counts.items()]
    detail = ", ".join(parts[:3])
    if len(parts) > 3:
        detail += ", ..."
    item_label = "item" if len(entries) == 1 else "items"
    return f"Codex process ({len(entries)} {item_label}: {detail})"


def build_turn_messages(turn: Turn) -> str:
    final_assistant_index: int | None = None
    for index in range(len(turn.entries) - 1, -1, -1):
        if turn.entries[index].role_class == "assistant":
            final_assistant_index = index
            break

    visible_indexes = {index for index, entry in enumerate(turn.entries) if entry.role_class == "user"}
    if final_assistant_index is not None:
        visible_indexes.add(final_assistant_index)

    rendered: list[str] = []
    hidden: list[TranscriptEntry] = []

    def flush_hidden() -> None:
        if not hidden:
            return
        rendered.append(f"**{summarize_hidden_entries(hidden)}**\n\n")
        rendered.extend(render_entry(entry) for entry in hidden)
        hidden.clear()

    for index, entry in enumerate(turn.entries):
        if index in visible_indexes:
            flush_hidden()
            rendered.append(render_entry(entry))
        else:
            hidden.append(entry)
    flush_hidden()
    return "".join(rendered)


def _turn_heading(turn_num: int, turn: Turn) -> str:
    title = " ".join(str(turn.prompt_preview).split()) or "(no prompt)"
    return f"Turn {turn_num}: {title} ({turn.status})"


def build_index_items(turns: list[Turn]) -> list[str]:
    timeline: list[tuple[float, int, str]] = []
    for index, turn in enumerate(turns, start=1):
        heading = _turn_heading(index, turn)
        link = f"#{github_slug(heading)}"
        preview = " ".join(str(turn.prompt_preview).split()) or "(no prompt)"
        stats = f"{turn.tool_calls} tool calls · {turn.status}"
        if turn.long_texts:
            stats += "\n\n" + "\n\n".join(
                f"**Long assistant response**\n\n{text}" for text in turn.long_texts
            )
        item = f"### Turn {index}: {preview}\n\n[view]({link})"
        if turn.started_at:
            item += f" · {turn.started_at}"
        item += f"\n\n{stats}\n"
        timeline.append((_timestamp_sort_key(turn.started_at, index), 0, item))
        for offset, commit in enumerate(turn.commits):
            commit_item = f"**`{commit.commit_hash[:7]}`** {commit.commit_message} · [view]({link}) · {commit.timestamp}\n"
            timeline.append(
                (_timestamp_sort_key(commit.timestamp, index + offset / 1000.0), 1, commit_item)
            )
    timeline.sort(key=lambda item: (item[0], item[1]))
    return [item for _, _, item in timeline]


def build_session_meta(meta: dict[str, Any]) -> list[tuple[str, str]]:
    cwd = str(meta.get("cwd") or "")
    workspace_name = Path(cwd).name if cwd else ""
    fields = [
        ("Session ID", str(meta.get("id") or meta.get("session_id") or "")),
        ("Originator", str(meta.get("originator") or "")),
        ("Model Provider", str(meta.get("model_provider") or "")),
        ("CLI Version", str(meta.get("cli_version") or "")),
        ("Workspace", workspace_name),
    ]
    return [(label, value) for label, value in fields if value]


def build_full_markdown(
    title: str,
    meta_fields: list[tuple[str, str]],
    turns: list[Turn],
) -> str:
    lines = [
        f"# {title}",
        "",
        "*Codex Conversation Export · Markdown*",
        "",
    ]
    if meta_fields:
        lines.extend(["## Session Info", ""])
        lines.extend(f"- **{label}**: {value}" for label, value in meta_fields)
        lines.append("")

    summary = (
        f"{len(turns)} turns · {sum(len(turn.entries) for turn in turns)} entries · "
        f"{sum(turn.tool_calls for turn in turns)} tool calls · "
        f"{sum(len(turn.commits) for turn in turns)} commits"
    )
    lines.extend([summary, "", "## Timeline", ""])
    lines.extend(item.rstrip("\n") for item in build_index_items(turns))
    lines.extend(["", "---", ""])
    for index, turn in enumerate(turns, start=1):
        lines.extend([f"## {_turn_heading(index, turn)}", "", build_turn_messages(turn).rstrip(), "", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def build_conversion_title(meta: dict[str, Any], input_path: Path, index_path: Path | None = None) -> str:
    index = read_session_index(index_path or (Path.home() / ".codex" / "session_index.jsonl"))
    session_id = str(meta.get("id") or meta.get("session_id") or "")
    if session_id and session_id in index:
        return str(index[session_id].get("thread_name") or input_path.stem)
    return input_path.stem


def generate_markdown(
    input_path: Path,
    output_dir: Path,
    *,
    session_index_path: Path | None = None,
) -> dict[str, Any]:
    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")
    meta, turns = parse_session_file(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    document = build_full_markdown(
        build_conversion_title(meta, input_path, session_index_path),
        build_session_meta(meta),
        turns,
    )
    output_file = output_dir / f"{input_path.stem}.md"
    output_file.write_text(document, encoding="utf-8", newline="\n")
    return {
        "meta": meta,
        "turns": turns,
        "output_dir": output_dir,
        "format": "markdown",
        "index_file": output_file.name,
    }


def build_project_index_markdown(project_name: str, sessions: list[SessionInfo]) -> str:
    lines = [f"# {project_name}", "", f"{len(sessions)} sessions", ""]
    for session in sessions:
        filename = session.path.stem
        link = f"{filename}/{filename}.md"
        lines.append(f"- [{session.thread_name}]({link}) — {session.updated_at} · {session.summary}")
    return "\n".join(lines) + "\n"


def build_master_index_markdown(projects: list[dict[str, Any]], total_projects: int, total_sessions: int) -> str:
    lines = [
        "# Codex Session Archive",
        "",
        f"{total_projects} workspaces · {total_sessions} sessions",
        "",
    ]
    for project in projects:
        lines.extend([f"## {project['name']} ({len(project['sessions'])} sessions)", ""])
        for session in project["sessions"]:
            filename = session.path.stem
            link = f"{project['name']}/{filename}/{filename}.md"
            lines.append(f"- [{session.thread_name}]({link}) — {session.updated_at}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_batch_markdown(
    source_dir: Path,
    output_dir: Path,
    *,
    include_agents: bool = False,
    dry_run: bool = False,
    session_date: date | None = None,
    session_index_path: Path | None = None,
) -> dict[str, Any]:
    projects = find_all_sessions(
        source_dir,
        include_agents=include_agents,
        session_date=session_date,
        session_index_path=session_index_path,
    )
    total_sessions = sum(len(project["sessions"]) for project in projects)
    if dry_run:
        return {
            "projects": projects,
            "total_projects": len(projects),
            "total_sessions": total_sessions,
            "output_dir": output_dir,
            "failed_sessions": [],
            "format": "markdown",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    successful_projects: list[dict[str, Any]] = []
    failed_sessions: list[dict[str, str]] = []
    successful_count = 0

    for project in projects:
        project_dir = output_dir / project["name"]
        successful_sessions: list[SessionInfo] = []
        for session in project["sessions"]:
            session_dir = project_dir / session.path.stem
            try:
                generate_markdown(
                    session.path,
                    session_dir,
                    session_index_path=session_index_path,
                )
            except Exception as exc:  # keep one broken session from aborting the archive
                failed_sessions.append(
                    {"project": project["name"], "session": session.path.stem, "error": str(exc)}
                )
                continue
            successful_sessions.append(session)
            successful_count += 1

        if not successful_sessions:
            continue
        successful_projects.append({"name": project["name"], "sessions": successful_sessions})
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "index.md").write_text(
            build_project_index_markdown(project["name"], successful_sessions),
            encoding="utf-8",
            newline="\n",
        )

    (output_dir / "index.md").write_text(
        build_master_index_markdown(successful_projects, len(successful_projects), successful_count),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "projects": successful_projects,
        "total_projects": len(successful_projects),
        "total_sessions": successful_count,
        "output_dir": output_dir,
        "failed_sessions": failed_sessions,
        "format": "markdown",
    }


def markdown_format(value: str) -> str:
    if value.lower() not in {"markdown", "md"}:
        raise argparse.ArgumentTypeError(
            "Only Markdown output is supported; HTML export is not available."
        )
    return "markdown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    json_parser = subparsers.add_parser("json", help="Export one local JSON/JSONL session as Markdown.")
    json_parser.add_argument("session_file", type=Path)
    json_parser.add_argument("-o", "--output", type=Path, required=True, help="Output directory.")
    json_parser.add_argument("--format", type=markdown_format, default="markdown")

    all_parser = subparsers.add_parser("all", help="Export local sessions as a Markdown archive.")
    all_parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / ".codex" / "sessions",
        help="Codex sessions directory.",
    )
    all_parser.add_argument("-o", "--output", type=Path, default=Path("./codex-archive"))
    all_parser.add_argument("--include-agents", action="store_true")
    all_parser.add_argument("--dry-run", action="store_true")
    all_parser.add_argument("-q", "--quiet", action="store_true")
    all_parser.add_argument("--date", type=parse_date, default=None, dest="session_date")
    all_parser.add_argument("--format", type=markdown_format, default="markdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "json":
            result = generate_markdown(args.session_file, args.output)
            print(f"Conversion: {result['output_dir'] / result['index_file']}")
            return 0

        result = generate_batch_markdown(
            args.source,
            args.output,
            include_agents=args.include_agents,
            dry_run=args.dry_run,
            session_date=args.session_date,
        )
        if args.dry_run:
            if not args.quiet:
                print(
                    f"Would convert {result['total_sessions']} sessions across "
                    f"{result['total_projects']} workspaces into {args.output}"
                )
                for project in result["projects"]:
                    print(f"{project['name']}: {len(project['sessions'])} sessions")
            return 0

        if not args.quiet:
            print(
                f"Archived {result['total_sessions']} sessions across "
                f"{result['total_projects']} workspaces to {args.output / 'index.md'}"
            )
            if result["failed_sessions"]:
                print(f"Skipped {len(result['failed_sessions'])} failed sessions:")
                for failed in result["failed_sessions"]:
                    print(f"- {failed['project']}/{failed['session']}: {failed['error']}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
