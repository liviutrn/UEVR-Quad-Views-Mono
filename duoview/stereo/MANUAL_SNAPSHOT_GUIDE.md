# DuoView V3 split-eye — automatic color + depth captures

The new manual capture mode builds on V3 commit `26b1b412` and R5 depth capture. Existing source rendering and XR output are **unchanged**. No stereo synthesis.

## Workflow

1. Run the new experimental ZIP from a **separate** UEVR directory.
2. In STALKER 2 select **DuoView ID6**, Split-Eye ON (left-eye fovea, right-eye periphery). Enable **R5 DSV/RDG capture in DuoView**. Exit and re-enter ID6 after enabling.
3. Go outside, face a scene with foreground and background structures, open the UEVR DuoView menu, press **CAPTURE NOW: both source colors + ALL eligible depth candidates**. Continue playing; GPU readback and file writing happen asynchronously.
4. Go inside and repeat. Press again at a doorway, near a weapon/character or foliage. Each press creates a **separate** numbered folder; it never overwrites previous captures.
5. Open Windows Run (**Win+R**) and enter `%TEMP%\UEVR_DuoViewCaptures`.
6. Zip the complete `capture_*` folders together and send the ZIP. Do not send only screenshots: the `.raw` files preserve exact depth values needed to check perspective and reversed-Z.

## Files in each session

- `image_0_left_fovea.bmp` and `.raw`: genuine UE0/left-eye cropped-source color **allocation**.
- `image_1_right_periphery.bmp` and `.raw`: genuine UE1/right-eye low-resolution peripheral-source color **allocation**.
- `image_2_depth_..._depth_preview.bmp`, etc: automatically contrast-normalized depth previews for fast visual screening.
- Corresponding `depth_*.raw`: untouched raw depth-plane bytes, dimensions and DXGI format documented in `manifest.json`.
- `manifest.json`: packet/draw/generation, camera positions and crop; GPU DSV/viewport provenance inventory, image sizes and formats, missing/unsupported/over-budget captures.

## Evidence limits

The GPU submission/copy protocol confirms the readbacks, but **the depth buffer's actual camera/view association remains unproven** until pixel-wise alignment against the two color sources is examined. The two color allocations can contain unused areas: the active foveal and peripheral rectangles are documented separately in frame metadata.

The capture budget is deliberately bounded to **512 MiB of GPU readback per user trigger**, at most **48** eligible R5 depth captures per frame, with a catalogue of up to **256** observed DSV resources. Stock capture behavior remains 12 per frame outside manual captures. These caps prevent unbounded allocation on your VR runtime; an excess is marked in the manifest rather than silently omitted. This is not a guarantee of *literally every* depth resource ever created by UE5, only a bounded capture of eligible submitted candidates plus a broad DSV inventory.

Do not use the diagnostic BMP contrast values as linear view distance; raw depth could be reversed-Z and must be interpreted using the correct view matrices.

After inspection we'll implement exact per-view capture attribution and a depth-aware L→R foveal reconstruction shader.
