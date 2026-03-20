"""Boot test: verify FastAPI app loads with all new modules."""
import os, sys
os.environ.setdefault('OPENCLAW_GATEWAY_URL', 'http://127.0.0.1:18789')

print("Loading FastAPI app...")
from src.server.main import app

print("FastAPI app loaded successfully")
print(f"Total routes: {len(app.routes)}")

# Check new API endpoints exist
new_endpoints = [
    '/api/access/config',
    '/api/access/presets',
    '/api/local-command',
    '/api/local-commands',
    '/api/mode',
    '/api/intent',
    '/api/intent/context',
    '/api/intent/history',
    '/api/workflows',
    '/api/mcp/desktop-tools',
    '/api/mcp/desktop-tool/call',
]

registered_paths = set()
for r in app.routes:
    if hasattr(r, 'path'):
        registered_paths.add(r.path)

print("\nNew endpoint verification:")
all_ok = True
for ep in new_endpoints:
    found = ep in registered_paths
    status = "OK" if found else "MISSING"
    if not found:
        all_ok = False
    print(f"  {status}: {ep}")

# Count all routes
api_routes = [r for r in app.routes if hasattr(r, 'path') and r.path.startswith('/api/')]
ws_routes = [r for r in app.routes if hasattr(r, 'path') and '/ws' in r.path]
print(f"\nAPI routes: {len(api_routes)}")
print(f"WebSocket routes: {len(ws_routes)}")

# Verify module imports work
print("\nModule import checks:")
try:
    from src.server.intent_router import get_intent_router
    print("  intent_router: OK")
except Exception as e:
    print(f"  intent_router: FAIL - {e}")
    all_ok = False

try:
    from src.server.mcp_desktop_tools import get_mcp_desktop_tools
    tools = get_mcp_desktop_tools()
    print(f"  mcp_desktop_tools: OK ({len(tools)} tools)")
except Exception as e:
    print(f"  mcp_desktop_tools: FAIL - {e}")
    all_ok = False

try:
    from src.server.workflow_recorder import get_workflow_recorder
    rec = get_workflow_recorder()
    print(f"  workflow_recorder: OK ({len(rec.list_workflows())} workflows)")
except Exception as e:
    print(f"  workflow_recorder: FAIL - {e}")
    all_ok = False

try:
    from src.server.access_config import load_config, get_presets
    cfg = load_config()
    presets = get_presets()
    print(f"  access_config: OK ({len(presets)} presets)")
except Exception as e:
    print(f"  access_config: FAIL - {e}")
    all_ok = False

try:
    from src.server.local_voice_commands import get_engine
    eng = get_engine()
    cmds = eng.get_all_commands()
    print(f"  local_voice_commands: OK ({len(cmds)} commands)")
except Exception as e:
    print(f"  local_voice_commands: FAIL - {e}")
    all_ok = False

print(f"\n{'='*50}")
print(f"BOOT TEST: {'PASS' if all_ok else 'FAIL'}")
print(f"{'='*50}")

sys.exit(0 if all_ok else 1)
