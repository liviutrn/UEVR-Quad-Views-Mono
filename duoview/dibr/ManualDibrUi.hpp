#pragma once

// ImGui-only presentation for the manual depth picker. The capture/runtime
// layer adapts its metadata to UiCandidate and publishes only immutable CPU
// thumbnail payloads after the async readback fence completes.
#include "ManualDibrPreview.hpp"

#include <algorithm>
#include <cstdio>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <imgui.h>

namespace uevr::duoview::dibr::ui {

inline constexpr size_t kCandidatePageSize = kManualDibrCandidatePageSize;

struct UiCandidate {
    Candidate candidate{};
    std::shared_ptr<const PreviewPayload> preview{};
    CandidatePreviewStatus preview_status{CandidatePreviewStatus::waiting_for_live_capture};
    uint64_t age_ms{};
    std::string status{};
};

struct Frame {
    std::vector<UiCandidate> candidates{};
    RoleAssignments assignments{};
    size_t first_candidate{};
    bool candidates_complete{};
    bool picker_open{};
    bool stereo_enabled{};
    std::string output_status{"Mono fallback — DuoView Stereo is off"};
};

struct Actions {
    std::function<void(bool)> set_stereo_enabled{};
    std::function<void(bool)> set_picker_open{};
    std::function<void(size_t)> set_first_candidate{};
    std::function<bool(CandidateKey)> assign_periphery{};
    std::function<bool(CandidateKey)> assign_fovea{};
    std::function<void()> clear_periphery{};
    std::function<void()> clear_fovea{};
};

struct State {
    std::optional<CandidateKey> enlarged_candidate{};
    bool show_alignment_grid{true};
};

inline const char* capture_stage_name(CaptureStage stage) noexcept {
    switch (stage) {
    case CaptureStage::depth_write_to_shader_read: return "Depth write → shader read";
    case CaptureStage::upscaler_input: return "Upscaler input";
    case CaptureStage::engine_pass: return "Engine pass";
    case CaptureStage::unknown: default: return "Unknown stage";
    }
}

inline const char* preview_status_name(CandidatePreviewStatus status) noexcept {
    switch (status) {
    case CandidatePreviewStatus::unsupported: return "Preview unsupported";
    case CandidatePreviewStatus::waiting_for_live_capture: return "Waiting for a live capture";
    case CandidatePreviewStatus::readback_pending: return "Readback pending";
    case CandidatePreviewStatus::live: return "LIVE";
    case CandidatePreviewStatus::stale: return "STALE";
    case CandidatePreviewStatus::source_changed: return "Source changed — reselect";
    default: return "Preview state unknown";
    }
}

inline const char* queue_relation_name(QueueRelation relation) noexcept {
    switch (relation) {
    case QueueRelation::same_queue: return "same queue";
    case QueueRelation::cross_queue: return "cross queue";
    case QueueRelation::unknown: default: return "queue relation unknown";
    }
}

inline void draw_depth_cells(
    const PreviewPayload& preview,
    ImVec2 size,
    uint32_t display_width,
    uint32_t display_height,
    bool alignment_grid)
{
    if (!valid_preview_payload(preview, preview.key) || !display_width || !display_height) {
        ImGui::TextUnformatted("No completed owned depth thumbnail.");
        return;
    }

    const ImVec2 top_left = ImGui::GetCursorScreenPos();
    const ImVec2 bottom_right{top_left.x + size.x, top_left.y + size.y};
    ImDrawList* draw = ImGui::GetWindowDrawList();
    const float cell_width = size.x / static_cast<float>(display_width);
    const float cell_height = size.y / static_cast<float>(display_height);

    for (uint32_t y = 0; y != display_height; ++y) {
        const uint32_t source_y = (std::min)(
            preview.height - 1,
            static_cast<uint32_t>((uint64_t{y} * preview.height) / display_height));
        for (uint32_t x = 0; x != display_width; ++x) {
            const uint32_t source_x = (std::min)(
                preview.width - 1,
                static_cast<uint32_t>((uint64_t{x} * preview.width) / display_width));
            const float depth = preview.raw_depth[size_t{source_y} * preview.width + source_x];
            const uint8_t gray = reversed_z_preview_gray(depth);
            const ImU32 color = IM_COL32(gray, gray, gray, 255);
            const ImVec2 cell_min{
                top_left.x + static_cast<float>(x) * cell_width,
                top_left.y + static_cast<float>(y) * cell_height};
            const ImVec2 cell_max{
                top_left.x + static_cast<float>(x + 1) * cell_width,
                top_left.y + static_cast<float>(y + 1) * cell_height};
            draw->AddRectFilled(cell_min, cell_max, color);
        }
    }

    if (alignment_grid) {
        constexpr ImU32 grid_color = IM_COL32(64, 210, 255, 150);
        for (int divider = 1; divider < 3; ++divider) {
            const float x = top_left.x + size.x * (static_cast<float>(divider) / 3.0f);
            const float y = top_left.y + size.y * (static_cast<float>(divider) / 3.0f);
            draw->AddLine(ImVec2{x, top_left.y}, ImVec2{x, bottom_right.y}, grid_color, 1.0f);
            draw->AddLine(ImVec2{top_left.x, y}, ImVec2{bottom_right.x, y}, grid_color, 1.0f);
        }
        const ImVec2 center{top_left.x + size.x * 0.5f, top_left.y + size.y * 0.5f};
        draw->AddLine(ImVec2{center.x - 8.0f, center.y}, ImVec2{center.x + 8.0f, center.y}, grid_color, 1.5f);
        draw->AddLine(ImVec2{center.x, center.y - 8.0f}, ImVec2{center.x, center.y + 8.0f}, grid_color, 1.5f);
    }
    draw->AddRect(top_left, bottom_right, IM_COL32(210, 220, 230, 255), 0.0f, 0, 1.0f);
    ImGui::Dummy(size);
}

inline const UiCandidate* find_candidate(const Frame& frame, CandidateKey key) {
    const auto it = std::find_if(frame.candidates.begin(), frame.candidates.end(), [key](const UiCandidate& view) {
        return view.candidate.key == key;
    });
    return it == frame.candidates.end() ? nullptr : &*it;
}

inline bool timing_is_packet_matched(const UiCandidate& view) noexcept {
    return view.preview && preview_has_verified_producer_frame(*view.preview, view.candidate.key);
}

inline void draw_preview_lineage(const PreviewPayload& preview) {
    ImGui::Text("Preview serial %llu  |  submitted order %llu  |  completion tick %llu ms",
        static_cast<unsigned long long>(preview.capture_serial),
        static_cast<unsigned long long>(preview.submitted_order),
        static_cast<unsigned long long>(preview.completed_ms));
    ImGui::Text("Queue provenance: %s  |  producer %llu → readback %llu  |  order %llu → %llu",
        queue_relation_name(preview.queue.relation),
        static_cast<unsigned long long>(preview.queue.producer_queue),
        static_cast<unsigned long long>(preview.queue.consumer_queue),
        static_cast<unsigned long long>(preview.queue.producer_order),
        static_cast<unsigned long long>(preview.queue.consumer_order));
    if (preview.queue.relation == QueueRelation::cross_queue) {
        ImGui::Text("Producer fence %llu  |  readback queue wait %llu",
            static_cast<unsigned long long>(preview.queue.producer_fence),
            static_cast<unsigned long long>(preview.queue.consumer_wait));
    }
    ImGui::Text("Private readback fence %llu / completed %llu",
        static_cast<unsigned long long>(preview.private_readback_fence_value),
        static_cast<unsigned long long>(preview.completed_private_readback_fence_value));
    if (preview.association == PreviewAssociation::producer_frame_matched) {
        ImGui::Text("Producer frame: generation %llu, frame %llu",
            static_cast<unsigned long long>(preview.producer_generation),
            static_cast<unsigned long long>(preview.producer_frame));
    } else {
        ImGui::TextColored(ImVec4{1.0f, 0.72f, 0.3f, 1.0f},
            "Timing unverified — preview only (observed producer tag %llu / %llu)",
            static_cast<unsigned long long>(preview.producer_generation),
            static_cast<unsigned long long>(preview.producer_frame));
    }
}

inline void draw_raw_depth_range(const PreviewPayload& preview) {
    float minimum = INFINITY;
    float maximum = -INFINITY;
    size_t valid_samples = 0;
    for (const float value : preview.raw_depth) {
        if (!std::isfinite(value) || value <= 0.0f) continue;
        minimum = (std::min)(minimum, value);
        maximum = (std::max)(maximum, value);
        ++valid_samples;
    }
    if (!valid_samples) {
        ImGui::TextUnformatted("Raw depth samples: no finite positive values");
        return;
    }
    ImGui::Text("Raw depth samples: %zu finite positive values, min %.7g, max %.7g",
        valid_samples, static_cast<double>(minimum), static_cast<double>(maximum));
}

inline void draw_role_summary(const char* label, std::optional<CandidateKey> assignment, const Frame& frame,
    const std::function<void()>& clear_action, const char* clear_id)
{
    ImGui::Text("%s", label);
    ImGui::SameLine();
    if (!assignment) {
        ImGui::TextDisabled("Not selected — choose a live candidate");
    } else {
        const auto* selected = find_candidate(frame, *assignment);
        if (!selected) {
            if (frame.candidates_complete) {
                ImGui::TextColored(ImVec4{1.0f, 0.55f, 0.3f, 1.0f},
                    "Source changed — reselect (%llu / gen %llu)",
                    static_cast<unsigned long long>(assignment->id),
                    static_cast<unsigned long long>(assignment->resource_generation));
            } else {
                ImGui::Text("Candidate %llu / gen %llu — details hidden",
                    static_cast<unsigned long long>(assignment->id),
                    static_cast<unsigned long long>(assignment->resource_generation));
            }
        } else {
            ImGui::Text("Candidate %llu — %s, %ux%u; %s",
                static_cast<unsigned long long>(selected->candidate.key.id),
                preview_status_name(selected->preview_status),
                selected->candidate.width, selected->candidate.height,
                timing_is_packet_matched(*selected)
                    ? "producer frame tagged" : "timing unverified");
        }
    }
    ImGui::SameLine();
    ImGui::PushID(clear_id);
    if (ImGui::SmallButton("Clear") && clear_action) clear_action();
    ImGui::PopID();
}

inline void draw_candidate_card(const UiCandidate& view, float card_width, State& state, const Actions& actions) {
    const auto& candidate = view.candidate;
    char id[96]{};
    std::snprintf(id, sizeof(id), "%llu:%llu:%u",
        static_cast<unsigned long long>(candidate.key.id),
        static_cast<unsigned long long>(candidate.key.resource_generation),
        candidate.key.subresource);
    ImGui::PushID(id);
    ImGui::BeginChild("DepthCandidateCard", ImVec2{card_width, 360.0f}, true);
    ImGui::Text("Candidate %llu  |  generation %llu  |  subresource %u",
        static_cast<unsigned long long>(candidate.key.id),
        static_cast<unsigned long long>(candidate.key.resource_generation), candidate.key.subresource);
    ImGui::Text("%ux%u  |  active rect %u,%u %ux%u  |  DXGI format %u",
        candidate.width, candidate.height, candidate.active_rect.x, candidate.active_rect.y,
        candidate.active_rect.width, candidate.active_rect.height, candidate.format);
    ImGui::Text("Depth capture: %s  |  CPU preview: %s",
        candidate.capture_supported ? "supported" : "unsupported",
        candidate.preview_supported ? "supported" : "unsupported");
    ImGui::Text("Stage: %s  |  Update serial: %llu", capture_stage_name(candidate.stage),
        static_cast<unsigned long long>(candidate.update_serial));
    ImGui::Text("%s%s", preview_status_name(view.preview_status),
        view.preview_status == CandidatePreviewStatus::live || view.preview_status == CandidatePreviewStatus::stale
            ? (view.age_ms ? " — updated " : " — updated just now") : "");
    if (view.age_ms && (view.preview_status == CandidatePreviewStatus::live ||
        view.preview_status == CandidatePreviewStatus::stale))
        ImGui::SameLine(), ImGui::Text("%llu ms ago", static_cast<unsigned long long>(view.age_ms));
    if (timing_is_packet_matched(view)) {
        ImGui::Text("This preview's producer frame: generation %llu, frame %llu",
            static_cast<unsigned long long>(view.preview->producer_generation),
            static_cast<unsigned long long>(view.preview->producer_frame));
    } else {
        ImGui::TextColored(ImVec4{1.0f, 0.72f, 0.3f, 1.0f}, "Timing unverified");
    }
    if (!view.status.empty()) ImGui::TextWrapped("%s", view.status.c_str());

    if (preview_payload_is_displayable(view.preview_status, view.preview.get(), candidate.key)) {
        const float thumb_width = (std::min)(ImGui::GetContentRegionAvail().x, 224.0f);
        const float thumb_height = thumb_width * static_cast<float>(view.preview->height) /
            static_cast<float>(view.preview->width);
        ImGui::TextUnformatted("Reversed-Z log grayscale: 1e-4 (dark) to 1e-2 (bright)");
        draw_depth_cells(*view.preview, ImVec2{thumb_width, thumb_height},
            view.preview->width, view.preview->height, false);
    } else if (view.preview_status == CandidatePreviewStatus::readback_pending) {
        ImGui::TextUnformatted("Preview readback is asynchronous; the previous safe thumbnail remains visible when available.");
    } else {
        ImGui::TextUnformatted("No completed owned thumbnail is available yet.");
    }

    if (ImGui::Button("Enlarge / align")) state.enlarged_candidate = candidate.key;
    ImGui::SameLine();
    if (candidate_can_be_assigned(candidate) && actions.assign_periphery) {
        if (ImGui::Button("Use for full view / Periphery")) actions.assign_periphery(candidate.key);
    }
    ImGui::SameLine();
    if (candidate_can_be_assigned(candidate) && actions.assign_fovea) {
        if (ImGui::Button("Use for Fovea")) actions.assign_fovea(candidate.key);
    }
    ImGui::EndChild();
    ImGui::PopID();
}

inline void draw_enlarged_preview(const Frame& frame, State& state) {
    if (!state.enlarged_candidate) return;
    const auto* view = find_candidate(frame, *state.enlarged_candidate);
    if (!view) {
        if (frame.candidates_complete) {
            ImGui::TextColored(ImVec4{1.0f, 0.55f, 0.3f, 1.0f},
                "Source changed — reselect to restore the enlarged preview.");
        } else {
            ImGui::TextDisabled("Open the candidate list to restore the enlarged preview.");
        }
        return;
    }

    ImGui::Separator();
    ImGui::Text("Alignment view — candidate %llu, %ux%u",
        static_cast<unsigned long long>(view->candidate.key.id), view->candidate.width, view->candidate.height);
    ImGui::Text("Source generation %llu, subresource %u  |  DXGI format %u  |  stage: %s",
        static_cast<unsigned long long>(view->candidate.key.resource_generation),
        view->candidate.key.subresource, view->candidate.format, capture_stage_name(view->candidate.stage));
    ImGui::Text("Active rect %u,%u %ux%u  |  update serial %llu",
        view->candidate.active_rect.x, view->candidate.active_rect.y,
        view->candidate.active_rect.width, view->candidate.active_rect.height,
        static_cast<unsigned long long>(view->candidate.update_serial));
    ImGui::TextWrapped("Status reason: %s", view->status.empty()
        ? preview_status_name(view->preview_status) : view->status.c_str());
    ImGui::Text("Preview state: %s%s", preview_status_name(view->preview_status),
        view->age_ms ? " (age shown below)" : "");
    if (view->age_ms) ImGui::Text("Preview age: %llu ms", static_cast<unsigned long long>(view->age_ms));
    ImGui::Checkbox("Show alignment grid", &state.show_alignment_grid);
    ImGui::SameLine();
    if (ImGui::SmallButton("Close enlarged view")) {
        state.enlarged_candidate.reset();
        return;
    }
    ImGui::TextWrapped("Compare broad scene edges, railings, and foreground objects in this depth preview with the center-color scene. Status badges identify stale data. The grid is a visual guide and does not assert frame alignment.");
    if (!preview_payload_is_displayable(view->preview_status, view->preview.get(), view->candidate.key)) {
        ImGui::TextWrapped("%s", view->status.empty() ? "Waiting for a completed owned depth thumbnail." : view->status.c_str());
        return;
    }

    draw_preview_lineage(*view->preview);
    draw_raw_depth_range(*view->preview);

    const float image_width = (std::min)(ImGui::GetContentRegionAvail().x, 512.0f);
    const float image_height = image_width * static_cast<float>(view->preview->height) /
        static_cast<float>(view->preview->width);
    ImGui::TextUnformatted("Reversed-Z log grayscale: 1e-4 (dark) to 1e-2 (bright)");
    draw_depth_cells(*view->preview, ImVec2{image_width, image_height},
        view->preview->width, view->preview->height, state.show_alignment_grid);
    ImGui::Text("Display: %s  |  %s", preview_status_name(view->preview_status),
        timing_is_packet_matched(*view) ? "producer frame tagged" : "timing unverified");
}

inline void draw(const Frame& frame, State& state, const Actions& actions) {
    if (!frame.picker_open && !frame.stereo_enabled) state.enlarged_candidate.reset();
    ImGui::TextUnformatted("DuoView manual depth");
    bool stereo_enabled = frame.stereo_enabled;
    if (ImGui::Checkbox("Enable DuoView Stereo", &stereo_enabled) && actions.set_stereo_enabled)
        actions.set_stereo_enabled(stereo_enabled);
    ImGui::TextWrapped("Output: %s", frame.output_status.empty() ? "Waiting for status" : frame.output_status.c_str());
    ImGui::Separator();

    draw_role_summary("Full view / Periphery depth", frame.assignments.periphery, frame,
        actions.clear_periphery, "clear-periphery");
    draw_role_summary("Fovea depth", frame.assignments.fovea, frame,
        actions.clear_fovea, "clear-fovea");

    if (frame.picker_open) {
        if (ImGui::Button("Hide depth candidates") && actions.set_picker_open)
            actions.set_picker_open(false);
    } else {
        if (ImGui::Button("Choose depth candidates") && actions.set_picker_open)
            actions.set_picker_open(true);
    }

    if (frame.picker_open) {
        const size_t count = frame.candidates.size();
        const auto page = candidate_page_window(count, frame.first_candidate);
        const size_t current_page = page.page_count ? page.page_index + 1 : 0;
        ImGui::SameLine();
        if (count) {
            ImGui::Text("Showing %zu–%zu of %zu observed candidates  |  page %zu / %zu",
                page.first + 1, page.end, count, current_page, page.page_count);
        } else {
            ImGui::TextUnformatted("No observed candidates");
        }
        if (!frame.candidates_complete)
            ImGui::TextColored(ImVec4{1.0f, 0.72f, 0.3f, 1.0f},
                "Candidate list may be incomplete; discovery can be capped or still in progress.");
        if (ImGui::Button("Previous page") && actions.set_first_candidate)
            actions.set_first_candidate(page.has_previous() ? page.first - kCandidatePageSize : 0);
        ImGui::SameLine();
        if (ImGui::Button("Next page") && actions.set_first_candidate)
            actions.set_first_candidate(page.has_next() ? page.end : page.first);

        if (frame.candidates.empty()) {
            ImGui::TextWrapped("No depth candidates are registered yet. The picker watches live depth-write transitions while open.");
        } else {
            ImGui::BeginChild("ManualDibrCandidatePages", ImVec2{0.0f, 620.0f}, true);
            const size_t end = page.end;
            const float available_width = ImGui::GetContentRegionAvail().x;
            const bool two_columns = available_width >= 720.0f;
            const float card_width = two_columns ? (available_width - 12.0f) * 0.5f : available_width;
            for (size_t i = page.first; i < end; ++i) {
                if (two_columns && i != page.first && ((i - page.first) % 2) != 0) ImGui::SameLine();
                ImGui::BeginGroup();
                draw_candidate_card(frame.candidates[i], card_width, state, actions);
                ImGui::EndGroup();
            }
            ImGui::EndChild();
        }
    }

    draw_enlarged_preview(frame, state);
}

} // namespace uevr::duoview::dibr::ui
