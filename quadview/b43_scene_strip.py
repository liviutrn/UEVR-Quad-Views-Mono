"""B43 helper for older shader-freeze tests: remove the extra-wide sharpen block
that B43 adds to ScenePixel, so the rest of ScenePixel is still compared exactly."""

def strip_b43(scene):
    pre = '        const float3 unsharpened = focus.rgb;\n'
    parts = scene.split('        // B43 extra-wide', 1)
    assert scene.count(pre) == 1 and len(parts) == 2, 'B43 ring block missing'
    scene = parts[0] + parts[1].split('        }\n', 1)[1]
    return scene.replace(pre, '', 1)
