# Build 52 v2 CI build request — 2026-11-01

This file intentionally triggers `.github/workflows/build52-auto-diagnostics.yml` by a push
to `experiment/build52-evidence-complete-20261101`, using the configured
`quadview/build52/**` path trigger.

Build outputs, if CI accepts this push, should include:
- UEVR-QuadViews-ID7-Build52-Compiled-<run>
- QuadView-Build52-Stereo-Evidence-<run>
- QuadView-Build52-Exact-Backend-Symbols

This file does **not** certify that a GitHub Actions job started or succeeded.
The Windows build additionally requires the repository's Epic-authorized
`UEVR_SOURCE_TOKEN` (or `PAT_TOKEN`) secret to fetch UESDK.

If no run starts, inspect repository Actions permissions and GitHub's handling
of commits made by the connector, then use a user-triggered Actions run.
