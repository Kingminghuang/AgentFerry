import json
import unittest
from pathlib import Path

from scripts.export_session_to_okf import export_rollout, normalize_rollout


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class SessionExportTests(unittest.TestCase):
    def test_injected_context_moves_out_of_conversation_but_remains_in_system_document(self):
        """Fails if runtime-injected text is rendered as a real user turn."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "rollout.jsonl"
            output = tmp_path / "demo"
            write_jsonl(
                source,
                [
                    {
                        "timestamp": "2026-08-12T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"session_id": "s-context", "cwd": "/private/project"},
                    },
                    {
                        "timestamp": "2026-08-12T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "<environment_context>secret runtime context</environment_context>"}],
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    },
                    {
                        "timestamp": "2026-08-12T00:00:02Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "# Actual request\n\nPlease inspect this."}],
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    },
                ],
            )

            export_rollout(source, output, title="Context test")

            bundle = output / "01 Sources" / "Sessions" / "codex" / "s-context"
            session = (bundle / "session.md").read_text(encoding="utf-8")
            system = (bundle / "system.md").read_text(encoding="utf-8")
            conversation = session.split("# 完整会话", 1)[1]
            self.assertIn("# Actual request", conversation)
            self.assertNotIn("secret runtime context", conversation)
            self.assertIn("运行时注入上下文已移至", session)
            self.assertIn("### injected_context", system)
            self.assertIn("secret runtime context", system)

    def test_readable_documents_group_records_and_chunk_large_payloads(self):
        """Fails if readable projections lose Markdown, grouping, or oversized evidence."""
        import tempfile

        large_output = "x" * (33 * 1024)
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "rollout.jsonl"
            output = tmp_path / "demo"
            write_jsonl(
                source,
                [
                    {
                        "timestamp": "2026-08-12T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"session_id": "s-readable", "cwd": "/private/project", "base_instructions": "base rules"},
                    },
                    {
                        "timestamp": "2026-08-12T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "# Request\n\n- keep Markdown"}],
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    },
                    {
                        "timestamp": "2026-08-12T00:00:02Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": "call-1",
                            "arguments": '{"cmd":"rg --files"}',
                            "turn_id": "turn-1",
                        },
                    },
                    {
                        "timestamp": "2026-08-12T00:00:03Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-1",
                            "output": large_output,
                            "turn_id": "turn-1",
                        },
                    },
                    {
                        "timestamp": "2026-08-12T00:00:04Z",
                        "type": "response_item",
                        "payload": {
                            "type": "reasoning",
                            "content": "The repository needs a readable export.",
                            "turn_id": "turn-1",
                        },
                    },
                    {
                        "timestamp": "2026-08-12T00:00:05Z",
                        "type": "turn_context",
                        "payload": {"turn_id": "turn-1", "workspace": "project"},
                    },
                    {
                        "timestamp": "2026-08-12T00:00:06Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete", "turn_id": "turn-1", "status": "completed"},
                    },
                    {
                        "timestamp": "2026-08-12T00:00:07Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "## Result\n\nExport is ready."}],
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    },
                ],
            )

            export_rollout(source, output, title="Readable test")

            bundle = output / "01 Sources" / "Sessions" / "codex" / "s-readable"
            session = (bundle / "session.md").read_text(encoding="utf-8")
            tools = (bundle / "tools.md").read_text(encoding="utf-8")
            reasoning = (bundle / "reasoning.md").read_text(encoding="utf-8")
            system = (bundle / "system.md").read_text(encoding="utf-8")
            events = (bundle / "events.md").read_text(encoding="utf-8")

            self.assertIn("## 阅读卡片", session)
            self.assertIn("# Request\n\n- keep Markdown", session)
            self.assertNotIn("~~~text\n# Request", session)
            self.assertIn("工具活动", session)
            self.assertIn("> 完成 1；[exec_command]", session)
            self.assertIn("返回主会话", tools)
            self.assertIn("## Turn turn-1", tools)
            self.assertIn("<details>", tools)
            self.assertIn("返回主会话", reasoning)
            self.assertIn("## Turn turn-1", reasoning)
            self.assertIn("<details>", reasoning)
            self.assertIn("返回主会话", system)
            self.assertIn("## 会话级上下文", system)
            self.assertIn("## Turn turn-1", system)
            self.assertIn("<details>", system)
            self.assertIn("## 时间线", events)
            self.assertIn("| 序号 | 类型 |", events)
            self.assertIn("<details>", events)

            assets = sorted((bundle / "assets").glob("*.md"))
            self.assertTrue(assets)
            self.assertIn("附件分片", tools)
            self.assertNotIn(large_output, tools)
            chunk_text = "".join(
                asset.read_text(encoding="utf-8").split("~~~text\n", 1)[1].rsplit("\n~~~", 1)[0]
                for asset in assets
            )
            self.assertEqual(chunk_text, large_output)
            index = (bundle / "index.md").read_text(encoding="utf-8")
            self.assertIn("assets/", index)

    def test_unscoped_tool_calls_attach_to_the_surrounding_real_turn(self):
        """Fails if missing provider turn IDs create one fake transcript turn per tool call."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "rollout.jsonl"
            output = tmp_path / "demo"
            write_jsonl(
                source,
                [
                    {"timestamp": "2026-08-12T00:00:00Z", "type": "session_meta", "payload": {"session_id": "s-unscoped"}},
                    {
                        "timestamp": "2026-08-12T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Check the repository."}],
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    },
                    {
                        "timestamp": "2026-08-12T00:00:02Z",
                        "type": "response_item",
                        "payload": {"type": "function_call", "name": "exec_command", "call_id": "call-unscoped", "arguments": "pwd"},
                    },
                    {
                        "timestamp": "2026-08-12T00:00:03Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Repository checked."}],
                            "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                        },
                    },
                ],
            )

            export_rollout(source, output, title="Unscoped tools")

            session = (output / "01 Sources" / "Sessions" / "codex" / "s-unscoped" / "session.md").read_text(encoding="utf-8")
            self.assertNotIn("Turn record-", session)
            self.assertEqual(session.count("## Turn turn-1"), 1)
            self.assertLess(session.index("Check the repository."), session.index("工具活动"))
            self.assertLess(session.index("工具活动"), session.index("Repository checked."))

    def test_reexport_removes_stale_managed_chunks_when_content_shrinks(self):
        """Fails if a later, smaller snapshot leaves obsolete managed assets behind."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "rollout.jsonl"
            output = tmp_path / "demo"
            large_rows = [
                {"timestamp": "2026-08-12T00:00:00Z", "type": "session_meta", "payload": {"session_id": "s-reset"}},
                {
                    "timestamp": "2026-08-12T00:00:01Z",
                    "type": "response_item",
                    "payload": {"type": "function_call", "name": "exec_command", "call_id": "call-reset", "arguments": "pwd"},
                },
                {
                    "timestamp": "2026-08-12T00:00:02Z",
                    "type": "response_item",
                    "payload": {"type": "function_call_output", "call_id": "call-reset", "output": "x" * (33 * 1024)},
                },
            ]
            write_jsonl(source, large_rows)
            export_rollout(source, output, title="Reset test")
            bundle = output / "01 Sources" / "Sessions" / "codex" / "s-reset"
            self.assertTrue(list((bundle / "assets").glob("*.md")))

            small_rows = [
                large_rows[0],
                large_rows[1],
                {
                    "timestamp": "2026-08-12T00:00:02Z",
                    "type": "response_item",
                    "payload": {"type": "function_call_output", "call_id": "call-reset", "output": "small result"},
                },
            ]
            write_jsonl(source, small_rows)
            export_rollout(source, output, title="Reset test")

            self.assertFalse(list((bundle / "assets").glob("*.md")))
            self.assertNotIn("## Assets", (bundle / "index.md").read_text(encoding="utf-8"))

    def test_normalization_keeps_jsonl_order_and_deduplicates_message_mirrors(self):
        rows = [
        {
            "timestamp": "2026-08-12T00:00:00Z",
            "type": "session_meta",
            "payload": {"session_id": "s-1", "timestamp": "2026-08-12T00:00:00Z", "cwd": "/private/project"},
        },
        {
            "timestamp": "2026-08-12T00:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "first"}],
                "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
            },
        },
        {
            "timestamp": "2026-08-12T00:00:01Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "first", "turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-08-12T00:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "second"}],
                "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
            },
        },
    ]

        records = normalize_rollout(rows, provider="codex")

        messages = [record for record in records if record["kind"] in {"user_message", "assistant_message"}]
        self.assertEqual(
            [(record["sequence"], record["kind"]) for record in messages],
            [(2, "user_message"), (4, "assistant_message")],
        )
        self.assertEqual(len(messages[0]["raw_evidence_refs"]), 2)
        self.assertTrue(all(ref.startswith("ev:codex:s-1:") for ref in messages[0]["raw_evidence_refs"]))


    def test_export_writes_okf_bundle_and_session_message_order(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            source = tmp_path / "rollout.jsonl"
            output = tmp_path / "demo"
            write_jsonl(
                source,
                [
            {
                "timestamp": "2026-08-12T00:00:00Z",
                "type": "session_meta",
                "payload": {"session_id": "s-1", "id": "s-1", "timestamp": "2026-08-12T00:00:00Z", "cwd": "/private/project"},
            },
            {
                "timestamp": "2026-08-12T00:00:02Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "answer"}],
                    "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                },
            },
            {
                "timestamp": "2026-08-12T00:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "question"}],
                    "internal_chat_message_metadata_passthrough": {"turn_id": "turn-1"},
                },
            },
                ],
            )

            export_rollout(source, output, title="Test session")

            bundle = output / "01 Sources" / "Sessions" / "codex" / "s-1"
            session = (bundle / "session.md").read_text(encoding="utf-8")
            full_session = session.split("# 完整会话", 1)[1]
            self.assertLess(full_session.index("answer"), full_session.index("question"))
            self.assertIn("resource: \"evidence://codex/s-1\"", session)
            self.assertTrue((bundle / "index.md").read_text(encoding="utf-8").startswith("# Session Bundle\n"))
            self.assertTrue((bundle / "reasoning.md").exists())
            self.assertTrue((bundle / "system.md").exists())
            self.assertTrue((bundle / "tools.md").exists())
            self.assertTrue((bundle / "events.md").exists())


if __name__ == "__main__":
    unittest.main()
