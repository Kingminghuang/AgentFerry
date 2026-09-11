# Codex 会话 Markdown 导出

当前项目提供一个只生成原生 Markdown 的 Codex 会话导出脚本：

```bash
python3 scripts/export_codex_markdown.py json \
  ~/.codex/sessions/YYYY/MM/DD/rollout-xxxx.jsonl \
  -o ./codex-export
```

批量导出指定日期最近更新的会话：

```bash
python3 scripts/export_codex_markdown.py all \
  --date 2026-09-07 \
  -o ./codex-archive
```

默认源目录是 `~/.codex/sessions`，默认排除 agent/subagent 会话。需要预览范围时使用：

```bash
python3 scripts/export_codex_markdown.py all \
  --source ~/.codex/sessions \
  --date 2026-09-07 \
  --dry-run
```

`json` 会生成 `<输出目录>/<会话文件名>.md`。`all` 会生成总索引、workspace 索引和每个会话的自包含 Markdown 文件：

```text
codex-archive/
  index.md
  <workspace>/
    index.md
    <session>/
      <session>.md
```

日期按会话索引 `~/.codex/session_index.jsonl` 中的 `updated_at` 判断；没有索引记录时回退到会话文件的修改时间，并使用本地时区。脚本不提供 HTML、Gist、浏览器打开、交互式选择器、远程 URL 或原始 JSON 复制功能。
