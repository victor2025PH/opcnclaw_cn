# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: 十三香小龙虾 AI (OpenClaw Voice) v4.1.0

Self-hosted full-duplex AI voice assistant with desktop control, WeChat automation, and human-AI collaboration.

## Commands

```bash
# Run server
python -m src.server.main

# Run all tests (exclude boot_test.py which has sys.exit)
python -m pytest tests/ -q --ignore=tests/boot_test.py

# Run single test file
python -m pytest tests/test_intent_fusion.py -v

# Build installer (requires Inno Setup 6)
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss

# Tauri desktop build
npx tauri build
```

## Architecture

```
FastAPI (Python 3.10+)
├── 10 routers: voice/desktop/wechat/workflow/admin/models/mcp/intent/a2a + main.py inline
├── AI Router: 15 platforms auto-failover (zhipu_flash → baidu → siliconflow → deepseek → ...)
├── 20 Function Calling tools: native FC for zhipu/deepseek, ReAct fallback for others
├── IntentFusionEngine: 4-channel signal fusion (gaze+expression+voice+desktop), 500ms window
├── A2A Server: Google A2A compatible, 6 skills, webhook notifications
├── CoworkBus: human-AI desktop conflict detection, task queue with priority
├── WeChat 4.x: accessibility hook (SetWinEventHook) + UIA + OCR 4-track adapter
├── MCP Server: 5 tools (wechat_send/read/status, cowork_status, action_journal)
└── 2 SQLite DBs: main.db (FTS5 dual-index) + wechat.db
```

## Key Design Decisions

- **Database**: 2 SQLite via `src/server/db.py` singleton. All modules use `_db.get_conn("main")`.
- **AI Tools**: `src/server/tools.py` defines 20 tools in OpenAI schema. Native function calling for zhipu/deepseek (`supports_function_calling` in providers.json), ReAct text parsing fallback for others.
- **Router**: `src/router/router.py` auto-switches between AI platforms on rate-limit/error/timeout. First-chunk timeout = 12s.
- **WeChat 4.x**: Window class `mmui::MainWindow`, process `WeChatAppEx.exe`. Accessibility hook required to expose UI tree (83 controls).
- **Desktop safety**: All desktop operations check `CoworkBus.can_operate_desktop()` — AI pauses when user is active.
- **Startup**: Two-phase — Phase 1 (fast: DB+config, <2s), Phase 2 (background: AI+STT+TTS+OCR).

## File Ownership (Claude vs Cursor)

- **Claude (backend)**: `src/server/`, `src/mcp/`, `src/router/`, `tests/`, `CLAUDE.md`
- **Cursor (frontend)**: `src/client/`, HTML/CSS/JS files
- **Shared**: `main.py` (routes), `config.ini`, `.env`, `CHANGELOG.md`

## Testing

- 340+ tests, run with `--ignore=tests/boot_test.py`
- `test_server.py` requires live server (5 errors expected in CI)
- `test_benchmark.py` has timing-dependent assertions (may flake on slow machines)
- New modules must have tests in `tests/test_<module>.py`

## Language

- All code comments in Chinese
- Commit messages in Chinese
- User-facing responses in Chinese
