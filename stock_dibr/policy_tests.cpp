#include "DepthPolicy.hpp"

#include <cstdint>
#include <cstdio>
#include <limits>
#include <array>

namespace {
unsigned failures{};

void expect(bool condition, const char* description) {
    if (condition) {
        return;
    }

    std::fprintf(stderr, "FAIL: %s\n", description);
    ++failures;
}
}

int main() {
    using stock_dibr::Layout;
    using stock_dibr::completed;
    using stock_dibr::layout;
    using stock_dibr::duoview_depth_shape;
    using stock_dibr::capture_boundary_supported;

    // Full-resolution engine depth may be packed double-wide or a single eye.
    expect(layout(3840, 2160, 3840, 2160) == Layout::Packed,
        "full-resolution packed depth accepted");
    expect(layout(1920, 2160, 3840, 2160) == Layout::Eye,
        "full-resolution eye depth accepted");

    // DLSS/internal allocations can round dimensions while preserving layout.
    expect(layout(1916, 1080, 3840, 2160) == Layout::Packed,
        "half-resolution packed depth accepts four-pixel width alignment");
    expect(layout(956, 1080, 3840, 2160) == Layout::Eye,
        "half-resolution eye depth accepts four-pixel width alignment");
    expect(layout(2566, 1440, 3840, 2160) == Layout::Packed,
        "two-thirds-resolution packed depth accepts six-pixel width alignment");
    expect(layout(1274, 1440, 3840, 2160) == Layout::Eye,
        "two-thirds-resolution eye depth accepts six-pixel width alignment");

    // Unrelated shadow maps and malformed resource descriptions must not be
    // classified as a scene depth image by dimensions alone.
    expect(layout(1024, 1024, 3840, 2160) == Layout::Invalid,
        "square shadow map rejected");
    expect(layout(2048, 512, 3840, 2160) == Layout::Invalid,
        "off-aspect shadow map rejected");
    expect(layout(0, 1080, 3840, 2160) == Layout::Invalid,
        "zero source width rejected");
    expect(layout(1920, 0, 3840, 2160) == Layout::Invalid,
        "zero source height rejected");
    expect(layout(1920, 1080, 0, 2160) == Layout::Invalid,
        "zero packed width rejected");
    expect(layout(1920, 1080, 3840, 0) == Layout::Invalid,
        "zero output height rejected");
    expect(layout(1920, 1080, 3839, 2160) == Layout::Invalid,
        "odd packed width rejected");
    expect(layout(1920, 400, 3840, 2160) == Layout::Invalid,
        "source below supported scale rejected");
    expect(layout(1920, 2200, 3840, 2160) == Layout::Invalid,
        "source above supported scale rejected");
    expect(layout(32769, 2160, 3840, 2160) == Layout::Invalid,
        "source width above supported extent rejected");
    expect(layout(1920, 32769, 3840, 2160) == Layout::Invalid,
        "source height above supported extent rejected");

    expect(completed(10, 10), "equal fence value is complete");
    expect(completed(11, 10), "greater fence value is complete");
    expect(!completed(9, 10), "lower fence value is incomplete");
    expect(!completed(10, 0), "zero target fence value is rejected");
    expect(!completed(std::numeric_limits<uint64_t>::max(), 10),
        "device-removed fence sentinel is not treated as completed");
    expect(duoview_depth_shape(1015,807,2030,1614),"observed DLSS fovea fits explicit source geometry");
    expect(duoview_depth_shape(406,323,812,646),"observed DLSS periphery below stock 20% floor is discoverable");
    expect(!duoview_depth_shape(128,128,812,646),"square shadow shape does not fit DuoView periphery");
    expect(!duoview_depth_shape(406,323,0,646),"unknown source shape rejected");
    expect(capture_boundary_supported(false,false),"stock depth-read capture policy preserved");
    expect(!capture_boundary_supported(true,false),"DuoView repeated read-only transitions cannot exhaust copy budget");
    expect(capture_boundary_supported(true,true),"DuoView distinct write versions remain captureable");
    const std::array<stock_dibr::DepthShape,4> candidates{{{1015,807,1},{1015,807,2},{406,323,3},{406,323,4}}};
    auto pair=stock_dibr::choose_duoview_depth_pair(candidates,0,0,2030,1614,812,646);
    expect(pair.valid && pair.left<2 && pair.right>=2,"Auto pairs matching relative DLSS scales, not two foveal DSVs");
    expect(!stock_dibr::choose_duoview_depth_pair(std::span(candidates).first(2),0,0,2030,1614,812,646).valid,
        "two foveal snapshots alone cannot masquerade as a complete Auto source pair");
    expect(!stock_dibr::choose_duoview_depth_pair(candidates,1,1,2030,1614,812,646).valid,"duplicate manual choice rejected");
    expect(!stock_dibr::choose_duoview_depth_pair(candidates,5,0,2030,1614,812,646).valid,"stale manual ordinal never becomes Auto");
    expect(stock_dibr::choose_duoview_depth_pair(candidates,1,3,2030,1614,812,646).valid,"explicit coherent manual choices retained");
    expect(!stock_dibr::choose_duoview_depth_pair(candidates,1,2,2030,1614,812,646).valid,
        "manual override must not use two foveal depths as a stereo pair");
    expect(!stock_dibr::choose_duoview_depth_pair(candidates,3,4,2030,1614,812,646).valid,
        "manual override must not use two periphery depths as a stereo pair");
    expect(!stock_dibr::choose_duoview_depth_pair(candidates,3,1,2030,1614,812,646).valid,
        "manual override must reject reversed eye/depth roles");
    expect(!stock_dibr::choose_duoview_depth_pair(candidates,3,0,2030,1614,812,646).valid,
        "partial manual selector must enforce left fovea dimensions");
    expect(!stock_dibr::choose_duoview_depth_pair(candidates,0,1,2030,1614,812,646).valid,
        "partial manual selector must enforce right periphery dimensions");
    const std::array<stock_dibr::DepthShape,2> mismatched_scales{{{1015,807,1},{325,258,2}}};
    expect(!stock_dibr::choose_duoview_depth_pair(mismatched_scales,1,2,2030,1614,812,646).valid,
        "manual override must reject incompatible scene render scales");

    std::printf("Stock DIBR depth policy: %u failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
