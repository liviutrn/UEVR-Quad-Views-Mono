"""Apply the guarded DIBR recording/submission transaction after review fixes."""
import pathlib
import shutil
import sys

root = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent


def edit(path, old, new):
    target = root / path
    source = target.read_text()
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one transaction anchor, got {count}: {old[:100]!r}")
    target.write_text(source.replace(old, new))


def replace_file(path, prepared, forbidden):
    target = root / path
    source = target.read_text()
    if any(marker in source for marker in forbidden):
        raise RuntimeError(f"{path}: transaction fix appears to be applied already or source is out of order")
    if not all(marker in source for marker in prepared):
        raise RuntimeError(f"{path}: expected R4 source anchors are missing")
    shutil.copyfile(here / "transaction_files" / pathlib.Path(path).name, target)


# These four sources are unchanged by the later adversarial hook overlay. Keep
# their complete, reviewed versions together so this stage stays reproducible.
replace_file("src/mods/vr/d3d12/CommandContext.hpp",
    ["    void execute();", "bool references_retired();"],
    ["execute_checked()", "DIBRTransaction.hpp"])
replace_file("src/mods/vr/d3d12/CommandContext.cpp",
    ["void CommandContext::execute() {", "bool CommandContext::try_wait() {"],
    ["CommandContext::execute_checked()", "untracked_submission = true"])
replace_file("src/mods/vr/d3d12/DIBRPreview.hpp",
    ["bool synthesize(", "m_output_has_been_written"],
    ["m_output_write_state", "DIBRTransaction.hpp"])
replace_file("src/mods/vr/d3d12/DIBRPreview.cpp",
    ["void DIBRPreview::stage_left_eye(", "m_output_has_been_written = true;"],
    ["m_output_write_state", "begin_after_preparation"])

shutil.copyfile(here / "DIBRTransaction.hpp", root / "src/mods/vr/d3d12/DIBRTransaction.hpp")

component_h = "src/mods/vr/D3D12Component.hpp"
edit(component_h,
    """    D3D12Component() 
        : m_openvr{this}
    {

    }
""",
    """    D3D12Component() 
        : m_openvr{this}
    {

    }
    ~D3D12Component();
""")
edit(component_h,
    """        d3d12::CommandContext commands{};
    };

    // Capture runs every frame.""",
    """        d3d12::CommandContext commands{};
        std::vector<ComPtr<ID3D12Resource>> in_flight_resources{};
        bool preview_recording_pending{};
        bool quarantined{};

        ~DIBRFrameSlot() {
            if (commands.references_retired() || commands.wait(2000)) {
                preview.abort_recording();
                preview.note_submission_retired();
                return;
            }

            commands.quarantine_untracked_objects();
            preview.quarantine_resources();
            d3d12::dibr_transaction::retain_untracked_com_object(present_tex.texture.Get());
            d3d12::dibr_transaction::retain_untracked_unique(present_tex.rtv_heap);
            d3d12::dibr_transaction::retain_untracked_unique(present_tex.srv_heap);
            for (auto& resource : in_flight_resources) {
                d3d12::dibr_transaction::retain_untracked_com_object(resource.Get());
            }
        }
    };

    // Capture runs every frame.""")

component_cpp = "src/mods/vr/D3D12Component.cpp"
edit(component_cpp,
    """}

const char* D3D12Component::shf_scene_mode_name(ShfSceneMode mode) {""",
    """}

D3D12Component::~D3D12Component() {
    const auto has_unretired_dibr_work = std::any_of(
        m_dibr_slots.begin(),
        m_dibr_slots.end(),
        [](auto& slot) {
            return !slot.commands.references_retired() && !slot.commands.wait(2000);
        });
    if (has_unretired_dibr_work) {
        // DIBR's final presentation pass references the shared SpriteBatch
        // pipeline and descriptors. Keep that owner alive if a slot cannot
        // establish retirement before the component itself is destroyed.
        d3d12::dibr_transaction::retain_untracked_unique(m_game_batch);
        d3d12::dibr_transaction::retain_untracked_unique(m_graphics_memory);
    }
}

const char* D3D12Component::shf_scene_mode_name(ShfSceneMode mode) {""")

edit(component_cpp,
    """    DIBRFrameSlot* slot{};
    for (uint32_t offset = 0; offset < DIBR_FRAME_SLOT_COUNT; ++offset) {
        const auto index = (m_dibr_slot_cursor + offset) % DIBR_FRAME_SLOT_COUNT;
        auto& candidate = m_dibr_slots[index];

        if (!candidate.commands.ready() && !candidate.commands.setup(L\"DIBR Preview Commands\")) {
            continue;
        }

        if (candidate.commands.try_wait()) {
            slot = &candidate;
            m_dibr_slot_cursor = (index + 1) % DIBR_FRAME_SLOT_COUNT;
            break;
        }
    }

    if (slot == nullptr) {
        // A ring miss is rare and means the GPU is genuinely more than three
        // DIBR frames behind. Preserve the known-good path rather than
        // resetting an in-flight allocator or presenting a stale texture.
        slot = &m_dibr_slots[m_dibr_slot_cursor];
        SPDLOG_WARNING_EVERY_N_SEC(2, \"[DIBR] All in-flight slots are busy; waiting for slot {}\", m_dibr_slot_cursor);
        slot->commands.wait(INFINITE);
        if (!slot->commands.ready()) {
            SPDLOG_WARN(\"[DIBR] Could not reclaim the fallback command context\");
            return false;
        }
        m_dibr_slot_cursor = (m_dibr_slot_cursor + 1) % DIBR_FRAME_SLOT_COUNT;
    }
""",
    """    DIBRFrameSlot* slot{};
    for (uint32_t offset = 0; offset < DIBR_FRAME_SLOT_COUNT; ++offset) {
        const auto index = (m_dibr_slot_cursor + offset) % DIBR_FRAME_SLOT_COUNT;
        auto& candidate = m_dibr_slots[index];

        if (candidate.commands.device_removed_after_untracked_submission()) {
            // Device removal ends queue execution. Abort the pending output
            // transaction and release only after the context records that
            // retirement outcome; this output must never be published.
            candidate.preview.abort_recording();
            candidate.preview.note_submission_retired();
            candidate.preview_recording_pending = false;
            candidate.in_flight_resources.clear();
            candidate.commands.reset();
            candidate.present_tex.reset();
            candidate.preview.reset();
            candidate.quarantined = false;
        }

        if (candidate.quarantined) {
            const auto safe_to_reclaim = candidate.commands.has_untracked_submission()
                ? candidate.commands.try_wait()
                : candidate.commands.references_retired();
            if (!safe_to_reclaim) {
                continue;
            }
            candidate.preview.note_submission_retired();
            candidate.commands.reset();
            candidate.present_tex.reset();
            candidate.preview.reset();
            candidate.in_flight_resources.clear();
            candidate.preview_recording_pending = false;
            candidate.quarantined = false;
        }

        bool reclaimed_untracked{};
        if (candidate.commands.has_untracked_submission()) {
            // Retry a queue-fence retirement without blocking the frame. Until
            // this succeeds, the slot and every resource it references stay
            // owned by the ring and cannot be reused.
            if (!candidate.commands.try_wait()) {
                if (!candidate.commands.device_removed_after_untracked_submission()) {
                    continue;
                }

                candidate.preview.abort_recording();
                candidate.preview.note_submission_retired();
                candidate.preview_recording_pending = false;
                candidate.in_flight_resources.clear();
                candidate.commands.reset();
                candidate.present_tex.reset();
                candidate.preview.reset();
            }
            reclaimed_untracked = !candidate.commands.device_removed_after_untracked_submission();
        }

        if (!candidate.commands.ready() && !candidate.commands.setup(L\"DIBR Preview Commands\")) {
            continue;
        }

        if (reclaimed_untracked || candidate.commands.try_wait()) {
            candidate.preview.note_submission_retired();
            if (candidate.preview_recording_pending) {
                candidate.preview.commit_recording();
                candidate.preview_recording_pending = false;
            }
            candidate.in_flight_resources.clear();
            slot = &candidate;
            m_dibr_slot_cursor = (index + 1) % DIBR_FRAME_SLOT_COUNT;
            break;
        }
    }

    if (slot == nullptr) {
        // Do not reuse a busy/quarantined slot through a fallback path. Every
        // reuse must pass the retirement and cleanup checks in the bounded
        // three-slot scan above.
        SPDLOG_WARNING_EVERY_N_SEC(2, \"[DIBR] All three frame slots are busy; skipping DIBR for this frame\");
        return false;
    }
""")

edit(component_cpp,
    """    if (!slot->preview.synthesize(
            device,
            slot->commands.cmd_list.Get(),
            scene_color,
            scene_color_state,
            scene_depth,
            scene_depth_state,
            parameters.ui_edge_guard ? m_dibr_ui_alpha_snapshot.Get() : nullptr,
            parameters)) {
        return false;
    }

    const auto output = slot->preview.output().texture.Get();
    if (output == nullptr || !ensure_dibr_present_texture(slot->present_tex, device, output->GetDesc())) {
        SPDLOG_INFO_EVERY_N_SEC(2, \"[DIBR] Synthesis completed but the packed presentation texture is unavailable\");
        return false;
    }

    const auto output_desc = output->GetDesc();
    const auto present_desc = slot->present_tex.texture->GetDesc();
    if (output_desc.Width != present_desc.Width || output_desc.Height != present_desc.Height) return false;
    // Alpha is explicitly opaque in the stock DIBR shader. SpriteBatch now
    // performs only RGBA -> BGRA storage conversion, avoiding unsupported
    // BGRA UAV writes and incompatible CopyResource between format families.
    d3d12::render_srv_to_rtv(m_game_batch.get(), slot->commands.cmd_list.Get(),
        slot->preview.output(), slot->present_tex,
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);

    // DIBR records directly into this context rather than through one of its
    // copy helpers, so mark it for submission explicitly.
    slot->commands.has_commands = true;
    slot->commands.execute();
    m_dibr_active_present_tex = &slot->present_tex;
    return true;
""",
    """    // Allocate the presentation target before DIBR records its first command.
    // The output format and extent are fixed by DIBRPreview, so this descriptor
    // is sufficient for transactional preparation even before output exists.
    auto expected_output_desc = scene_color->GetDesc();
    expected_output_desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    if (!ensure_dibr_present_texture(slot->present_tex, device, expected_output_desc)) {
        SPDLOG_INFO_EVERY_N_SEC(2, \"[DIBR] Presentation target preparation failed before recording\");
        return false;
    }
    const auto present_desc = slot->present_tex.texture->GetDesc();
    if (expected_output_desc.Width != present_desc.Width || expected_output_desc.Height != present_desc.Height) {
        return false;
    }

    const auto needs_ui_alpha = d3d12::dibr_transaction::needs_ui_alpha(
        parameters.ui_edge_guard,
        parameters.ui_footprint_reprojection,
        parameters.show_ui_footprint_reprojection_mask);
    auto* frame_ui_alpha = needs_ui_alpha ? m_dibr_ui_alpha_snapshot.Get() : nullptr;

    if (!slot->preview.synthesize(
            device,
            slot->commands.cmd_list.Get(),
            scene_color,
            scene_color_state,
            scene_depth,
            scene_depth_state,
            frame_ui_alpha,
            parameters,
            true)) {
        slot->preview.abort_recording();
        return false;
    }
    slot->preview_recording_pending = true;

    const auto output = slot->preview.output().texture.Get();
    if (output == nullptr) {
        slot->commands.discard_recording();
        slot->preview.abort_recording();
        slot->preview_recording_pending = false;
        SPDLOG_INFO_EVERY_N_SEC(2, \"[DIBR] Output disappeared after preparation; discarded the unsubmitted recording\");
        return false;
    }

    const auto output_desc = output->GetDesc();
    if (output_desc.Width != present_desc.Width || output_desc.Height != present_desc.Height) {
        slot->commands.discard_recording();
        slot->preview.abort_recording();
        slot->preview_recording_pending = false;
        return false;
    }
    // Alpha is explicitly opaque in the stock DIBR shader. SpriteBatch now
    // performs only RGBA -> BGRA storage conversion, avoiding unsupported
    // BGRA UAV writes and incompatible CopyResource between format families.
    d3d12::render_srv_to_rtv(m_game_batch.get(), slot->commands.cmd_list.Get(),
        slot->preview.output(), slot->present_tex,
        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);

    // DIBR records directly into this context rather than through one of its
    // copy helpers, so mark it for submission explicitly.
    slot->commands.has_commands = true;
    const auto execution = slot->commands.execute_checked();
    if (execution == d3d12::dibr_transaction::ExecuteResult::SubmittedTracked ||
        execution == d3d12::dibr_transaction::ExecuteResult::SubmittedTrackedNeedsPolling) {
        slot->preview.note_submission_started();
        slot->preview.commit_recording();
        slot->preview_recording_pending = false;
    } else if (execution == d3d12::dibr_transaction::ExecuteResult::SubmittedUntracked) {
        slot->preview.note_submission_started();
        slot->preview_recording_pending = true;
    } else {
        slot->commands.discard_recording();
        slot->preview.abort_recording();
        slot->preview_recording_pending = false;
        return false;
    }

    auto retain_submitted_resource = [&](ID3D12Resource* resource) {
        if (resource != nullptr) {
            ComPtr<ID3D12Resource> retained{};
            retained = resource;
            slot->in_flight_resources.emplace_back(std::move(retained));
        }
    };
    retain_submitted_resource(scene_color);
    retain_submitted_resource(scene_depth);
    retain_submitted_resource(frame_ui_alpha);

    if (execution != d3d12::dibr_transaction::ExecuteResult::SubmittedTracked) {
        return false;
    }

    m_dibr_active_present_tex = &slot->present_tex;
    return true;
""")

edit(component_cpp,
    """    for (auto& slot : m_dibr_slots) {
        slot.commands.wait(INFINITE);
        slot.commands.reset();
        slot.present_tex.reset();
        slot.preview.reset();
    }
""",
    """    for (auto& slot : m_dibr_slots) {
        const auto was_untracked = slot.commands.has_untracked_submission();
        const auto retired = slot.commands.references_retired() ||
            slot.commands.wait(was_untracked ? 2000 : INFINITE);
        if (!retired) {
            slot.commands.quarantine_untracked_objects();
            slot.preview.quarantine_resources();
            d3d12::dibr_transaction::retain_untracked_com_object(slot.present_tex.texture.Get());
            d3d12::dibr_transaction::retain_untracked_unique(slot.present_tex.rtv_heap);
            d3d12::dibr_transaction::retain_untracked_unique(slot.present_tex.srv_heap);
            for (auto& resource : slot.in_flight_resources) {
                d3d12::dibr_transaction::retain_untracked_com_object(resource.Get());
            }
            slot.quarantined = true;
            continue;
        }

        slot.in_flight_resources.clear();
        slot.preview_recording_pending = false;
        slot.preview.note_submission_retired();
        slot.commands.reset();
        slot.present_tex.reset();
        slot.preview.reset();
        slot.quarantined = false;
    }
""")

print("Applied transactional DIBR preparation, checked submission, retirement, and alpha-consumer fixes")
