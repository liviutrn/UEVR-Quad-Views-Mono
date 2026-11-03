#pragma once
// Independent aiming projection core for DuoView Mono. No SDK dependencies.
// Matrices are row-major and multiply column vectors: clip = VP * (x,y,z,1).
// The adapter MUST supply a producer-frame VP, and a verified game firing ray.
#include <array>
#include <cmath>
#include <optional>
namespace duoview::aim {
struct Vec3 { double x{}, y{}, z{}; };
struct UV { double u{}, v{}; };
struct Mat4 { std::array<double,16> m{}; };
inline bool finite(Vec3 v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
inline std::optional<UV> project_point(Vec3 p,const Mat4& vp) {
    if(!finite(p)) return std::nullopt;
    for(double e:vp.m) if(!std::isfinite(e)) return std::nullopt;
    const auto& m=vp.m;
    const double x=m[0]*p.x+m[1]*p.y+m[2]*p.z+m[3];
    const double y=m[4]*p.x+m[5]*p.y+m[6]*p.z+m[7];
    const double z=m[8]*p.x+m[9]*p.y+m[10]*p.z+m[11];
    const double w=m[12]*p.x+m[13]*p.y+m[14]*p.z+m[15];
    if(!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(z)||!std::isfinite(w)||w<=1e-6) return std::nullopt;
    const double nx=x/w, ny=y/w, nz=z/w;
    if(!std::isfinite(nx)||!std::isfinite(ny)||!std::isfinite(nz)||
       nx< -1||nx>1||ny< -1||ny>1||nz<0||nz>1) return std::nullopt;
    return UV{(nx+1)*.5,(1-ny)*.5};
}
inline std::optional<UV> project_ray(Vec3 origin,Vec3 direction,double distance_world_units,const Mat4& vp) {
    if(!finite(origin)||!finite(direction)||!std::isfinite(distance_world_units)||distance_world_units<=0) return std::nullopt;
    const double length=std::hypot(direction.x,direction.y,direction.z);
    if(!std::isfinite(length)||length<1e-9) return std::nullopt;
    const double step=distance_world_units/length;
    return project_point({origin.x+direction.x*step,origin.y+direction.y*step,origin.z+direction.z*step},vp);
}
} // namespace duoview::aim
