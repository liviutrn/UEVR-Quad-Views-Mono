#include "HeadMovementScaling.hpp"
#include <cassert>
#include <cmath>
#include <iostream>

namespace {
struct Vec { double x, y, z; };
struct Yaw {
    double angle;
    Vec operator*(const Vec& v) const {
        const auto c=std::cos(angle), s=std::sin(angle);
        return {c*v.x+s*v.z,v.y,-s*v.x+c*v.z};
    }
};
void equal(Vec actual, Vec expected) {
    assert(std::abs(actual.x-expected.x)<1.e-10);
    assert(std::abs(actual.y-expected.y)<1.e-10);
    assert(std::abs(actual.z-expected.z)<1.e-10);
}
}
int main() {
    using uevr::head_movement::scale_translation;
    unsigned checks=0;
    for (int degrees=-180;degrees<=180;degrees+=5) {
        const double angle=degrees*std::acos(-1.)/180.;
        const Yaw recenter{angle}, undo{-angle};
        for (const Vec gains : {Vec{3,1,1},Vec{1,3,1},Vec{1,1,3},Vec{.05,2,5},Vec{1,1,1},Vec{3,3,3}}) {
            for (const Vec player_delta : {Vec{.2,0,0},Vec{0,.2,0},Vec{0,0,-.2},Vec{.2,.11,-.35},Vec{0,0,0}}) {
                const auto tracking_delta=undo*player_delta;
                equal(scale_translation(recenter,tracking_delta,gains),
                      Vec{player_delta.x*gains.x,player_delta.y*gains.y,player_delta.z*gains.z});
                ++checks;
            }
        }
    }
    // Demonstrate that the regression is detected: old R*(S*d) adds a Z
    // component to a pure player-X motion after a 45-degree recenter.
    const Yaw recenter{std::acos(-1.)/4.}, undo{-std::acos(-1.)/4.};
    const auto d=undo*Vec{.2,0,0};
    const auto old=recenter*Vec{d.x*3.,d.y,d.z};
    assert(std::abs(old.z)>.1);
    equal(scale_translation(recenter,d,Vec{3,1,1}),Vec{.6,0,0});
    std::cout << checks << " recenter/anisotropic-axis checks passed; old diagonal reproduced\n";
}
