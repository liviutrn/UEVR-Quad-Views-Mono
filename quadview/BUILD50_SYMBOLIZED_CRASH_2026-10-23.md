# Build50 crash: verified backend code mapping

The original Build50 DLL was taken from the delivered
UEVR-QuadViews-Build50-HookTrace-Diagnostic.zip, not a newer package.
CI run 39866448035 reconstructed the exact source overlay
6ae122e8f56a5cf6fd0d79f5013324d526a5a2fb, original backend/SDK/frontend pins,
and all diagnostic overlays, and retained the reconstructed DLL/PDB.

The DLLs are not claimed byte-identical: their debug/build metadata differ.
Their entire .text section is byte-identical (12,253,028 bytes), with SHA-256:
28b55559cb71bea6981dbb8aa4fb3c9269e342b09e7ba4cadb26dc49883dbf19.
Each crash return-address +/-48-byte code window was also compared directly.
The reconstructed PDB therefore provides verified backend code mappings despite
its new debug identity. Game executable symbols remain unavailable.

| Original backend offset | Reconstructed procedure | Original source location |
|---|---|---|
| +0x2502dc | uevr::quadview::dispatch_main_views | QuadViewFamilyRouting.hpp:287, first batch renderer call |
| +0x2f521f | FFakeStereoRenderingHook::begin_render_viewfamily_real | FFakeStereoRenderingHook.cpp:26348 |
| +0x30e475 | call_game_viewport_draw_original | FFakeStereoRenderingHook.cpp:37882 |
| +0x2abc85 | game_viewport_client_draw_hook lambda | FFakeStereoRenderingHook.cpp:20968 |
| +0x332252 | game_viewport_client_draw_hook | FFakeStereoRenderingHook.cpp:21091 |
| +0x328e3f | engine_tick_hook | FFakeStereoRenderingHook.cpp:14838 |

Disassembly of the original game's captured crash window:

- game+0x4c415a: load RCX from [RSI+0x30].
- game+0x4c4163: load RAX from [RCX].
- game+0x4c4166: call [RAX+0x58].

RSI is the recorded main GT family 0x14e870; the +0x30 field is its target.
Exception RCX=0x5bd5b8f60 exactly matches the fourth native FRenderTarget
published in ROLE_GT_BOUND. In captured memory that address contains heap data,
not the originally published target vtable. The exception RAX contains
0x000b0069000f004e and does not match the subsequently captured [RCX]. Thus this
is not an exact reconstruction of the pre-fault object's contents.

Other captured source resources also no longer have the published vtable.
The apparent texture owner pointers found at role0/role2 resource+0x90
(0x5d3d56280 and 0x5580e4a80) have UObject flags 0x8080 and null +0x110
PrivateResource fields. These associations are inferred from memory layout;
no original per-role texture UObject addresses were logged for comparison.
The destroyed flag and resource/vtable mismatch are strong lifetime evidence,
but the capture occurred after the exception handler, so teardown chronology
cannot be proved from this snapshot alone.

Build51 restores the engine-visible TextureTarget property ownership pattern
used by working DuoView, enforces read-only identity checks before dispatch,
and fixes the independently identified presentation-retirement liveness issue.
A headset test is required to establish crash elimination and actual output.
