# Suites added after D44. (group, script, extra args) — see tests/run_all.py.
SUITES = [
    ("core", "mcp_server/test_storage.py", []),
    ("enterprise", "enterprise/test_enterprise.py", []),
    ("enterprise", "mcp_server/test_server_tools.py", []),
    ("js", "enterprise/test_parity.py", []),
    ("js", "studio/core/core.test.js", []),
    ("postgres", "db/test_postgres.py", []),
    ("postgres", "@replay", []),
]
