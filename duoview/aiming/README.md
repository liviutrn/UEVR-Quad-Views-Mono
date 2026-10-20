# STALKER 2 mouse aiming — isolated projection POC

**Status: tested projection math, NOT an injectable VR fix yet.**

The mouse controls the game's shot ray. Headset rotation/translation changes
the actual rendered camera view. A crosshair fixed at the center of the headset
is therefore misleading; this module projects a game-provided firing impact
point (or approximate ray endpoint) into the **same producer-frame camera**.

## Remaining connection points

1. Obtain **the actual shot ray or hit point** from STALKER 2 weapon/gameplay
   logic. Controller ControlRotation alone does not prove ballistic alignment,
   particularly under ADS, sway, recoil or projectile drop.
2. Obtain the **frozen Mono source view-projection matrix** used by that exact
   DuoView source frame, including HMD pose, offsets and ADS zoom.
   Convert its matrix storage convention into this module's row-major VP form.
3. Associate ray and matrix with the same immutable DuoView frame generation;
   reject stale/mismatched samples rather than holding a false crosshair.
4. Render the computed UV as a separate **optional** dot or reticle, in the
   composed image or dedicated OpenXR UI layer, not as a fixed HMD center dot.
   Hide while invalid, menus/cutscenes, or unsupported modes/games. Disable the
   game's original centered crosshair to avoid competing markers.
5. Retain default OFF, and do not change frame-delivery, gaze, rendering mode,
   lighting, fovea/periphery source poses or GPU synchronization.

The fallback ray is an angular approximation, not a weapon ballistic trace.
Camera VP and origin/direction must use the *same Unreal world units*.
The renderer/compositor integration is intentionally **not enabled**.

Test with a C++17 compiler:
```sh
g++ -std=c++17 -Wall -Wextra -Werror -pedantic AimReticleProjectionTests.cpp -o aimtest && ./aimtest
```

## Attribution

Original standalone math implementation. No modified or copied Remleo STALKER 2
profile is included (that profile uses CC BY-NC-ND 4.0). Reference: GPL UEVR
engine work in [Remleo/UEVR](https://github.com/Remleo/UEVR), and
[Joey's UEVR](https://github.com/joeyhodge/UEVR).

Headset/GPU testing and actual weapon-shot alignment have **not** occurred.
