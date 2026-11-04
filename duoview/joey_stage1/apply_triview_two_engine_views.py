#!/usr/bin/env python3
"""Experiment: render the third texture through an extra Native Fix renderer call,
without requesting or constructing a third Unreal engine view.

Run AFTER apply_triview_stage1.py. Every replacement is guarded; the stock backend
and the working Mono modes remain untouched by this experiment.
"""
from pathlib import Path
import argparse
import hashlib
import json

HOOK = "src/mods/vr/FFakeStereoRenderingHook.cpp"
VR_HPP = "src/mods/VR.hpp"

def replace_exact(source, before, after, label):
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact anchor, found {count}")
    return source.replace(before, after, 1)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def apply(backend, evidence):
    hook_file = backend / HOOK
    vr_file = backend / VR_HPP
    hook = hook_file.read_text(encoding="utf-8-sig")
    vr = vr_file.read_text(encoding="utf-8-sig")

    # No engine index 2 is ever requested by this variant. Keep Joey's original
    # one-based stereo index heuristic intact, including for any legacy index 2.
    vr = replace_exact(vr,
        """    bool triview_owns_view_index_two() const {
        return is_triview_active() ||
            (is_triview_selected() && m_triview_owns_index_two.load(std::memory_order_acquire));
    }""",
        """    bool triview_owns_view_index_two() const {
        // This prototype never asks Unreal for index 2; leave Joey's legacy indices alone.
        return false;
    }""",
        "VR.hpp engine index-2 policy")

    # Target creation is still initiated from GetDesiredNumberOfViews, but never
    # allow it to change the number of engine views away from Joey's validated 2.
    hook = replace_exact(hook,
        """            vr->note_triview_views_demanded();
            if (uevr::triview::diag::armed.load()) { SPDLOG_INFO("[TriDiag] GetDesiredNumberOfViews -> 3"); }
            return 3;""",
        """            if (uevr::triview::diag::armed.load()) {
                SPDLOG_INFO("[TriDiag] GetDesiredNumberOfViews -> 2 (third target ready; separate GPU renderer call)");
            }
            return 2;""",
        "GetDesiredNumberOfViews third-view gate")

    # Replace the 3->2 engine-view hiding trick. Select the SAME real right-eye
    # FSceneView that Joey just rendered. Reusing it for the proof avoids creating
    # or modifying a private-SDK FSceneViewState and cannot change UE's two-eye
    # construction. It is deliberately not the finished independent-periphery view.
    start_marker = "    // Tri-View ID7: the engine built a third (centre periphery) view."
    end_marker = "    using SceneViewsArrayPtr = decltype(view_family->get_views());"
    if hook.count(start_marker) != 1:
        raise RuntimeError("Existing 3-view family block anchor missing/ambiguous")
    start = hook.index(start_marker)
    end = hook.find(end_marker, start)
    if end < start or end - start > 6000:
        raise RuntimeError("Existing 3-view family block bounds are unsafe")
    old_block = hook[start:end]
    if ("family_views->count != 3" not in old_block or
            "family_views->count = 2" not in old_block or
            "triview_restore_count" not in old_block):
        raise RuntimeError("Existing 3-view block no longer matches the reviewed implementation")
    new_block = """    // Third-render proof: Unreal builds exactly TWO views. Do not hide or fabricate views.
    // Re-render the already validated real right-eye view into the independent third target.
    // Its capture occurs AFTER the original right-eye Native Fix render, before publication.
    sdk::FSceneView* triview_third_view{};
    sdk::FSceneViewFamily* triview_family{};
    bool triview_rendered{};
    std::shared_ptr<const VRRenderTargetManager_Base::TriViewTargetSnapshot> triview_used_target{};
    if (native_stereo_fix_enabled && vr->is_triview_active() && vr->triview_third_view_enabled()) {
        const auto* const triview_main_target = rtm != nullptr ? rtm->get_view_family_render_target() : nullptr;
        for (const auto family : view_families) {
            if (family == nullptr || triview_main_target == nullptr ||
                family->get_render_target() != triview_main_target) { continue; }
            auto* const family_views = family->get_views();
            if (family_views == nullptr ||
                !is_readable_process_range(reinterpret_cast<uintptr_t>(family_views), sizeof(*family_views)) ||
                family_views->count != 2 || family_views->capacity < 2 || family_views->data == nullptr ||
                !is_readable_process_range(reinterpret_cast<uintptr_t>(family_views->data), sizeof(void*) * 2)) {
                continue;
            }
            auto* const right = family_views->data[1];
            if (right == nullptr || right == family_views->data[0]) { continue; }
            triview_third_view = right;
            triview_family = family;
            break;
        }
    }

"""
    hook = hook[:start] + new_block + hook[end:]
    hook = replace_exact(hook,
        """        // Tri-View: render the hidden centre view exactly like Joey's secondary above (frame-count
        // decrement, singleton family), but into the periphery's own render target at (0,0).""",
        """        // Proof: re-render the already validated real right-eye view as a separate third GPU
        // renderer call (no third Unreal view, no new camera, no third scene view state).""",
        "Third renderer documentation")
    hook = replace_exact(hook,
        """    if (triview_third_view != nullptr && triview_family == view_family && vr->is_triview_active()) {""",
        """    if (triview_third_view != nullptr && triview_family == view_family && vr->is_triview_active() &&
        vr->triview_third_view_enabled()) {""",
        "Third renderer enable guard")

    # Prevent incomplete file writes if any anchor fails.
    hook_file.write_text(hook, encoding="utf-8", newline="")
    vr_file.write_text(vr, encoding="utf-8", newline="")
    evidence.mkdir(parents=True, exist_ok=True)
    manifest_path = evidence / "triview-stage1-hashes.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for path in (HOOK, VR_HPP):
        if path not in manifest["backend"]:
            raise RuntimeError(f"Expected source hash missing for {path}")
        manifest["backend"][path] = digest(backend / path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    state = {"variant": "two-engine-views + third renderer call / same right-eye FSceneView proof",
             "files": {path: digest(backend / path) for path in (HOOK, VR_HPP)}}
    (evidence / "triview-two-engine-third-render.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print("Two-engine-view proof patched; third eye is a third renderer call, not a third UE view.")

def verify(backend, evidence):
    state = json.loads((evidence / "triview-two-engine-third-render.json").read_text(encoding="utf-8"))
    for rel, sha in state["files"].items():
        if digest(backend / rel) != sha:
            raise RuntimeError(f"Two-engine-view source changed after patch: {rel}")
    hook = (backend / HOOK).read_text(encoding="utf-8")
    vr = (backend / VR_HPP).read_text(encoding="utf-8")
    for required in ("GetDesiredNumberOfViews -> 2 (third target ready", "family_views->count != 2",
                     "triview_third_view = right;", "views.data[0] = triview_third_view;"):
        if required not in hook:
            raise RuntimeError(f"Missing third-pass contract: {required}")
    if "GetDesiredNumberOfViews -> 3" in hook or "family_views->count = 2" in hook:
        raise RuntimeError("Old three-engine-view path remains active")
    if "return false;\n    }" not in vr:
        raise RuntimeError("Index-2 hook is not disabled")
    print("Two-engine-view third render source-contract verified.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("backend", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    (verify if args.verify else apply)(args.backend, args.evidence)
