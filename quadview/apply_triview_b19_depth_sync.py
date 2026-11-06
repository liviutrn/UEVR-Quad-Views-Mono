#!/usr/bin/env python3
"""TriView B19: consume submitted in-flight NGX depth with a GPU-side queue fence.

Apply AFTER all B18 production parity tests. The B18 canonical header remains
untouched so its production/test parity gate still exercises the B18 baseline.

This repairs the observed 'foreign_queue=submitted' starvation. It does NOT
authenticate the DLSS evaluation to a particular UE scene frame.
"""
from pathlib import Path
import sys


def once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"B19 {label}: expected 1 anchor, got {count}")
    return source.replace(old, new, 1)


def patch_depth(source: str) -> str:
    return once(
        source,
        "                (!slot->foreign_queue || depth_copy_complete(completed, slot->producer_fence_value)) &&\n",
        "                // Submission plus a valid signal makes a foreign copy eligible.\n"
        "                // The compositor inserts a GPU-side Wait BEFORE executing its draw.\n"
        "                slot->producer_fence && slot->producer_fence_value && completed != ~uint64_t{} &&\n",
        "submitted foreign depth selection")


def patch_d3d12(source: str) -> str:
    return once(
        source,
        "    std::shared_ptr<const void> keepalive{};\n",
        "    // The lease keeps both this fence and its depth texture alive through\n"
        "    // the compositor's own completion fence. Cross-queue waits are GPU-side.\n"
        "    ComPtr<ID3D12Fence> producer_fence{};\n"
        "    uint64_t producer_fence_value{};\n"
        "    bool foreign_queue{};\n"
        "    std::shared_ptr<const void> keepalive{};\n",
        "depth synchronization fields")


def patch_consumer(source: str) -> str:
    source = once(
        source,
        "                                    depth_input.keepalive=snapshot;\n",
        "                                    depth_input.producer_fence=snapshot->producer_fence;\n"
        "                                    depth_input.producer_fence_value=snapshot->producer_fence_value;\n"
        "                                    depth_input.foreign_queue=snapshot->foreign_queue;\n"
        "                                    depth_input.keepalive=snapshot;\n",
        "forward producer fence")

    wait = """                                    // B19: the game is executing DLSS depth copies on a
                                    // different DIRECT queue. Polling the CPU fence in B18
                                    // missed approximately half the depth frames in the
                                    // user's live log. Queue a GPU wait instead.
                                    // OpenXR's CommandContext executes on this same queue
                                    // AFTER this callback, so Wait precedes sampling.
                                    auto synced_depth=depth_input;
                                    if (synced_depth.texture && synced_depth.foreign_queue) {
                                        const uint64_t completed=synced_depth.producer_fence
                                            ? synced_depth.producer_fence->GetCompletedValue() : ~uint64_t{};
                                        bool safe=completed!=~uint64_t{} && synced_depth.producer_fence_value!=0;
                                        if (safe && completed < synced_depth.producer_fence_value) {
                                            const auto& queue_hook=g_framework->get_d3d12_hook();
                                            auto* queue=queue_hook ? queue_hook->get_command_queue() : nullptr;
                                            safe=queue && SUCCEEDED(queue->Wait(
                                                synced_depth.producer_fence.Get(),synced_depth.producer_fence_value));
                                            if (safe) {
                                                static std::atomic<uint64_t> queued_waits{0};
                                                const auto count=queued_waits.fetch_add(1,std::memory_order_relaxed)+1;
                                                SPDLOG_INFO_EVERY_N_SEC(5,
                                                    "[TriView][DepthSync] GPU-side cross-queue waits queued={} (no CPU blocking)",count);
                                            }
                                        }
                                        if (!safe) {
                                            // A failed Wait must NEVER expose an in-flight texture.
                                            synced_depth.texture=nullptr;
                                            synced_depth.reproject=false;
                                            SPDLOG_WARNING_EVERY_N_SEC(2,
                                                "[TriView][DepthSync] fence invalid/Wait failed; homography-only fallback");
                                        }
                                    }
"""
    source = once(
        source,
        "                                    recorded=comp.record_sources(commands.cmd_list.Get(),native_sources,destination,\n",
        wait + "                                    recorded=comp.record_sources(commands.cmd_list.Get(),native_sources,destination,\n",
        "queue wait before compositor recording")
    source = once(
        source,
        "                                        (depth_input.texture || depth_input.show) ? &depth_input : nullptr);",
        "                                        (synced_depth.texture || synced_depth.show) ? &synced_depth : nullptr);",
        "use synchronized input only")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_triview_b19_depth_sync.py <backend>")
    root = Path(sys.argv[1]) / "src/mods/vr"
    operations = {
        root / "QuadViewNgxDepth.hpp": patch_depth,
        root / "QuadViewD3D12.hpp": patch_d3d12,
        root / "D3D12Component.cpp": patch_consumer,
    }
    transformed = {p: fn(p.read_text(encoding="utf-8")) for p, fn in operations.items()}
    for path, changed in transformed.items():
        path.write_text(changed, encoding="utf-8", newline="\n")
    print("B19: GPU queue Wait before composite; no CPU polling of in-flight foreign depth")


if __name__ == "__main__":
    main()
