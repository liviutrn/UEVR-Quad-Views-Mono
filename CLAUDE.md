# Instructions for Claude sessions in this repo

## About the owner (Liviu)
- Not a programmer. Explain everything in plain words, keep steps few and simple.
- Only ask him to do something when there is no other way (for example clicking
  "Run workflow", downloading a build, testing in VR, pasting an error message).
- Tests every build himself in VR (STALKER 2, PSVR2, SteamVR/OpenXR, RTX 5070).
  He cannot compile anything locally. Builds come only from GitHub Actions.

## Team rules
- This is a team project. ChatGPT also works in this repo. Both of us can read,
  review and learn from each other's work. Collaboration is encouraged.
- Claude only pushes to branches named `claude/...`. Never push to `main`,
  `experiment/...`, `fix/...`, `review/...` or any other branch. Never force-push,
  never delete branches or files that were not created on a `claude/` branch.
- To build on ChatGPT's work, start a new `claude/` branch from its latest
  `experiment/ciNN-...` branch. Do not edit its branch. Explain differences in
  commit messages or in a note under `research/` so ChatGPT can read them.
- Do not touch the published releases (v182, v186.1) or the `build-182` branch.

## Be honest about evidence
Label every claim as one of: source-read only, CI-verified (compiles / WARP
tests pass), or headset-verified (Liviu tested it in VR). A green Actions run
does not prove the picture looks right in the headset. Do not say a build
works until the Actions run for that exact commit has finished green. Never
hide failures or call an unfinished build a success.

## How builds work
- Workflow: `.github/workflows/duoview-true-stereo-xr-v1.yml` (Windows build).
  It starts on push only for branches listed in the file, and has a manual
  "Run workflow" button (workflow_dispatch) that works on any branch.
- The build needs the private `joeyhodge/UESDK` through the repo secret
  `UEVR_SOURCE_TOKEN`. It cannot be built in Claude's sandbox, so the only real
  compile check is the Actions run.
- Claude's sandbox can list Actions runs and see which step failed, but cannot
  download the logs or artifacts (access is blocked). When a build fails, ask
  Liviu to paste the last ~40 lines of the failed step, or read the error
  messages the build scripts print.
- Build artifacts are downloaded by Liviu from the run's page (Actions tab).

## Where to read first
1. `README.md` and `RELEASE_NOTES_V186_GLAMARYE.md` (released mono DuoView).
2. `ciNN/README.md` for the newest builds (each one explains what changed and
   what to check in the headset). Newest are `ci74` to `ci77`.
3. `research/` for ChatGPT's reviews and findings.
4. `duoview/` for the older base code, `duoview/stereo/` for stereo work and
   `stock_dibr/` for the depth-capture code. `duoview/WORK_LOG.md` and the
   handoff files there are history.

## Commit style
End commits with the attribution lines Claude Code gives for the session.
