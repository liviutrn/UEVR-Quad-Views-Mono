// B37: final color placement differs from the engine's role identity rectangle.
#include "QuadViewGeometry.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
using namespace uevr::quadview;
static void check(bool value,const char* message) {
    if (!value) throw std::runtime_error(message);
}
int main() try {
    const auto made=make_layout(4060,3228,.5f,.5f,.2f,1.f);
    check(made.has_value(),"Captured-size layout rejected");
    Layout atlas=*made;
    const auto original=atlas.views;
    for (size_t role=0;role<4;++role)
        check(color_source_rect(atlas,role)==original[role],"Atlas color coordinates changed");
    Layout native=atlas;
    check(apply_native_local(native),"Native layout rejected");
    const auto identity=native.views;
    // B42.5: every native role starts at 0 (no x16/x24 role tags), so the final
    // colour position cannot differ from the engine rectangle any more.
    check(identity[2]==Rect{0,0,2030,1614},"Left fovea not at origin");
    check(identity[3]==Rect{0,0,2030,1614},"Right fovea not at origin");
    const auto extents=source_extents(native);
    check(extents[2]==std::array<uint32_t,2>{2048,1664} && extents[3]==extents[2],
          "Source allocation is not the picture rounded to 64 px");
    for (size_t role=0;role<4;++role) {
        const Rect expected{0,0,identity[role].width,identity[role].height};
        const Rect actual=color_source_rect(native,role);
        check(actual==expected,"Native final color did not start at origin");
        check(actual.x+actual.width<=extents[role][0] && actual.y+actual.height<=extents[role][1],
              "Final color rectangle exceeds allocation");
    }
    check(native.views==identity,"Color lookup modified engine role identities");
    // In the captured resource x2030 starts black allocation padding. The old
    // engine-origin interpretation samples x2045/x2053 at its last pixel and
    // skips the first16/24 actual image columns. Correct mapping preserves both.
    for (size_t eye=0;eye<2;++eye) {
        const auto role=eye+2;
        const auto rect=color_source_rect(native,role);
        check(rect.x==0 && rect.x+rect.width-1==2029,"Captured first/last image column lost");
        check(identity[role].x==0 && rect==identity[role],"Engine and colour rectangles differ");
    }
    std::cout<<"Color source rectangles: all native roles at origin 0, atlas coordinates passed\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr<<"Color source rectangles FAILED: "<<e.what()<<'\n';
    return 1;
}
