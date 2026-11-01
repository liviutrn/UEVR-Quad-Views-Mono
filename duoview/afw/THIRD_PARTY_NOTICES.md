# DuoView AFW: third-party notices and credits

**Alternate Frame Warping (AFW)**
- Author: PureDark. Source: https://github.com/PureDark/UEVR, branch `AFW`.
- What DuoView uses:
  - `PDAFWPlugin.dll`. The user copies it from PureDark's own UEVR AFW release, beta 6. DuoView never modifies, bundles or redistributes it.
  - `PDAFWPlugin.h`, the public API header. The build downloads it from PureDark's repository at commit `fc8de1026622d42d0d1f76c3e9c8bb0d80b11035` and checks its SHA-256. It is not stored in this repository and is not packaged.
  - `duoview/afw/DuoViewAFW.cpp` ports PureDark's UEVR integration code: `src/mods/VR.cpp`, `src/mods/vr/D3D12Component.cpp`, `src/mods/vr/FFakeStereoRenderingHook.cpp` and the NGX declarations in `src/mods/vr/UpscaleHelper.hpp`, all at the same commit.
- Permission: PureDark to Liviu (Discord, 31 Oct 2026): OK for non-commercial use. PureDark to clarkcheekykent (Discord, 8 Oct 2026): "with proper credits I am fine with others using AFW in their mod".
- Conditions we follow: non-commercial only, PureDark credited, the DLL never modified.

**UEVR**
- UEVR by praydog (https://github.com/praydog/UEVR).
- The fork DuoView builds on is by Joey Hodge (https://github.com/joeyhodge/UEVR, pinned `5ac7edc`).

**witcher3-vr** (tig3rmast3r, MIT)
- Its clean-room AFW bridge was reviewed as a reference.
- Its code is not used: we compile against PureDark's own beta-6 header instead, so the AFW interface matches the DLL exactly.
