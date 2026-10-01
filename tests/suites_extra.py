# Suites added after D44. (group, script, extra args) — see tests/run_all.py.
SUITES = [
    ("core", "mcp_server/test_storage.py", []),
    ("core", "builder/test_versioned_import.py", []),
    ("core", "web/test_web.py", []),
    ("core", "web/test_gateway.py", []),
    ("enterprise", "enterprise/test_enterprise.py", []),
    ("enterprise", "mcp_server/test_server_tools.py", []),
    ("js", "enterprise/test_parity.py", []),
    ("js", "studio/core/core.test.js", []),
    ("studio", "studio/test_studio.py", []),
    ("studio", "web/test_browser.py", []),
    ("postgres", "db/test_postgres.py", []),
    ("postgres", "@replay", []),
]
