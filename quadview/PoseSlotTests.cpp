// Tri-view B15: "where is the head now" in TriView. Model of UEVR's 6-slot pose ring
// with ID7's three role renders per draw (frames N, N+1, N+2; only N gets a located
// pose). Recenter runs on the game-thread tick between draws, when the current frame
// is the last role frame. The old rule (slot of the current frame) returns a pose that
// was never refreshed; the B15 rule returns the newest located pose. Other modes keep
// the old rule exactly.
#include "QuadViewGeometry.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace uevr::quadview;
static void check_at(bool b, int line) { if (!b) throw std::runtime_error("pose slot assertion at line " + std::to_string(line)); }
#define check(b) check_at((b), __LINE__)

struct Ring {
    struct Slot { uint32_t frame{}; int yaw{-1}; };
    std::array<Slot, 6> slots{};
    uint32_t current{}, newest{}; bool located{};
    void locate(uint32_t f, int yaw) {
        slots[f % 6] = {f, yaw}; current = f;
        if (!located || !pose_frame_newer(newest, f)) { located = true; newest = f; }
    }
    void role(uint32_t f) { slots[f % 6].frame = f; current = f; } // on_pre_render: frame only, no pose
    int read(bool triview) const { return slots[current_pose_frame(triview, located, current, newest) % 6].yaw; }
    int read_old() const { return slots[current % 6].yaw; }
};

int main() try {
    {   // TriView: head turns 1 degree per draw; recenter after many draws
        Ring r; uint32_t n = 1000; int stale = 0;
        for (int draw = 0; draw < 200; ++draw, n += 3) {
            r.locate(n, draw); r.role(n + 1); r.role(n + 2);
            if (r.read_old() != draw) ++stale;          // the B14 behaviour
            check(r.read(true) == draw);                // B15: always the newest head pose
        }
        check(stale == 200);                            // old rule never saw the current head pose
    }
    {   // other modes (one frame per draw): identical to the old rule
        Ring r; uint32_t n = 7;
        for (int draw = 0; draw < 50; ++draw, ++n) {
            r.locate(n, draw);
            check(r.read(false) == r.read_old() && r.read(true) == r.read_old() && r.read(true) == draw);
        }
    }
    {   // Native Fix style clone (second eye N+1 copies N's pose): unchanged result
        Ring r; uint32_t n = 50;
        for (int draw = 0; draw < 50; ++draw, n += 2) {
            r.locate(n, draw); r.slots[(n + 1) % 6] = {n + 1, draw}; r.current = n + 1;
            check(r.read_old() == draw && r.read(false) == draw);
        }
    }
    check(pose_frame_newer(5u, 0xFFFFFFF0u) && !pose_frame_newer(0xFFFFFFF0u, 5u)); // counter wrap
    std::cout << "pose slot: ok\n";
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
