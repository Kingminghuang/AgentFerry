import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import scripts.export_codex_markdown as markdown_export
from scripts.export_codex_markdown import (
    generate_batch_markdown,
    generate_markdown,
    main,
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def session_rows(
    session_id: str = "session-1",
    workspace: str = "/tmp/demo-workspace",
    *,
    include_agent: bool = False,
) -> list[dict]:
    meta = {
        "id": session_id,
        "cwd": workspace,
        "originator": "Codex",
        "model_provider": "OpenAI",
        "cli_version": "0.1.0",
    }
    if include_agent:
        meta["source"] = {"subagent": True}
    return [
        {"type": "session_meta", "timestamp": "2026-09-10T10:00:00Z", "payload": meta},
        {
            "type": "event_msg",
            "timestamp": "2026-09-10T10:00:01Z",
            "payload": {"type": "task_started", "turn_id": "turn-1"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-10T10:00:02Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Export this session\n\nKeep Markdown."}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-10T10:00:03Z",
            "payload": {
                "type": "reasoning",
                "summary": ["Planning the export."],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-10T10:00:04Z",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec_command",
                "call_id": "call-1",
                "input": "echo done",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-10T10:00:05Z",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "call-1",
                "output": "result",
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-09-10T10:00:06Z",
            "payload": {
                "type": "item_completed",
                "item": {"type": "message", "role": "user", "content": "Export this session"},
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-10T10:00:07Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The export is ready."}],
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-09-10T10:00:08Z",
            "payload": {"type": "task_complete"},
        },
    ]


class MarkdownExportTests(unittest.TestCase):
    def test_single_session_is_one_native_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "session.jsonl"
            output = root / "output"
            write_jsonl(source, session_rows())

            result = generate_markdown(source, output)

            self.assertEqual(result["format"], "markdown")
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["session.md"])
            document = (output / "session.md").read_text(encoding="utf-8")
            self.assertIn("# session", document)
            self.assertIn("## Session Info", document)
            self.assertIn("## Timeline", document)
            self.assertIn("### User · 2026-09-10T10:00:02Z", document)
            self.assertIn("> Planning the export.", document)
            self.assertIn("### Tool Call · 2026-09-10T10:00:04Z", document)
            self.assertIn("### Tool Result · 2026-09-10T10:00:05Z", document)
            self.assertIn("The export is ready.", document)
            self.assertIn("\n---\n", document)
            self.assertNotIn("<div", document)
            self.assertNotIn("<details", document)
            self.assertNotIn("<pre", document)
            self.assertNotIn("<script", document)

    def test_runtime_mirrors_are_not_rendered_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "session.jsonl"
            output = root / "output"
            rows = session_rows()
            rows.insert(
                3,
                {
                    "type": "response_item",
                    "timestamp": "2026-09-10T10:00:02.500000Z",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "<environment_context>hidden</environment_context>"}],
                    },
                },
            )
            write_jsonl(source, rows)

            generate_markdown(source, output)
            document = (output / "session.md").read_text(encoding="utf-8")
            self.assertNotIn("hidden", document)
            self.assertEqual(document.count("Export this session"), 3)
            self.assertNotIn("item_completed", document)

    def test_fence_grows_for_embedded_backticks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "session.jsonl"
            output = root / "output"
            rows = session_rows()
            rows.insert(
                5,
                {
                    "type": "response_item",
                    "timestamp": "2026-09-10T10:00:04.500000Z",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "output": "has ``` embedded fence\nsecond line",
                    },
                },
            )
            write_jsonl(source, rows)

            generate_markdown(source, output)
            document = (output / "session.md").read_text(encoding="utf-8")
            self.assertIn("````", document)
            self.assertIn("has ``` embedded fence", document)

    def test_json_array_input_and_multiple_turns_stay_in_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "multi.json"
            output = root / "output"
            rows = session_rows()
            for number in range(2, 4):
                rows.extend(
                    [
                        {
                            "type": "event_msg",
                            "timestamp": f"2026-09-10T10:01:0{number}Z",
                            "payload": {"type": "task_started", "turn_id": f"turn-{number}"},
                        },
                        {
                            "type": "response_item",
                            "timestamp": f"2026-09-10T10:01:1{number}Z",
                            "payload": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": f"prompt {number}"}],
                            },
                        },
                        {
                            "type": "response_item",
                            "timestamp": f"2026-09-10T10:01:2{number}Z",
                            "payload": {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": f"done {number}"}],
                            },
                        },
                    ]
                )
            source.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

            generate_markdown(source, output)
            document = (output / "multi.md").read_text(encoding="utf-8")
            self.assertIn("## Turn 3: prompt 3 (in_progress)", document)
            self.assertGreaterEqual(document.count("\n---\n"), 3)
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["multi.md"])

    def test_batch_indexes_date_filter_agents_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "sessions"
            output = root / "archive"
            recent = source_dir / "a" / "recent.jsonl"
            agent = source_dir / "a" / "agent.jsonl"
            old = source_dir / "b" / "old.jsonl"
            write_jsonl(recent, session_rows("recent", "/tmp/workspace-a"))
            write_jsonl(agent, session_rows("agent", "/tmp/workspace-a", include_agent=True))
            write_jsonl(old, session_rows("old", "/tmp/workspace-b"))
            old_time = datetime(2020, 1, 1).timestamp()
            os.utime(old, (old_time, old_time))

            dry_result = generate_batch_markdown(
                source_dir,
                output,
                session_date=date(2000, 1, 1),
                dry_run=True,
            )
            self.assertEqual(dry_result["total_sessions"], 0)
            self.assertFalse(output.exists())

            recent_date = datetime.fromtimestamp(recent.stat().st_mtime).date()
            result = generate_batch_markdown(source_dir, output, session_date=recent_date)
            self.assertEqual(result["total_sessions"], 1)
            self.assertTrue((output / "index.md").exists())
            self.assertTrue((output / "workspace-a" / "index.md").exists())
            self.assertTrue((output / "workspace-a" / "recent" / "recent.md").exists())
            self.assertFalse((output / "workspace-a" / "agent").exists())
            self.assertFalse((output / "workspace-b").exists())

            include_result = generate_batch_markdown(
                source_dir,
                root / "archive-with-agents",
                include_agents=True,
                session_date=recent_date,
            )
            self.assertEqual(include_result["total_sessions"], 2)

    def test_batch_continues_after_a_broken_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "sessions"
            output = root / "archive"
            write_jsonl(source_dir / "workspace" / "good.jsonl", session_rows())
            write_jsonl(source_dir / "workspace" / "broken.jsonl", session_rows("broken"))

            original_generate = markdown_export.generate_markdown

            def fail_broken(path: Path, destination: Path, **kwargs):
                if path.stem == "broken":
                    raise ValueError("simulated render failure")
                return original_generate(path, destination, **kwargs)

            with patch.object(markdown_export, "generate_markdown", side_effect=fail_broken):
                result = generate_batch_markdown(source_dir, output)

            self.assertEqual(result["total_sessions"], 1)
            self.assertEqual(len(result["failed_sessions"]), 1)
            self.assertEqual(result["failed_sessions"][0]["session"], "broken")

    def test_cli_rejects_html_and_supports_json_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "session.jsonl"
            output = root / "output"
            write_jsonl(source, session_rows())

            self.assertEqual(main(["json", str(source), "-o", str(output), "--format", "markdown"]), 0)
            self.assertTrue((output / "session.md").exists())
            with self.assertRaises(SystemExit) as error:
                main(["json", str(source), "-o", str(root / "html"), "--format", "html"])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
