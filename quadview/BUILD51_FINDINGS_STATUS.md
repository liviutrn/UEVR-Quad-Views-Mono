# Build51: source lifetime and presentation setup

Build50 crashed and has no verified headset output. This revision is a test
candidate, not a production release. Build40 remains the last visually working
reference. Stable DuoView files and the original backend/SDK/frontend pins are
unchanged.

## Evidence from the supplied crash

ID7 activated at 00:19:42.039. All four RT roles matched; native RHI execution
was accepted. The GameThread fault followed at 00:19:56.988. Source/copy/XR
output markers were absent. Their absence alone does not prove nonexecution.

The exception's RCX (0x5bd5b8f60) equals the logged fourth source FRenderTarget.
The game instruction loads the family target at +0x30, then calls virtual slot
+0x58. In the captured memory this address contains unrelated-looking heap
pointers. Two other source addresses no longer contain their originally
published vtable. Captured associated texture objects have flags 0x8080 and a
null PrivateResource; 0x8000 is BeginDestroyed in the engine object flags.
The exception registers and later captured memory disagree, so this is evidence
of unsafe target lifetime, not a fully symbolized proof of the original fault.

## Implementation changes

1. Each of the four textures is now referenced through the same world actor ->
   scene capture component -> TextureTarget property chain used by working
   DuoView Native Fix. The components are configured invisible, with both
   capture-every-frame and capture-on-movement disabled before registration.
   They only hold references; the existing four singleton renderer calls still
   produce the sources. C++ weak references/COM resource references no longer
   stand in for this engine object ownership.
2. The existing packet/target-set lease retains these holders. GT cleanup only
   detaches and destroys the holders after CPU leases and the existing GPU fence
   have retired. Before dispatch and every singleton, read-only checks reject
   destroyed objects, changed PrivateResource/RHI identities, or changed hook
   vtables. An invalid set is retired; a later draw may create a replacement.
3. D3D12 setup now waits for presentation copy/compositor/UI fences rather than
   a continually replenished set of engine producer tickets. Mode changes still
   default to full engine retirement and retain the separate GT commit check.
   No engine delivery ledger is cleared by presentation setup.
4. Bounded PRESENT_ENTER/PRESENT_RETURN/NATIVE_COMPLETION diagnostics identify
   pre-copy exits and actual quartet completion; unfilled RHI masks from Build50
   must not be interpreted as measured zeros.

## Validation boundary

Portable retirement tests reproduce the old continually-pending engine-ticket
condition and check that presentation can initialize while full mode transitions
remain blocked. GPU fences still independently block presentation reset. Packet
leases retain target owners until explicit delivery retirement. Windows CI must
compile the real adapters and run the existing CPU/WARP/compatibility suites.
The package must include source/binary identity and exact backend PDB artifacts.
No offline test establishes headset brightness/FOV/gaze stability or proves the
15-second crash is eliminated. Headset acceptance is still required.
