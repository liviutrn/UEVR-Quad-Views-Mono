#pragma once
// Double-precision CPU setup for the camera-relative HLSL input contract.
// Matrices are ROW MAJOR and operate on COLUMN vectors: p'=M*p.
// Camera/view matrices must be obtained BEFORE UE Large World Coordinates
// are truncated to float. This helper cannot undo precision already lost.
#include "StereoBackwardContract.hpp"
#include <array>
#include <cmath>
#include <limits>

namespace uevr::duoview::stereo {
struct Mat4d {
    std::array<double,16> m{};
};
inline Mat4d Multiply(const Mat4d& a, const Mat4d& b) {
    Mat4d out;
    for(int i=0;i<4;++i)
      for(int j=0;j<4;++j)
        for(int k=0;k<4;++k)
          out.m[i*4+j]+=a.m[i*4+k]*b.m[k*4+j];
    return out;
}
inline Mat4d Translate(double x,double y,double z) {
    Mat4d a;
    for(int i=0;i<4;++i) a.m[i*4+i]=1.0;
    a.m[3]=x; a.m[7]=y; a.m[11]=z;
    return a;
}
struct AbsoluteMatrices {
    Mat4d targetWorldFromClip;
    Mat4d sourceDepthClipFromWorld;
    Mat4d sourceDepthWorldFromClip;
    Mat4d sourceColorClipFromWorld;
    std::array<double,3> sourceCameraWorld{};
    std::array<double,3> targetCameraWorld{};
};
inline bool CopyFinite(float* dst, const Mat4d& a) {
    for(int i=0;i<16;++i) {
        if(!std::isfinite(a.m[i]) ||
           std::abs(a.m[i])>static_cast<double>(std::numeric_limits<float>::max()))
            return false;
        dst[i]=static_cast<float>(a.m[i]);
        if(!std::isfinite(dst[i]))return false;
    }
    return true;
}
inline bool ConfigureCameraRelative(BackwardConstants& out,
                                    const AbsoluteMatrices& input,
                                    const std::array<double,3>& origin) {
    for(double v:origin) if(!std::isfinite(v))return false;
    const Mat4d tMinus=Translate(-origin[0],-origin[1],-origin[2]);
    const Mat4d tPlus=Translate(origin[0],origin[1],origin[2]);
    if(!CopyFinite(out.targetWorldFromClip,Multiply(tMinus,input.targetWorldFromClip)) ||
       !CopyFinite(out.sourceDepthClipFromWorld,Multiply(input.sourceDepthClipFromWorld,tPlus)) ||
       !CopyFinite(out.sourceDepthWorldFromClip,Multiply(tMinus,input.sourceDepthWorldFromClip)) ||
       !CopyFinite(out.sourceColorClipFromWorld,Multiply(input.sourceColorClipFromWorld,tPlus)))
        return false;
    for(int i=0;i<3;++i) {
        const double s=input.sourceCameraWorld[i]-origin[i];
        const double t=input.targetCameraWorld[i]-origin[i];
        if(!std::isfinite(s)||!std::isfinite(t)||std::abs(s)>1.0e6||std::abs(t)>1.0e6)
            return false;
        out.sourceCameraWorld[i]=static_cast<float>(s);
        out.targetCameraWorld[i]=static_cast<float>(t);
    }
    out.sourceCameraWorld[3]=0;
    out.targetCameraWorld[3]=0;
    return true;
}
} // namespace
