#include "../SurfaceGeometry.hpp"
#include <cassert>
#include <iostream>
#include <limits>
using namespace uevr::duoview::surface;
static void close(double a,double b,double tolerance=1.e-9) {assert(std::abs(a-b)<tolerance);}
int main() {
    Matrix p{};p[0]=p[5]=p[14]=1.;p[11]=10.;
    const auto inv=inverse(p);assert(inv);
    const auto check=multiply(p,*inv);
    for(int k=0;k<16;++k)close(check[k],k%5==0?1.:0.);
    // At zero UE rotation, world +Y is physical right, NOT world +X.
    const auto relative=target_eye_from_source({0,0,0},{418000.,312000.,25000.},
        {0,0,0},{418000.,312006.4,25000.});
    auto point=transform(relative,{0,0,100,1});close(point[0],-6.4,1.e-9);close(point[1],0);close(point[2],100);
    auto right=transform(p,point);close(right[0]/right[3],-.064,1.e-9);
    // Large common world positions must not swallow centimeter IPD.
    const auto far=target_eye_from_source({0,0,0},{1.e10,1.e10,1.e10},{0,0,0},{1.e10,1.e10+6.4,1.e10});
    close(far[3],-6.4,1.e-5);
    const auto axes=camera_axes({24.,67.,-19.});
    for(int a=0;a<3;++a)for(int b=0;b<3;++b)close(dot(axes[a],axes[b]),a==b?1.:0.);
    // Common arbitrary head rotation leaves the relative physical eye shift
    // horizontal when the eye displacement follows the rotated right axis.
    Point rp{};for(int k=0;k<3;++k)rp[k]=axes[0][k]*6.4;
    const auto rolled=target_eye_from_source({24.,67.,-19.},{0,0,0},{24.,67.,-19.},rp);
    close(rolled[3],-6.4);close(rolled[7],0);close(rolled[11],0);
    // Unequal eye rotation / vertical baseline must actually change Y.
    const auto unrectified=target_eye_from_source({0,0,0},{0,0,0},{2,0,0},{0,6.4,1.});
    auto unrectified_point=transform(unrectified,{0,0,100,1});assert(std::abs(unrectified_point[1])>1.);
    const auto cropped=crop(p,.25,.25,.75,.75);
    auto center=transform(cropped,{0,0,100,1});close(center[0]/center[3],0);close(center[1]/center[3],0);
    const auto g=build(cropped,cropped,p,{0,0,0},{0,0,0},{0,0,0},{0,6.4,0});assert(g&&g->reverse_depth);
    auto forward=p;forward[10]=1.001;forward[11]=-10.01;
    const auto fg=build(p,forward,forward,{0,0,0},{0,0,0},{0,0,0},{0,6.4,0});assert(fg&&!fg->reverse_depth);
    assert(!inverse(Matrix{}));
    auto invalid=p;invalid[0]=std::numeric_limits<double>::quiet_NaN();
    assert(!build(invalid,p,p,{0,0,0},{0,0,0},{0,0,0},{0,6.4,0}));
    std::cout<<"PASS: full camera-relative transforms, signed physical baseline, Unreal axes, roll/cant/vertical shift, LWC, crop and forward/reverse depth\n";
}
