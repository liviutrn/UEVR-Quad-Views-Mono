#include "QuadViewGeometry.hpp"
#include <stdexcept>
#include <iostream>
#include <string>
using namespace uevr::quadview;
// B11: MSVC C2512 on the std::source_location default argument (run 21). A plain
// line-number macro is portable.
static void check_at(bool b, int line) { if(!b) throw std::runtime_error(std::string("Depth geometry assertion at line ")+std::to_string(line)); }
#define check(b) check_at((b), __LINE__)
int main() {
    Layout l{}; l.shared_context=true;
    for(double far_plane : {0.,10000.}) {
        std::array<double,16> p{};
        p[0]=1.3;p[5]=1.7;p[8]=.13;p[9]=-.07;p[11]=1.;
        const double near_plane=5.;
        p[10]=far_plane ? -near_plane/(far_plane-near_plane) : 0.;
        p[14]=far_plane ? near_plane*far_plane/(far_plane-near_plane) : near_plane;
        const std::array<std::array<double,3>,2> origins{{{-3.2,.7,-.4},{3.1,-.3,.8}}};
        check(configure_depth_geometry(l,p,origins));
        for(unsigned eye=0;eye<2;++eye) for(double z:{12.,50.,1000.,1.e7})
            for(double x:{-.3,.1,.4}) for(double y:{-.2,.0,.25}) {
                // A known point and eye ray in context coordinates. Rotating a
                // target-eye ray through any optical cant produces this same
                // context ray; the existing homography supplies its UV.
                const auto& t=origins[eye];
                const double px=x*z,py=y*z;
                const std::array<double,2> infinity_uv{
                    .5*(p[0]*(px-t[0])/(z-t[2])+p[8]+1.),
                    .5*(1.-p[5]*(py-t[1])/(z-t[2])-p[9])};
                const auto uv=reproject_context_ray(l,eye,infinity_uv,(p[10]*z+p[14])/z);
                const std::array<double,2> exact{.5*(p[0]*x+p[8]+1.),.5*(1.-p[5]*y-p[9])};
                check(std::abs(uv[0]-exact[0])<1.e-7);
                check(std::abs(uv[1]-exact[1])<1.e-7);
            }
        if (!far_plane) {
            const auto uv=reproject_context_ray(l,0,{.1,.9},0.);
            check(uv[0]==.1 && uv[1]==.9);
        }
        auto bad=p;bad[4]=.1;check(!configure_depth_geometry(l,bad,origins));
        check(!l.depth_geometry_valid);
    }
    // Full chain: different eye frusta and a 20-degree canted right eye.
    auto stereo=make_layout(2000,1800,.5f,.5f,.2f,1.f,{});check(bool(stereo));
    std::array<float,16> left{},right{};
    left[0]=1.2f;left[5]=1.5f;left[8]=.1f;left[9]=-.04f;left[11]=1.f;left[14]=5.f;
    right=left;right[0]=1.35f;right[8]=-.08f;right[9]=.03f;
    const double angle=.3490658503988659;
    const std::array<float,4> qleft{0,0,0,1},qright{0,float(std::sin(angle*.5)),0,float(std::cos(angle*.5))};
    check(apply_shared_context(*stereo,left,right,&qleft,&qright));
    std::array<double,16> context{};
    for(unsigned i=0;i<16;++i) context[i]=left[i];
    context[0]=stereo->context_projection[0];context[8]=stereo->context_projection[1];
    context[5]=stereo->context_projection[2];context[9]=stereo->context_projection[3];
    const std::array<std::array<double,3>,2> origins{{{-3.2,0,0},{3.2,.4,.7}}};
    check(configure_depth_geometry(*stereo,context,origins));
    for(unsigned eye=0;eye<2;++eye) for(double z:{20.,100.,10000.}) {
        const auto& t=origins[eye];
        const double dx=.15*z-t[0],dy=-.1*z-t[1],dz=z-t[2];
        const double c=eye ? std::cos(angle) : 1.,sn=eye ? std::sin(angle) : 0.;
        const double ex=c*dx+sn*dz,ez=-sn*dx+c*dz;
        const auto& ep=eye ? right : left;
        const double u=.5*(ep[0]*ex/ez+ep[8]+1.),v=.5*(1.-ep[5]*dy/ez-ep[9]);
        const auto& h=stereo->context_h[eye];
        const double w=h[8]*u+h[9]*v+h[10];
        const std::array<double,2> infinity_uv{(h[0]*u+h[1]*v+h[2])/w,(h[4]*u+h[5]*v+h[6])/w};
        const auto uv=reproject_context_ray(*stereo,eye,infinity_uv,5./z);
        check(std::abs(uv[0]-.5*(context[0]*.15+context[8]+1.))<2.e-7);
        check(std::abs(uv[1]-.5*(1.-context[5]*(-.1)-context[9]))<2.e-7);
    }
    std::cout<<"Exact asymmetric finite/infinite depth, vertical/forward eye translation, infinity and unsupported projection tests passed\n";
}
