VectorXR #21 one-session research presets. ALL experimental behavior defaults OFF if no settings file.

Close STALKER 2 completely before copying a preset.
Copy ONE preset file and RENAME IT to framegen-research.txt in:
  C:\Users\livs\AppData\Local\VectorXR\framegen-research.txt
Restart game after every swap.
A: stock max4, reserve0, stock scene clock; telemetry on.
B: stock max4, reserve0, experimental continuous release-phase CONTENT clock; pose clock remains stock.
C: max6 cap hysteresis, reserve0, stock content clock.
UEVR trace requires the separately built #21 UEVR DLL, and writes only when enabled via UEVR_WORLD_TRACE21=1.
Inspect VectorXR startup log for 'VectorXR #21 mode: A/B/C'.
One scene, 120Hz, 3 minutes per mode: slow head turning and sideways strafing past narrow objects.
No need to edit text; swap files only. Do not combine B and C during the initial test.
Stop/go AFTER log analysis: world-stamp interval P95 >=3ms warrants further dual-clock research; <=1ms stops hypothesis; middle inconclusive.
