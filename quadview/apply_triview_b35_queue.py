#!/usr/bin/env python3
"""B35: pin QuadView submissions to the queue used while recording.

Run after the QuadView consumer overlay. Other CommandContext submissions keep
using the existing hook-queue lookup.
"""
from pathlib import Path
import sys


def once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"B35 {label} anchor count {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def main():
    root = Path(sys.argv[1]) / "src/mods/vr"
    header_path = root / "d3d12/CommandContext.hpp"
    source_path = root / "d3d12/CommandContext.cpp"
    dx_path = root / "D3D12Component.cpp"

    header = header_path.read_text(encoding="utf-8")
    source = source_path.read_text(encoding="utf-8")
    dx = dx_path.read_text(encoding="utf-8")
    if any("seam_submission_queue" in text for text in (header, source, dx)):
        raise RuntimeError("B35 queue pin overlay already applied")

    header = once(header, "    void execute();", '''    void execute();

    // Optional queue captured by a callback that records cross-slot GPU state.
    // execute() consumes this reference for one submission; all other callers
    // continue to use the D3D12 hook's current queue.
    ComPtr<ID3D12CommandQueue> seam_submission_queue{};''', "CommandContext declaration")

    source = once(source, '#include <string_view>', '#include <string_view>\n#include <utility>',
                  "standard utility include")
    source = once(source, '''void CommandContext::execute() {
    std::scoped_lock _{this->mtx};

    if (this->poisoned || !this->ready()) {''', '''void CommandContext::execute() {
    std::scoped_lock _{this->mtx};
    // Pin and consume the optional queue before closing/submitting. Keep this
    // ComPtr alive through both ExecuteCommandLists and the fence Signal.
    auto command_queue = std::exchange(this->seam_submission_queue, ComPtr<ID3D12CommandQueue>{});

    if (this->poisoned || !this->ready()) {''', "execute queue capture")
    source = once(source, "        auto command_queue = g_framework->get_d3d12_hook()->get_command_queue();",
                  "        if (!command_queue) command_queue = g_framework->get_d3d12_hook()->get_command_queue();",
                  "execute fallback")

    dx = once(dx, '                                    auto& comp=*found->second;', '                                    auto& comp=*found->second;\n                                    // Temporal history is updated only on its retained queue.\n                                    // Other seam modes preserve the original dynamic queue path.\n                                    const auto seam_queue=frozen->settings.seam_mode==4 ? comp.edge_submission_queue() : nullptr;', "history submission queue")
    dx = once(dx, '                                    if (comp.commands_recorded()) commands.has_commands=true;', '                                    if (comp.commands_recorded()) {\n                                        commands.has_commands=true;\n                                        if (seam_queue) commands.seam_submission_queue=seam_queue;\n                                    }', "pin temporal list")

    header_path.write_text(header, encoding="utf-8", newline="\n")
    source_path.write_text(source, encoding="utf-8", newline="\n")
    dx_path.write_text(dx, encoding="utf-8", newline="\n")
    print("Applied B35 one-shot QuadView queue pinning.")


if __name__ == "__main__":
    main()
