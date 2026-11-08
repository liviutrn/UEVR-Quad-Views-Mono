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
    check(identity[2]==Rect{16,0,2030,1614},"Left engine identity changed");
    check(identity[3]==Rect{24,0,2030,1614},"Right engine identity changed");
    const auto extents=source_extents(native);
    check(extents[2]==std::array<uint32_t,2>{2112,1664} && extents[3]==extents[2],
          "Captured source allocation changed");
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
        check(identity[role].x+identity[role].width-1>=2030,"Fixture no longer exposes old overrun");
    }
    std::cout<<"Color source rectangles: captured 2030x1614 origin, role identity and atlas coordinates passed\n";
    return 0;
} catch (const std::exception& e) {
    std::cerr<<"Color source rectangles FAILED: "<<e.what()<<'\n';
    return 1;
}
