VectorXR #21 one-session A/B/C/D research presets.

Close STALKER 2 completely before changing presets.
Copy ONE of A/B/C/D and RENAME the copied file to framegen-research.txt in:
  C:\Users\livs\AppData\Local\VectorXR\framegen-research.txt
Restart STALKER 2 between runs; no need to edit any text or copy log files.
Check startup log for "VectorXR #21 mode", with all individual switches.

A: stock Max4/Reserve0, stock content clock; telemetry ON.
B: Max4/Reserve0; experimental mean-adjusted continuous release-phase content clock; stock headset pose and exact gate.
C: Max6, cap hysteresis, Reserve0; stock content clock.
D: Max6, fixed game-release cadence 6 refreshes @120Hz = target 20 real FPS, Reserve0, stock content clock.
    Only meaningful if the game reliably holds 20 FPS; below 20 FPS, locking cannot fix missed frames.
A/B/C/D: UEVR research trace enabled in matching UEVR #21 DLL.

All experimental behavior is OFF without settings; never enable B+C+D simultaneously on initial test.
Same TriView 120Hz scene, ~3 min per mode; slow head turn and lateral strafe past poles.
Both UEVR and VectorXR make UNIQUE timestamped and mode-labelled CSVs automatically
in %LOCALAPPDATA%\VectorXR\; no manual saving between runs.
No mode is confirmed better until real content-timing data and headset notes are compared.
