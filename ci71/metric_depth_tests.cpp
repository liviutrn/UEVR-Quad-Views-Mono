#include "mods/vr/SurfaceGeometry.hpp"
#include <array>
#include <cmath>
#include <cstdio>
#include <stdexcept>
using namespace uevr::duoview::surface;
static void check(bool a,const char* m){if(!a)throw std::runtime_error(m);}
static Matrix make_projection(double fx,double fy,double near_cm,double far_cm,bool reversed) {
 Matrix p{};
 p[0]=fx;p[5]=fy;p[14]=1.;
 if(reversed) {
  p[10]=-near_cm/(far_cm-near_cm);
  p[11]=far_cm*near_cm/(far_cm-near_cm);
 } else {
  p[10]=far_cm/(far_cm-near_cm);
  p[11]=-far_cm*near_cm/(far_cm-near_cm);
 }
 return p;
}
static double depth_of_z(const Matrix& p,double z) {
 return (p[10]*z+p[11])/(p[14]*z+p[15]);
}
static double forward_z_of_depth(const Matrix& p,double d) {
 return (p[11]-d*p[15])/(d*p[14]-p[10]);
}
int main()try{
 const Point rotation{0,0,0}, left_position{0,-3.6,0}, right_position{0,3.6,0};
 for(const bool reverse:{true,false}) {
  const auto p=make_projection(1.25,1.5,10.0,100000.0,reverse);
  const auto geometry=build(p,p,p,rotation,left_position,rotation,right_position,1.);
  check(bool(geometry),"camera geometry build failed");
  check(geometry->reverse_depth==reverse,"wrong reversed-Z convention");
  auto src_crop=crop(p,.25,.25,.75,.75);
  const auto cropped=build(src_crop,p,p,rotation,left_position,rotation,right_position,1.);
  check(bool(cropped),"cropped physical projection failed");
  for(double z:{40.,100.,200.,500.,2000.}) {
   const auto clip=transform(p,{0.,0.,z,1.});
   const double depth=clip[2]/clip[3];
   check(std::abs(z-forward_z_of_depth(p,depth))<1.e-5*z,"non-metric depth roundtrip");
   const auto view=target_eye_from_source(rotation,left_position,rotation,right_position);
   const auto projected=transform(p,transform(view,{0.,0.,z,1.}));
   const double disparity=projected[0]/projected[3];
   check(std::abs(disparity+1.25*7.2/z)<1.e-9,"wrong 7.2cm physical camera disparity");
   const auto target_clip=transform(p,transform(view,{0.,0.,z,1.}));
   check(std::abs(target_clip[2]/target_clip[3]-depth_of_z(p,z))<1.e-8,"target Z drift");
   check(std::abs(depth-depth_of_z(p,z))<1.e-8,"unexpected NDC Z");
  }
 }
 std::puts("PASS: metric depth roundtrip forward/reversed-Z and native 7.2cm disparity at 40-2000cm");
 return 0;
} catch(const std::exception& e) {std::fprintf(stderr,"%s\n",e.what());return 1;}
