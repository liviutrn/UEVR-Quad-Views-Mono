# v208d optional VRAM options (UNVERIFIED in VR; compiled only by CI)
- New DuoView menu toggle "Skip unused depth swapchain" (default OFF = exact v208 behaviour).
- ON + DuoView ID6 active + "Enable Depth-based Latency Reduction" OFF + no AFR/DIBR: the OpenXR depth swapchain (2W x H, D32_S8, never written in DuoView) is not created. Expected saving: roughly 200 MiB per image at 4060x3228 (about 600 MiB for 3 images) - an estimate, not measured.
- Apply: tick the toggle, then press "Reinitialize Runtime" (or restart the game). The value is read only when swapchains are created.
- Read the effect: compare the in-game VRAM readout (used / budget / in system memory) with the toggle OFF vs ON, and the log line "[DuoView][VRAM] depth swapchain skipped (toggle ON; saves roughly N MiB per image)".
- If depth is needed later (rendering method changed with PassDepth ON), the existing depth recreate path builds the chain.
- Also new: log "[DuoView][VRAM] Native gather atlas ALLOCATED (N MiB)" and the menu line "Gather atlas allocated (since start): yes/no" (diagnostic only).
- NOT verified: real VRAM saving, runtime behaviour of every OpenXR runtime without a depth chain, any headset test. Only the patch anchors were replayed.
