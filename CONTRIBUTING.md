# Contributing

`main` is protected: changes land through a pull request, and both CI legs
(`test (3.11)` and `test (3.12)`) must pass before it can merge. Direct pushes to
`main` are blocked for everyone, including admins.

## Workflow

```bash
git checkout -b my-change
# ...edit...
python3 run.py            # optional: eyeball the five apps locally
# run the suite before pushing:
python3 mcp_server/token_budget.py --validate \
  && python3 mcp_server/traceability.py \
  && python3 mcp_server/scenario.py \
  && for t in governance/test_store enforcement/test_enforce signal/test_conformance \
              dashboard/test_rollup audit/test_audit_chain audit/test_anchor \
              governance/test_retention governance/test_taskedit governance/test_authoring \
              governance/test_binding maps/test_mapdata advisor/test_advisor \
              ask/test_agent test_run; do python3 "$t.py" || break; done

git commit -am "…"
git push -u origin my-change
gh pr create --fill       # CI runs on 3.11 + 3.12; merge when both are green
```

See [`MANUAL.md`](MANUAL.md) for setup and per-suite expectations, and
[`DECISIONS.md`](DECISIONS.md) for the rationale behind each piece.

## Ground rules

- Every feature is real or an explicitly declared, auth-gated stub — never
  silently faked. Keep it that way.
- Add assertions with new behavior; the suite is the contract.
- Standard library only for the core engine; `mcp` / `tiktoken` / `jsonschema`
  are for the server, harness, and apps.
