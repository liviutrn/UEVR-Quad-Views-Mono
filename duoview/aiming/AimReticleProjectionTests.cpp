#include "AimReticleProjection.hpp"
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
using namespace duoview::aim;
static bool near(double a,double b){return std::abs(a-b)<1e-8;}
int main(){
    const Mat4 id{{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1}};
    auto c=project_point({0,0,.5},id); assert(c&&near(c->u,.5)&&near(c->v,.5));
    auto l=project_point({-.6,0,.5},id); assert(l&&near(l->u,.2));
    auto u=project_point({0,.5,.5},id); assert(u&&near(u->v,.25));
    assert(!project_point({2,0,.5},id));
    assert(!project_point({0,0,-.5},id));
    assert(!project_point({0,0,2},id));
    assert(!project_point({std::numeric_limits<double>::quiet_NaN(),0,.5},id));
    assert(!project_ray({0,0,0},{0,0,0},.5,id));
    auto a=project_ray({0,0,0},{0,0,2},.5,id);
    assert(a&&near(a->u,.5)&&near(a->v,.5));
    auto b=project_ray({0,0,0},{0,0,400},.5,id);
    assert(b&&near(a->u,b->u));
    const Mat4 camA{{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,1,0}};
    const Mat4 camB{{1,0,0,-.5, 0,1,0,0, 0,0,1,0, 0,0,1,0}};
    a=project_point({0,0,5},camA); b=project_point({0,0,5},camB);
    assert(a&&b&&near(a->u,.5)&&near(b->u,.45));
    assert(!project_point({0,0,-5},camA));
    Mat4 invalid=id; invalid.m[0]=std::numeric_limits<double>::infinity();
    assert(!project_point({0,0,.5},invalid));
    std::cout<<"Aim reticle projection geometry checks passed; headset not tested.\n";
}
