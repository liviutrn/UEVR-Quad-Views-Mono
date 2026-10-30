#pragma once
// Camera-relative surface reprojection. Matrices below are row-major and act
// on column vectors. Camera positions stay double until their difference has
// been taken. Unreal rotations are (pitch,yaw,roll) in degrees; UE world axes
// are X forward/Y right/Z up, while projection space is X right/Y up/Z forward.
#include <algorithm>
#include <array>
#include <cmath>
#include <optional>

namespace uevr::duoview::surface {
using Matrix = std::array<double, 16>;
using Vector = std::array<double, 4>;
using Point = std::array<double, 3>;
inline Matrix identity() { Matrix m{}; m[0]=m[5]=m[10]=m[15]=1; return m; }
inline Vector transform(const Matrix& m, const Vector& p) {
    Vector out{};
    for(int r=0;r<4;++r)for(int c=0;c<4;++c)out[r]+=m[r*4+c]*p[c];
    return out;
}
inline Matrix multiply(const Matrix& a, const Matrix& b) {
    Matrix out{};
    for(int r=0;r<4;++r)for(int c=0;c<4;++c)for(int k=0;k<4;++k)
        out[r*4+c]+=a[r*4+k]*b[k*4+c];
    return out;
}
inline std::optional<Matrix> inverse(const Matrix& m) {
    double a[4][8]{};
    for(int r=0;r<4;++r)for(int c=0;c<4;++c) {
        if(!std::isfinite(m[r*4+c]))return {};
        a[r][c]=m[r*4+c];a[r][c+4]=r==c?1.:0.;
    }
    for(int col=0;col<4;++col) {
        int pivot=col;
        for(int r=col+1;r<4;++r)if(std::abs(a[r][col])>std::abs(a[pivot][col]))pivot=r;
        if(std::abs(a[pivot][col])<1.e-12)return {};
        if(pivot!=col)for(int c=0;c<8;++c)std::swap(a[pivot][c],a[col][c]);
        const double d=a[col][col];for(double& value:a[col])value/=d;
        for(int r=0;r<4;++r)if(r!=col) {
            const double scale=a[r][col];
            for(int c=0;c<8;++c)a[r][c]-=scale*a[col][c];
        }
    }
    Matrix out{};
    for(int r=0;r<4;++r)for(int c=0;c<4;++c) {
        out[r*4+c]=a[r][c+4];if(!std::isfinite(out[r*4+c]))return {};
    }
    return out;
}
inline Matrix projection(const std::array<float,16>& column_major) {
    Matrix out{};
    for(int r=0;r<4;++r)for(int c=0;c<4;++c)out[r*4+c]=column_major[c*4+r];
    return out;
}
inline Matrix crop(Matrix m,double u0,double v0,double u1,double v1) {
    const double sx=1./(u1-u0),sy=1./(v1-v0);
    const double ox=(1.-u0-u1)*sx,oy=(v0+v1-1.)*sy;
    for(int c=0;c<4;++c) {m[c]=m[c]*sx+m[12+c]*ox;m[4+c]=m[4+c]*sy+m[12+c]*oy;}
    return m;
}
inline std::array<Point,3> camera_axes(const Point& rotation) {
    constexpr double radians=3.14159265358979323846/180.;
    const double p=rotation[0]*radians,y=rotation[1]*radians,r=rotation[2]*radians;
    const double cp=std::cos(p),sp=std::sin(p),cy=std::cos(y),sy=std::sin(y),cr=std::cos(r),sr=std::sin(r);
    const Point right{sr*sp*cy-cr*sy,sr*sp*sy+cr*cy,-sr*cp};
    const Point up{-(cr*sp*cy+sr*sy),cy*sr-cr*sp*sy,cr*cp};
    const Point forward{cp*cy,cp*sy,sp};
    return {right,up,forward};
}
inline double dot(const Point& a,const Point& b) {return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];}
inline Matrix target_eye_from_source(const Point& source_rotation,const Point& source_position,
        const Point& target_rotation,const Point& target_position,double baseline_sign=1.) {
    const auto src=camera_axes(source_rotation),dst=camera_axes(target_rotation);
    Point delta{};
    for(int k=0;k<3;++k)delta[k]=(source_position[k]-target_position[k])*baseline_sign;
    Matrix m=identity();
    for(int r=0;r<3;++r) {
        for(int c=0;c<3;++c)m[r*4+c]=dot(dst[r],src[c]);
        m[r*4+3]=dot(dst[r],delta);
    }
    return m;
}
struct Geometry {
    std::array<float,16> source_eye_from_clip{},target_clip_from_source_eye{},target_full_clip_from_source_eye{};
    bool reverse_depth{};
};
inline std::optional<Geometry> build(const Matrix& source_projection,const Matrix& target_projection,
        const Matrix& target_full_projection,const Point& source_rotation,const Point& source_position,
        const Point& target_rotation,const Point& target_position,double baseline_sign=1.) {
    if(!std::isfinite(baseline_sign)||std::abs(baseline_sign)!=1.)return {};
    for(const auto* p:{&source_rotation,&source_position,&target_rotation,&target_position})
        for(double value:*p)if(!std::isfinite(value))return {};
    const auto inv=inverse(source_projection);if(!inv)return {};
    const auto view=target_eye_from_source(source_rotation,source_position,target_rotation,target_position,baseline_sign);
    const auto target=multiply(target_projection,view),full=multiply(target_full_projection,view);
    Geometry out{};
    for(int k=0;k<16;++k) {
        out.source_eye_from_clip[k]=static_cast<float>((*inv)[k]);
        out.target_clip_from_source_eye[k]=static_cast<float>(target[k]);
        out.target_full_clip_from_source_eye[k]=static_cast<float>(full[k]);
        if(!std::isfinite(out.source_eye_from_clip[k])||!std::isfinite(out.target_clip_from_source_eye[k])||
           !std::isfinite(out.target_full_clip_from_source_eye[k]))return {};
    }
    // d(Az+B)/(Cz+D)/dz has the sign of A*D-B*C.
    const double derivative=target_projection[10]*target_projection[15]-target_projection[11]*target_projection[14];
    if(!std::isfinite(derivative)||std::abs(derivative)<1.e-12)return {};
    out.reverse_depth=derivative<0.;
    return out;
}
}
