# Tri-view B4: B3 + 2.10 local-origin compositor (Claude, 5 Nov 2026)

- HEADSET (Liviu, 5 Nov): artifact "UEVR-TriView-B1-4" (run 41239720583, commit 4c0ee7f = Tri-view B3) on STALKER 2 **2.06**: head tracking perfect, "like native stereo but with third view periphery". Log: mask=13 (roles 0,2,3), separate renderer calls, healthy.
- Known 2.10 difference (CAPTURE, Build 52): every isolated singleton render lands at (0,0) of its own texture; the compositor sampled at the atlas offset -> broken foveas on 2.10.
- This branch = 4c0ee7f + port of ChatGPT 1c8f275 (QuadViewD3D12.hpp: offsets 0 when the four sources are distinct textures) + matching WARP test (native targets hold content at local origin). Workflow still applies all ten Build 51 overlays + triview.
- Expectation: fixes 2.10. On 2.06 the foveas will now be sampled at the wrong place (2.06 honoured the rect) - use B1-4 for 2.06.
- Status: CI only until Liviu tests on 2.10.
