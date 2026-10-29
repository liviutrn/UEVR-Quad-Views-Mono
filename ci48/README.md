# Build48 Windows CI input

Upload the exact `payload.b64` from the CI48 upload kit into this directory, and commit it on this experimental branch (never `main`). The workflow triggers from the `ci48/payload.b64` push. The payload is a compressed, hash-guarded Build45→Build48 source patch and adversarial tests; it contains no SDK secrets or personal game logs.

**No new DLL exists until the full Windows GitHub Actions workflow completes successfully.** Keep Build45 as rollback.

Build CI: https://github.com/liviutrn/UEVR-Quad-Views-Mono/actions/workflows/duoview-true-stereo-xr-v1.yml
