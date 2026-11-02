#pragma once
// Tri-View automatic capture: turns raw 8-bit BGRA/RGBA readback rows into half-size BMP images,
// per-region pixel statistics and one uncompressed ZIP. Standard C++ only (unit-tested on any OS).
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace uevr::triview::capture {

struct View {                       // one mapped image: rows of 4-byte pixels
    const uint8_t* data{};
    size_t row_pitch{};
    uint32_t width{}, height{};
    bool bgra{true};
    const uint8_t* px(uint32_t x, uint32_t y) const { return data + y * row_pitch + size_t(x) * 4; }
    // r, g, b of one pixel
    std::array<int, 3> rgb(uint32_t x, uint32_t y) const {
        const auto* p = px(x, y);
        return bgra ? std::array<int, 3>{p[2], p[1], p[0]} : std::array<int, 3>{p[0], p[1], p[2]};
    }
};

struct Region {
    std::string name;
    uint32_t x0{}, y0{}, x1{}, y1{};  // half-open, clamped to the image
};

struct Stats {
    uint64_t pixels{}, nonblack{};
    double r{}, g{}, b{};             // mean 0..255
};

// "Non-black" = any channel above 10 (same threshold as the Build 52 capture).
inline Stats region_stats(const View& v, Region r) {
    Stats s{};
    r.x1 = (std::min)(r.x1, v.width); r.y1 = (std::min)(r.y1, v.height);
    if (r.x0 >= r.x1 || r.y0 >= r.y1) return s;
    double sr = 0, sg = 0, sb = 0;
    for (uint32_t y = r.y0; y < r.y1; ++y) {
        for (uint32_t x = r.x0; x < r.x1; ++x) {
            const auto c = v.rgb(x, y);
            sr += c[0]; sg += c[1]; sb += c[2];
            if (c[0] > 10 || c[1] > 10 || c[2] > 10) ++s.nonblack;
        }
    }
    s.pixels = uint64_t(r.x1 - r.x0) * (r.y1 - r.y0);
    s.r = sr / double(s.pixels); s.g = sg / double(s.pixels); s.b = sb / double(s.pixels);
    return s;
}

inline std::string format_stats(const std::string& image, const Region& r, const Stats& s) {
    char line[320];
    std::snprintf(line, sizeof(line), "%s %s [%u,%u)-[%u,%u): nonblack %.1f%% mean rgb %.1f %.1f %.1f\n",
                  image.c_str(), r.name.c_str(), r.x0, r.y0, r.x1, r.y1,
                  s.pixels ? 100.0 * double(s.nonblack) / double(s.pixels) : 0.0, s.r, s.g, s.b);
    return line;
}

inline void put16(std::vector<uint8_t>& o, uint32_t v) { o.push_back(uint8_t(v)); o.push_back(uint8_t(v >> 8)); }
inline void put32(std::vector<uint8_t>& o, uint32_t v) { put16(o, v & 0xffff); put16(o, v >> 16); }

// 24-bit bottom-up BMP at half size (2x2 box filter); odd last row/column dropped.
inline std::vector<uint8_t> half_bmp(const View& v) {
    const uint32_t w = (std::max)(1u, v.width / 2), h = (std::max)(1u, v.height / 2);
    const uint32_t row = (w * 3 + 3) & ~3u;
    std::vector<uint8_t> o;
    o.reserve(54 + size_t(row) * h);
    o.push_back('B'); o.push_back('M'); put32(o, 54 + row * h); put32(o, 0); put32(o, 54);
    put32(o, 40); put32(o, w); put32(o, h); put16(o, 1); put16(o, 24); put32(o, 0); put32(o, row * h);
    put32(o, 2835); put32(o, 2835); put32(o, 0); put32(o, 0);
    for (uint32_t y = h; y-- > 0;) {
        const size_t start = o.size();
        for (uint32_t x = 0; x < w; ++x) {
            int sum[3]{};
            int n = 0;
            for (uint32_t dy = 0; dy < 2; ++dy) for (uint32_t dx = 0; dx < 2; ++dx) {
                const uint32_t sx = (std::min)(x * 2 + dx, v.width - 1), sy = (std::min)(y * 2 + dy, v.height - 1);
                const auto c = v.rgb(sx, sy);
                sum[0] += c[0]; sum[1] += c[1]; sum[2] += c[2]; ++n;
            }
            o.push_back(uint8_t(sum[2] / n)); o.push_back(uint8_t(sum[1] / n)); o.push_back(uint8_t(sum[0] / n));
        }
        while (o.size() - start < row) o.push_back(0);
    }
    return o;
}

inline uint32_t crc32(const uint8_t* data, size_t size) {
    static const auto table = [] {
        std::array<uint32_t, 256> t{};
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            t[i] = c;
        }
        return t;
    }();
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < size; ++i) c = table[(c ^ data[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

// Minimal ZIP (method 0 = stored), enough for Windows Explorer and every unzip tool.
class Zip {
public:
    void add(const std::string& name, const std::vector<uint8_t>& bytes) {
        Entry e{name, crc32(bytes.data(), bytes.size()), uint32_t(bytes.size()), uint32_t(out_.size())};
        put32(out_, 0x04034b50); put16(out_, 20); put16(out_, 0); put16(out_, 0);
        put16(out_, 0); put16(out_, 0x21); put32(out_, e.crc); put32(out_, e.size); put32(out_, e.size);
        put16(out_, uint32_t(name.size())); put16(out_, 0);
        out_.insert(out_.end(), name.begin(), name.end());
        out_.insert(out_.end(), bytes.begin(), bytes.end());
        entries_.push_back(e);
    }
    void add(const std::string& name, const std::string& text) { add(name, std::vector<uint8_t>(text.begin(), text.end())); }
    std::vector<uint8_t> finish() {
        const uint32_t start = uint32_t(out_.size());
        for (const auto& e : entries_) {
            put32(out_, 0x02014b50); put16(out_, 20); put16(out_, 20); put16(out_, 0); put16(out_, 0);
            put16(out_, 0); put16(out_, 0x21); put32(out_, e.crc); put32(out_, e.size); put32(out_, e.size);
            put16(out_, uint32_t(e.name.size())); put16(out_, 0); put16(out_, 0); put16(out_, 0); put16(out_, 0);
            put32(out_, 0); put32(out_, e.offset);
            out_.insert(out_.end(), e.name.begin(), e.name.end());
        }
        const uint32_t size = uint32_t(out_.size()) - start;
        put32(out_, 0x06054b50); put16(out_, 0); put16(out_, 0);
        put16(out_, uint32_t(entries_.size())); put16(out_, uint32_t(entries_.size()));
        put32(out_, size); put32(out_, start); put16(out_, 0);
        return std::move(out_);
    }

private:
    struct Entry { std::string name; uint32_t crc{}, size{}, offset{}; };
    std::vector<uint8_t> out_;
    std::vector<Entry> entries_;
};

} // namespace uevr::triview::capture
