# Project status as read by Claude (30 Oct 2026, evening)

Source: README, release notes, ci48-ci77 notes, duoview/ and stock_dibr/ docs,
ChatGPT's handoff and research review, branch history and the Actions run list.
Nothing here was tested in a headset by Claude. Claims are labeled.

## What the project is today

1. **Released and headset-tested: DuoView Mono (v186.1, mode ID 6).** One mono
   camera, two renders (small sharp center that follows the eyes, wide cheap
   edge), blended into one picture that both eyes show. No stereo depth.
   Pinned to Joey Hodge's UEVR. PSVR2 eye tracking through the PSVR2 Toolkit.
2. **In development: synthesized stereo ("True Stereo XR", ci48 to ci77).**
   Two real renders per frame from two cameras about 6.4-7.2 cm apart:
   LEFT = small high-resolution crop where you look, RIGHT = whole field of view
   at low resolution. Each eye's missing half is built from the other camera's
   image using depth (the depth DLSS uses, captured through NVIDIA NGX hooks):
   LEFT eye = real sharp center + built wide edge, RIGHT eye = real low-res
   edge + built sharp center. Result: both eyes get a sharp center and a wide
   edge from only two game renders. This is where all current work happens.
3. The repo does not contain the whole mod. It holds patch scripts (ci48,
   ci49 ... ci77) that are applied one after another, on top of pinned copies
   of Joey's UEVR (5ac7edc), his private UESDK (3cffbc8) and his frontend
   (60be4b0), inside one Windows build in GitHub Actions. Each ciNN folder is
   one more layer.

## Where things stand

Headset-verified (by Liviu): v182/v186.1 mono DuoView ran smoothly in
STALKER 2. For the stereo builds, Liviu reported edge jitter, doubled
peripheral hands, and flicker or black output when raising the peripheral
resolution (ci76 notes).

CI-verified only (compiles and WARP software-GPU tests pass, not headset): ci74
jitter-mask fix (72,160 of 663,552 mask checks wrong before, 0 after), ci75
lossless recorder, ci76 owner selection and resize recovery.

Latest builds: ci76 run #106 is green (newest downloadable stereo build).
**ci77 runs #107 and #108 both failed**, in the step that applies the whole
patch chain and its tests. The last commit only fixed text encoding and the
build still failed. The error text is not readable from Claude's sandbox.

## Open problems

- ci77 does not build yet (need the error lines from the failed step).
- Edge shimmer and jitter; ci77 is the attempted fix, unproven.
- The depth, camera matrices and jitter seen through NGX are matched to the
  right view by shape and timing, not proven (both ChatGPT and the code notes
  say so). Dynamic objects and never-seen surfaces cannot be rebuilt.
- Hands and near objects: stereo is deliberately reduced inside 80 cm.
- No measured FPS for the stereo path. The mono "up to 50 percent" figure was
  extrapolated from GPU load, not measured uncapped.
- Research note (ChatGPT) lists fixes needed before trying its proposed new
  design (HSVR-L2): 16-bit float UV is too coarse, atomic depth selection can
  pick mismatched color, history needs surface checks, budgets are guesses.

## Suggested next steps

1. Get the ci77 failure text and fix the build.
2. Test ci76 in VR now, since it is the newest green build, and record what
   remains broken (use the recorder from ci75).
3. Build a replay/benchmark harness so strategies (ci71, ci72, ci73, ci77)
   are compared on identical input, as ChatGPT's review recommends.
4. Only after that, consider new reconstruction designs.
