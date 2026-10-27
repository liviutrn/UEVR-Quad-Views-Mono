#include "DepthPolicy.hpp"

#include <cstdint>
#include <cstdio>
#include <limits>

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

    std::printf("Stock DIBR depth policy: %u failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
