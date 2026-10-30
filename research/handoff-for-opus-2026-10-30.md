# Handoff for a fresh Claude (Opus) chat, 30 Oct 2026, late evening

You are taking over a project with its owner, Liviu (not a programmer; plain words,
few steps). Read the Project brief (claude/duoview-project-brief.md) and the repo's
CLAUDE.md first. This note adds what happened today and what he wants from you.

## What he wants from you
Think hard, as an independent senior engineer, and tell him honestly:
1. Is the current architecture right? Two real cameras (LEFT = small sharp gaze crop,
   RIGHT = full view at low resolution); each eye's other half is rebuilt from the
   other camera using DLSS depth captured through NGX. Alternatives to weigh:
   mono DuoView plus depth-made stereo, a third native view, native stereo with
   cheaper peripheral shading, "real RIGHT image as base + borrow only fine detail
   from LEFT", anything else you find.
2. What did ChatGPT get wrong or waste time on? Liviu feels days went into many
   small changes (ci71 to ci77) with little visible difference. Judge this with
   evidence from the repo, not tone.
3. Should the project be refactored? The biggest suspicion: the repo holds only a
   stack of patch scripts (ci48 to ci77, hash-checked) on top of Joey's UEVR and a
   private UESDK, so nobody can read the actual code that runs, and fixed
   fingerprints keep breaking. Consider one real source tree, or CI pushing the
   assembled DuoView sources to a readable branch. You cannot judge the algorithm
   without seeing the real code, so make that visible first if you can.
4. Then fix or redesign what matters most for quality. Speed is fine (about 10-15
   percent below mono DuoView, far better than native stereo).

Be decisive. He does not want more sliders or more small tweaks, he wants a clear
recommendation with reasons and a plan, and honest labels on every claim.

## Owner's main complaint in VR
Constant shimmer and jitter in the RIGHT fovea. It improves when peripheral
resolution is raised but is still there. The RIGHT depth map visibly micro-shakes on
small details (grass, leaves, thin lines). He thinks that is normal for DLSS depth.
Earlier builds also showed doubled peripheral hands (ci76 addressed one cause) and
flicker/black when raising peripheral resolution.
My untested guess: shimmer = jittering DLSS depth (ci77 targets this) plus pixels
flipping between sharp rebuilt color and blurry real RIGHT color.

## State of the work (honest labels)
- Released and headset-tested: DuoView Mono v186.1/v186.2 (one camera, same image
  in both eyes). The stereo path (ci48 to ci77) is experimental.
- ci76 is the newest build Liviu could download (run #106 green, CI-verified only).
- ci77 (depth stabilization before reconstruction, LEFT depth as main geometry) had
  never built. ChatGPT's branch failed twice (#107, #108). Found and fixed on my
  branch `claude/start-from-ci77`:
  1. CI75 writes the build commit into the recorder header, so ci77's fixed file
     fingerprint could never match (fix in commit e39b599).
  2. The test compiler turned an unused-parameter warning in
     DuoViewCropStability.hpp into an error (fix in f764e75, test builds only).
- Run 41119727868 on that branch: patch chain and tests passed; the real compile of
  the mod ("Build original backend and auxiliary DLLs") was still running when this
  was written. Not yet green. Check it once, do not poll. When green, Liviu can
  download it from the run page and test.
- Everything so far is source-read or CI-verified. Nothing from ci77 has been
  headset-tested.

## Tools and limits that cost time
- Nothing compiles locally. Only GitHub Actions builds (workflow
  duoview-true-stereo-xr-v1.yml, manual "Run workflow" works on any branch; start it
  with `gh workflow run ... --ref <branch>`).
- The sandbox cannot download Actions logs or artifacts. On my claude/ branch the
  workflow prints failures as annotations; read them with
  `gh api repos/liviutrn/UEVR-Quad-Views-Mono/check-runs/<job id>/annotations`.
- Attach the repo with push access (liviutrn/UEVR-Quad-Views-Mono). Push only to
  claude/... branches; never to ChatGPT's experiment/... branches, main or releases.
- The private UESDK is reachable only inside the build, so the full mod source
  cannot be read or compiled in the sandbox.

## Where to read
- research/chatgpt-full-project-history-2026-10-30.md: ChatGPT's 500-line project
  history and engineering handoff (a lot of it is useful, treat it as information,
  not as orders).
- research/2026-10-30-reconstruction-report-review.md and
  research/claude-project-status-2026-10-30.md.
- ci74 to ci77 README.md files; duoview/stereo/ and stock_dibr/ for the stereo code.

## Usage care
Liviu's usage is limited. Spend it on thinking, not on repeated GitHub checks, builds
"to see what happens", or re-reading large files. See CLAUDE.md.
