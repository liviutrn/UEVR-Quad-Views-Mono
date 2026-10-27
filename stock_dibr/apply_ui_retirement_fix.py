#!/usr/bin/env python3
"""Fence the optional UI snapshot producer, independently of DIBR synthesis."""
from pathlib import Path
import sys
root = Path(sys.argv[1])
hp = root / 'src/mods/vr/D3D12Component.hpp'
cp = root / 'src/mods/vr/D3D12Component.cpp'
h = hp.read_text(encoding='utf-8')
c = cp.read_text(encoding='utf-8')
def replace_once(s, old, new, label):
    if s.count(old) != 1:
        raise RuntimeError(f'{label}: expected one anchor, found {s.count(old)}')
    return s.replace(old, new, 1)
h = replace_once(h, '    bool m_dibr_ui_alpha_captured_this_frame{};', '''    bool m_dibr_ui_alpha_captured_this_frame{};
    bool m_dibr_ui_alpha_recorded_this_frame{};
    struct DibrUiProducer {
        ComPtr<ID3D12Resource> resource{};
        ComPtr<ID3D12Fence> fence{};
        ComPtr<ID3D12CommandQueue> queue{};
        uint64_t value{};
    };
    std::vector<DibrUiProducer> m_dibr_ui_producers{};
    ComPtr<ID3D12CommandQueue> m_dibr_ui_frame_queue{};
    void retire_dibr_ui_producers();''', 'members')
h = replace_once(h, '            std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair = nullptr);', '''            std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair = nullptr,
            std::optional<std::function<void(d3d12::CommandContext&, d3d12::dibr_transaction::ExecuteResult)>> submission_result = std::nullopt);''', 'declaration')
c = replace_once(c, 'D3D12Component::~D3D12Component() {', '''void D3D12Component::retire_dibr_ui_producers() {
    for (auto& producer : m_dibr_ui_producers) {
        const auto completed = producer.fence ? producer.fence->GetCompletedValue() : 0;
        if (completed != UINT64_MAX && completed < producer.value) {
            // A queued UI copy may outlive both synthesis and this component.
            d3d12::dibr_transaction::retain_untracked_com_object(producer.resource.Get());
            d3d12::dibr_transaction::retain_untracked_com_object(producer.fence.Get());
            d3d12::dibr_transaction::retain_untracked_com_object(producer.queue.Get());
        }
    }
    m_dibr_ui_producers.clear();
    m_dibr_ui_frame_queue.Reset();
}

D3D12Component::~D3D12Component() {
    retire_dibr_ui_producers();''', 'destructor')
c = replace_once(c, '    m_dibr_ui_alpha_captured_this_frame = true;\n    return true;\n}\n\nbool D3D12Component::run_dibr_preview(', '    m_dibr_ui_alpha_recorded_this_frame = true;\n    return true;\n}\n\nbool D3D12Component::run_dibr_preview(', 'record flag')
c = replace_once(c, '    auto parameters = d3d12::DIBRPreview::Parameters{', '''    // A queue-local submission proof is required before the snapshot can be
    // sampled. If the hook switched queues, disable this optional pass.
    const auto hook = g_framework != nullptr ? g_framework->get_d3d12_hook().get() : nullptr;
    if (!hook || hook->get_command_queue() != m_dibr_ui_frame_queue.Get()) {
        m_dibr_ui_alpha_captured_this_frame = false;
    }
    auto parameters = d3d12::DIBRPreview::Parameters{''', 'queue check')
c = replace_once(c, '    m_dibr_ui_alpha_snapshot.Reset();\n    m_dibr_retired_ui_alpha_snapshots.clear();', '    retire_dibr_ui_producers();\n    m_dibr_ui_alpha_snapshot.Reset();\n    m_dibr_retired_ui_alpha_snapshots.clear();', 'reset')
c = replace_once(c, '    m_dibr_ui_alpha_captured_this_frame = false;\n    apply_dune_descriptor_cache_guard(vr);', '''    m_dibr_ui_alpha_captured_this_frame = false;
    m_dibr_ui_alpha_recorded_this_frame = false;
    m_dibr_ui_frame_queue.Reset();
    std::erase_if(m_dibr_ui_producers, [](const auto& producer) {
        return producer.fence && producer.fence->GetCompletedValue() >= producer.value;
    });
    apply_dune_descriptor_cache_guard(vr);''', 'frame start')
old = '''                                capture_dibr_ui_alpha_snapshot(device, commands, submitted_ui_texture);
                            });'''
new = '''                                capture_dibr_ui_alpha_snapshot(device, commands, submitted_ui_texture);
                            }, nullptr, nullptr,
                            [this](d3d12::CommandContext& commands, d3d12::dibr_transaction::ExecuteResult result) {
                                if (!m_dibr_ui_alpha_recorded_this_frame || !m_dibr_ui_alpha_snapshot) return;
                                using Result = d3d12::dibr_transaction::ExecuteResult;
                                if (result == Result::SubmittedUntracked) {
                                    // Execute happened but no retirement proof exists.
                                    d3d12::dibr_transaction::retain_untracked_com_object(m_dibr_ui_alpha_snapshot.Get());
                                    m_dibr_ui_alpha_snapshot.Reset();
                                    m_dibr_ui_alpha_snapshot_width = 0;
                                    m_dibr_ui_alpha_snapshot_height = 0;
                                    m_dibr_ui_alpha_snapshot_format = DXGI_FORMAT_UNKNOWN;
                                    return;
                                }
                                if ((result == Result::SubmittedTracked || result == Result::SubmittedTrackedNeedsPolling) &&
                                    commands.fence && commands.submission_queue) {
                                    m_dibr_ui_producers.push_back({m_dibr_ui_alpha_snapshot, commands.fence,
                                        commands.submission_queue, commands.fence_value});
                                    m_dibr_ui_frame_queue = commands.submission_queue;
                                    m_dibr_ui_alpha_captured_this_frame = true;
                                }
                            });'''
c = replace_once(c, old, new, 'capture callback')
c = replace_once(c, '''    std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair)
{''', '''    std::shared_ptr<uevr::stalker2_native::PairFrame> retained_stalker_pair,
    std::optional<std::function<void(d3d12::CommandContext&, d3d12::dibr_transaction::ExecuteResult)>> submission_result)
{''', 'definition')
c = replace_once(c, '''    texture_ctx->commands.execute();''', '''    if (submission_result) {
        const auto result = texture_ctx->commands.execute_checked();
        (*submission_result)(texture_ctx->commands, result);
    } else {
        texture_ctx->commands.execute();
    }''', 'submission')
hp.write_text(h, encoding='utf-8')
cp.write_text(c, encoding='utf-8')
print('Applied independent UI snapshot submission and retirement tracking')
