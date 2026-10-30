// Production math contract: asymmetric physical eyes, moving crops,
// unequal NGX input sizes/subrects, and independently jittered sample grids.
// This proves algebra under an explicit raster-displacement convention;
// it does not authenticate the game's depth-pass camera or jitter sign.
#include "mods/vr/SurfaceGeometry.hpp"
#include "mods/vr/DuoViewNgxGuide.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace uevr::duoview;
static void need(bool b,const char* s){if(!b)throw std::runtime_error(s);}
static double halton(unsigned i,unsigned base){double f=1,r=0;while(i){f/=base;r+=f*(i%base);i/=base;}return r;}
int main()try {
    unsigned checks=0;double worst=0,wrong_sign=0,wrong_dimensions=0,omitted=0;
    for(bool reverse:{false,true})for(unsigned gaze=0;gaze<50;++gaze)for(unsigned phase=1;phase<=64;++phase) {
        auto left=surface::identity(),right=surface::identity();
        left[0]=1.25;left[5]=1.5;left[2]=-.12;
        right[0]=1.31;right[5]=1.43;right[2]=.07;
        for(auto* p:{&left,&right}){(*p)[10]=reverse?0:1;(*p)[11]=reverse?10:-10;(*p)[14]=1;(*p)[15]=0;}
        const double u0=.5*double(gaze%10)/9.,v0=.5*double(gaze/10)/4.;
        const auto cropped=surface::crop(left,u0,v0,u0+.5,v0+.5);
        ngx::Guide gl{},gr{};
        gl.input_width=860;gl.input_height=684;gr.input_width=344;gr.input_height=276;
        gl.jitter_x=float(halton(phase,2)-.5);gl.jitter_y=float(halton(phase,3)-.5);
        gr.jitter_x=float(halton(phase+17,2)-.5);gr.jitter_y=float(halton(phase+17,3)-.5);
        const ngx::Guide guides[]{gl,gr};
        const surface::Matrix projections[]{cropped,right};
        for(unsigned eye=0;eye<2;++eye) {
            const auto& p=projections[eye];const auto j=guides[eye].jitter_uv();
            const double fullU=u0+.5*.43,fullV=v0+.5*.57,z=240.;
            // A physical 6.4-cm baseline changes the target eye-space X.
            const double worldX=((2*fullU-1)-left[2])*z/left[0];
            const double worldY=((1-2*fullV)-left[6])*z/left[5];
            const surface::Vector point{worldX-(eye?6.4:0),worldY,z,1};
            const auto clip=surface::transform(p,point);
            const double u=.5+.5*clip[0]/clip[3],v=.5-.5*clip[1]/clip[3];
            // Raster projection displaces an unjittered sample by +j pixels.
            // Nonzero subrect origins must be added once, before conversion.
            const double rx=eye?11:9,ry=eye?17:13;
            const double sx=rx+u*guides[eye].input_width+guides[eye].jitter_x;
            const double sy=ry+v*guides[eye].input_height+guides[eye].jitter_y;
            const double correctedU=(sx-rx)/guides[eye].input_width-j[0];
            const double correctedV=(sy-ry)/guides[eye].input_height-j[1];
            const auto inv=surface::inverse(p);need(bool(inv),"projection inverse");
            auto restored=surface::transform(*inv,{2*correctedU-1,1-2*correctedV,clip[2]/clip[3],1});
            for(unsigned k=0;k<3;++k) {
                const double e=std::abs(restored[k]/restored[3]-point[k]);worst=std::max(worst,e);
                need(e<1.e-5,"per-eye crop/jitter world reconstruction");++checks;
            }
            const double targetX=rx+(u+j[0])*guides[eye].input_width;
            const double targetY=ry+(v+j[1])*guides[eye].input_height;
            need(std::abs(targetX-sx)<1.e-5&&std::abs(targetY-sy)<1.e-5,"target grid correspondence");
            omitted=std::max(omitted,std::abs(rx+u*guides[eye].input_width-sx));
            wrong_sign=std::max(wrong_sign,std::abs(rx+(u-j[0])*guides[eye].input_width-sx));
            wrong_dimensions=std::max(wrong_dimensions,
                std::abs(rx+(u+guides[eye].jitter_x/3144.)*guides[eye].input_width-sx));
        }
    }
    need(omitted>.45&&wrong_sign>.9&&wrong_dimensions>.3,"negative controls failed");
    std::cout<<"PASS coordinate checks="<<checks<<" max world error="<<worst
        <<" cm; controls max input-pixel error omitted="<<omitted
        <<" wrong-sign="<<wrong_sign<<" output-size="<<wrong_dimensions<<"\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
