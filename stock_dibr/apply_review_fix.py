"""Apply the independent review corrections after the R3 overlays."""
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()


def edit(path, old, new):
    target = root / path
    source = target.read_text()
    if source.count(old) != 1:
        raise RuntimeError(f"{path}: expected one review anchor, got {source.count(old)}: {old[:100]}")
    target.write_text(source.replace(old, new))


shader = "src/mods/vr/d3d12/DIBRPreview.cpp"
edit(shader,
     "float2 ReprojectSourceUv(float2 source_uv, float raw_depth) {",
     "float2 ReprojectSourceUv(float2 source_uv, float raw_depth, float reprojection_strength) {")
edit(shader,
     "    return float2(target_ndc.x * 0.5f + 0.5f, 0.5f - target_ndc.y * 0.5f);",
     """    const float2 target_uv = float2(target_ndc.x * 0.5f + 0.5f, 0.5f - target_ndc.y * 0.5f);
    // Strength changes the mapping being solved, rather than the solver gain.
    // Multiplying each correction by strength made strength=2 undo the first
    // iteration on a constant-depth plane and collapse stereo back to zero.
    return lerp(source_uv, target_uv, reprojection_strength);""")
edit(shader,
     "ReprojectSourceUv(source_uv, source_depth)",
     "ReprojectSourceUv(source_uv, source_depth, reprojection_strength)")
edit(shader,
     "const float2 candidate = source_uv + correction * reprojection_strength;",
     "const float2 candidate = source_uv + correction;")
edit(shader,
     "    float2 synthesized_source_uv,\n    uint source_clamped,",
     "    float2 synthesized_source_uv,\n    float reprojection_strength,\n    uint source_clamped,")
edit(shader,
     "ReprojectSourceUv(synthesized_source_uv, source_depth)",
     "ReprojectSourceUv(synthesized_source_uv, source_depth, reprojection_strength)")
edit(shader,
     "            synthesized_source_uv,\n            source_clamped,",
     "            synthesized_source_uv,\n            reprojection_strength,\n            source_clamped,")

print("Applied independent review correction: monotonic DIBR strength and matching spatial-repair mapping")
