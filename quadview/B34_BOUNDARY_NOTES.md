# B34: automatic spatial boundary brightness + RGB (B31-110 foundation)

Built directly from B31-110 `008c9f7548c43f5977c1197c4180cddb435c64de`, not from B32 or B33.

## The new automatic algorithm

* Reuse B31's existing compute pass: two eye groups, each gathering 128 patch samples near the true foveal boundary. Reuse its **same** 18 float4 correction records and one fence-retired compositor slot.
* New mode **Boundary B34** (3), preserving B31 Off/Manual/Adaptive (0/1/2) for A/B. New persistent UI keys start B34 in the new mode rather than inheriting a potentially stale B31 profile.
* Model separately the fovea/periphery **luminance ratio**, and the **red and blue residual after luminance correction** (green inferred to avoid shifting measured luminance). The RGB residual follows actual foveal color, including color-temperature differences.
* Segment-local estimates are confidence-gated, clipped, and spatially interpolated. Differences that are too large (probably disocclusion/occlusion rather than display-color mismatch) attenuate the correction instead of assigning arbitrary colors.
* Apply the correction near the foveal boundary, with a **smooth outward falloff** (default 180 output pixels). All distant periphery pixels remain unchanged. The true stereo fovea core is entirely untouched. Only a narrow optional **inward blend** (default 12 output pixels) trades a thin strip of detail for seam continuity.
* Analysis observes the actual current-eye source textures, including NR-before-SR on foveas. No new Unreal view, CPU-GPU readback, GPU fence polling, mutex, shadow history, texture, render pass, or D3D12 resource-allocation path.
* Default: strength .95, gain cap +/- .40, chroma .80, segment influence .90, outward reach180px, inward feather12px; fully adjustable in UEVR's original seam menu.

## Performance and simulation
An offline synthetic 512x512 RGB scene with a smooth lighting gradient and warm foveal shift showed approximately 68% lower boundary color error for this *type* of bounded RGB/luminance model (.03918 -> .01247 mean RGB absolute mismatch). This was a mathematical prototype, NOT validation against exact uploaded user screenshots or the compiled HLSL.

At 1810x1440 output and a 50% foveal crop, a 180px outward band covers ~27.4% of the output versus the ~75% of pixels that B31's global match could affect. It is a theoretical *processing-footprint* comparison, not measured GPU performance. B34 retains B31's same compute dispatch with somewhat more arithmetic per 16-sample model and may be faster/slower in real hardware. Windows WARP verifies production pixel behavior.

## Safety and limitations
No claim that the seam is mathematically invisible or never flickers: stereo geometry, depth disocclusion, NR temporal effects, lighting/shading differences and changing frame content can leave visible residuals. Stateless response avoids introducing new temporal synchronization and cross-frame history failures, but cannot guarantee zero time-dependent correction fluctuation.

B31 underlying engine-registration 16-slot capacity and source role-3 D3D12 mismatch failure remain unmodified, and B34 does not resolve them. Do not stress runtime reset or resize in the first headset test. Always keep B28/B31 rollback binaries.

Tests: original B31 anti-vignette and WARP, new B34 WARP boundary/neutral/determinism, CI FXC /WX, sanitizer and backend compatibility.
