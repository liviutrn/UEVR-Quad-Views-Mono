# DuoView AFW beta-6 compatibility probe — NOT stereo

This Windows x64 diagnostic is separate from the game. It never alters or bundles `PDAFWPlugin.dll`.

Run in PowerShell using your own stock PureDark beta-6 DLL:

```powershell
.\AFWAbiProbe.exe "C:\full\path\PDAFWPlugin.dll"
```

This checks that the DLL loads and exports `InitDevice`, `InitFrameWarp`, and `EvaluateFrameWarp`.

**Optional, stronger check** after that passes:

```powershell
.\AFWAbiProbe.exe --device-smoke "C:\full\path\PDAFWPlugin.dll"
```

The second command creates a Direct3D 12 device/queue, then calls PureDark's `InitDevice` once **in this standalone process, not in STALKER 2**. An incompatible DLL could crash this diagnostic. Do not use it in the game if the test crashes.

Passing does **not** establish the `EvaluateFrameWarp` binary layout, plugin vtable methods, motion/depth correctness, GPU warp, or stereo. The diagnostic **never** calls `EvaluateFrameWarp` or changes the UEVR backend. The exact beta-6 DLL still needs an identified SHA256 hash (`Get-FileHash "C:\full\path\PDAFWPlugin.dll" -Algorithm SHA256`).

Credits: PureDark (closed AFW plugin); tig3rmast3r/Witcher3VR (MIT independent bridge design). No proprietary DLL or PureDark header is included or modified.
