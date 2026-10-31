# AFW binary interface preflight (NOT Stage 1 stereo)
This is a non-invasive Windows x64 diagnostic. It does **not** render, submit, warp, or call PureDark's functions.

In PowerShell run: \`.\AFWAbiProbe.exe "C:\full\path\PDAFWPlugin.dll"\`.

PASS confirms only that the external DLL can be loaded and its three named exports exist. It is **not** proof of runtime ABI layout, graphics interface vtable, GPU resource ownership, frame warping, or headset stereo. This does not authorize installing the stage as a VR mode.

Based on the independent MIT ABI bridge design by tig3rmast3r / Witcher3VR, and cross-checked against PureDark's public-facing AFW API. PureDark owns PDAFWPlugin.dll. No proprietary DLL or header is included or modified.
