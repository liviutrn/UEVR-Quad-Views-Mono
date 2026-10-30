#include "mods/vr/DuoViewGeometry.hpp"
#include "mods/vr/SurfaceGeometry.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace uevr::duoview;
using namespace uevr::duoview::surface;
static void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
static Matrix projection(bool reverse) {Matrix p{};p[0]=1.3;p[5]=1.5;p[14]=1.;
 p[10]=reverse?-.0001:1.0001;p[11]=reverse?10.001:-10.001;return p;}
int main()try{
 for(bool reverse:{false,true})
 for(double gazeU:{.25,.33,.50,.68,.75})
 for(double gazeV:{.25,.45,.50,.55,.75}){
  auto layout=make_layout(3000,3000,.5f,.5f,.499f,1.f,float(gazeU),float(gazeV));
  check(bool(layout),"layout invalid");const auto& l=*layout;
  check(l.fovea.width==1500&&l.fovea.height==1500,"fovea wrong dimensions");
  check(l.periphery.width<l.fovea.width&&l.periphery.height<l.fovea.height,"periphery producer not actually smaller");
  check(std::abs(l.u1-l.u0-.5)<1.e-5&&std::abs(l.v1-l.v0-.5)<1.e-5,"crop size");
  auto p=projection(reverse),c=crop(p,l.u0,l.v0,l.u1,l.v1);
  for(double u:{.05,.3,.5,.7,.95})for(double v:{.1,.5,.9}){
   double fullU=l.u0+u*(l.u1-l.u0),fullV=l.v0+v*(l.v1-l.v0);
   const double z=240.,x=(2*fullU-1)*z/p[0],y=(1-2*fullV)*z/p[5];
   auto full=transform(p,{x,y,z,1}),cropped=transform(c,{x,y,z,1});
   check(std::abs(.5+.5*cropped[0]/cropped[3]-u)<1.e-5 &&
         std::abs(.5-.5*cropped[1]/cropped[3]-v)<1.e-5,"jitter-free crop reprojection");
   check(std::abs(.5+.5*full[0]/full[3]-fullU)<1.e-5,"full FOV alignment");
   check(std::abs(full[2]/full[3]-cropped[2]/cropped[3])<1.e-7,"crop changed physical device Z");
  }
  DepthViewport d{9.f,13.f,1080.f,860.f,0.f,1.f};
  check(depth_viewport_valid(d,1100,900),"NGX subrect rejected");
  for(double u:{0.,.125,.5,.875,.999})for(double v:{0.,.125,.5,.875,.999}){
   double x=d.x+u*d.width-.5,y=d.y+v*d.height-.5;
   check(std::abs((x+.5-d.x)/d.width-u)<1.e-9&&
         std::abs((y+.5-d.y)/d.height-v)<1.e-9,"NGX depth active rect lost half-texel alignment");
  }
 }
 std::cout<<"PASS CI73: 50 moving crop layouts, 0.499 peripheral producer, normal/reversed Z, nonzero NGX subrect"<<std::endl;
 return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}
