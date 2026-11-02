// Tri-View capture writer: CRC, statistics, half-size BMP and ZIP layout (standard C++ only).
#include "TriViewCapture.hpp"
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>

namespace cap = uevr::triview::capture;
static void expect(bool ok, const char* what) { if (!ok) throw std::runtime_error(what); }

int main() try {
    const char* digits = "123456789";
    expect(cap::crc32(reinterpret_cast<const uint8_t*>(digits), 9) == 0xCBF43926u, "CRC-32 check value");
    // 8x4 BGRA image: left half red, right half black, with a padded row pitch.
    const uint32_t w = 8, h = 4, pitch = 40;
    std::vector<uint8_t> px(pitch * h, 0);
    for (uint32_t y = 0; y < h; ++y) for (uint32_t x = 0; x < 4; ++x) {
        auto* p = &px[y * pitch + x * 4]; p[0] = 0; p[1] = 0; p[2] = 200; p[3] = 255;
    }
    const cap::View view{px.data(), pitch, w, h, true};
    const auto left = cap::region_stats(view, {"left", 0, 0, 4, 4});
    const auto right = cap::region_stats(view, {"right", 4, 0, 99, 99});
    expect(left.pixels == 16 && left.nonblack == 16 && left.r == 200.0 && left.b == 0.0, "left stats");
    expect(right.pixels == 16 && right.nonblack == 0, "right stats clamp to the image");
    const auto line = cap::format_stats("img", {"left", 0, 0, 4, 4}, left);
    expect(line.find("img left [0,0)-[4,4): nonblack 100.0% mean rgb 200.0 0.0 0.0") == 0, "stats line");
    const auto bmp = cap::half_bmp(view);
    expect(bmp.size() == 54 + 12 * 2 && bmp[0] == 'B' && bmp[1] == 'M', "bmp size (4x2, rows padded to 12)");
    expect(bmp[54 + 2] == 200 && bmp[54 + 0] == 0 && bmp[54 + 9 + 2] == 0, "bmp pixels are BGR, red then black");
    cap::Zip zip;
    zip.add("a.txt", std::string("hello"));
    zip.add("b.bmp", bmp);
    const auto bytes = zip.finish();
    expect(bytes.size() > 100 && bytes[0] == 'P' && bytes[1] == 'K', "zip signature");
    const uint8_t* end = bytes.data() + bytes.size() - 22;
    expect(std::memcmp(end, "PK\x05\x06", 4) == 0 && end[10] == 2, "zip end record with two entries");
    std::puts("Tri-View capture writer tests passed.");
    return 0;
} catch (const std::exception& e) {
    std::fprintf(stderr, "FAILED: %s\n", e.what());
    return 1;
}
