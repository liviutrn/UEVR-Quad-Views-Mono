// DuoView Stereo Hybrid V1 — deterministic high-res forward geometry support.
// LEFT fovea -> RIGHT fovea; reverse RIGHT periphery -> LEFT periphery.
// Independent shader, compiled offline, not enabled in the live XR compositor.
// Depth inputs and color sampling correspond to SAME FRAME, correctly matched
// UE views/projections. ALL matrices use ONE shared camera-relative origin.
Texture2D<float> SourceDepth : register(t0);
Texture2D<float4> SourceColor : register(t1);
Texture2D<float> TargetDepth : register(t2);
Texture2D<float4> TargetRealColor : register(t3);
Texture2D<float4> BackwardColor : register(t4);
Texture2D<float> BackwardConfidence : register(t5);
Texture2D<float4> ForwardColor : register(t6);
Texture2D<float> ForwardConfidence : register(t7);
SamplerState LinearClamp : register(s0);
RWTexture2D<uint> FrontDistance : register(u0);
RWTexture2D<uint> SourceOwner : register(u1);
RWTexture2D<float4> OutForwardColor : register(u2);
RWTexture2D<float> OutForwardConfidence : register(u3);
RWTexture2D<uint> OutForwardReject : register(u4);
RWTexture2D<float4> OutHybridColor : register(u5);
RWTexture2D<float> OutHybridConfidence : register(u6);
RWTexture2D<uint> OutHybridMode : register(u7);

cbuffer HybridSettings : register(b0)
{
    row_major float4x4 SourceWorldFromClip;
    row_major float4x4 SourceColorClipFromWorld;
    row_major float4x4 TargetClipFromWorld;
    row_major float4x4 TargetWorldFromClip;
    float4 SourceCameraWorld;
    float4 TargetCameraWorld;
    float4 SourceDepthRect;
    float4 SourceColorRect;
    float4 TargetDepthRect;
    float4 TargetColorRect;
    float4 Limits;         // x visibilityWorldAbs, y visibilityWorldRel, z minDistance, w maxDistance
    float4 BlendParams;    // x minForwardConfidence, y minBackwardConfidence, z 2ndEyeStrength[unused], w reserved
    uint4 SourceDimensions; // depth W,H, color W,H
    uint4 TargetDimensions; // output W,H, targetDepth W,H
    uint4 Flags;            // x useTargetDepth, y useBackward, z splat2x2 (cost), w reserved
};
// OutHybridMode: 0=real target fallback, 1=backward, 2=forward, 3=both (prefer forward).
// This is deliberately NOT the same as stereo "strength": true eye matrices own disparity.

bool ValidDepth(float d) { return isfinite(d) && d>0.000001f && d<0.999999f; }
bool ValidUV(float2 p) { return all(p>=float2(0,0)) && all(p<float2(1,1)); }
float2 MapUV(float2 uv,float4 rect) { return rect.xy+uv*rect.zw; }
bool Inside(float2 p,float4 rect) {
    return all(rect.zw>float2(0,0))&&
           all(p>=rect.xy)&&all(p<rect.xy+rect.zw)&&ValidUV(p);
}
bool Unproject(float2 uv,float z,row_major float4x4 matrix,out float3 world) {
    const float4 w=mul(matrix,float4(uv.x*2-1,1-uv.y*2,z,1));
    world=float3(0,0,0);
    if(!all(isfinite(w))||abs(w.w)<1e-8f)return false;
    world=w.xyz/w.w;return all(isfinite(world));
}
bool Project(float3 world,row_major float4x4 matrix,out float2 uv,out float z) {
    const float4 p=mul(matrix,float4(world,1));
    uv=float2(0,0);z=0;
    if(!all(isfinite(p))||p.w<=1e-7f)return false;
    const float3 ndc=p.xyz/p.w;uv=float2(.5f*ndc.x+.5f,.5f-.5f*ndc.y);z=ndc.z;
    return all(isfinite(ndc))&&ValidUV(uv)&&z>=0&&z<=1;
}
bool FromSource(uint2 pixel,out float3 world) {
    world=float3(0,0,0);
    if(pixel.x>=SourceDimensions.x||pixel.y>=SourceDimensions.y)return false;
    float2 phys=(float2(pixel)+.5f)/float2(SourceDimensions.xy);
    if(!Inside(phys,SourceDepthRect))return false;
    const float depth=SourceDepth.Load(int3(pixel,0));
    if(!ValidDepth(depth))return false;
    const float2 native=(phys-SourceDepthRect.xy)/SourceDepthRect.zw;
    if(!Unproject(native,depth,SourceWorldFromClip,world))return false;
    const float dist=length(world-TargetCameraWorld.xyz);
    return isfinite(dist)&&dist>=Limits.z&&dist<=Limits.w;
}
bool ToTarget(float3 world,out uint2 pixel,out float dist) {
    pixel=uint2(0,0);dist=0;
    float2 uv;float z;
    if(!Project(world,TargetClipFromWorld,uv,z))return false;
    const float2 position=uv*float2(TargetDimensions.xy);
    pixel=uint2(floor(position));
    dist=length(world-TargetCameraWorld.xyz);
    return pixel.x<TargetDimensions.x&&pixel.y<TargetDimensions.y
        &&dist>=Limits.z&&dist<=Limits.w&&isfinite(dist);
}
void ScatterDepthPixel(uint2 pixel,float dist) {
    uint original;
    InterlockedMin(FrontDistance[pixel],asuint(dist),original);
}
void ScatterOwnerPixel(uint2 pixel,float dist,uint owner) {
    const uint nearBits=FrontDistance[pixel];
    // One-pixel exact depth winner, deterministic tie-break on source index.
    if(asuint(dist)!=nearBits)return;
    uint ignored;InterlockedMin(SourceOwner[pixel],owner,ignored);
}
[numthreads(8,8,1)]
void CSForwardDepth(uint3 id:SV_DispatchThreadID) {
    const uint2 p=id.xy;float3 world;
    if(!FromSource(p,world))return;
    uint2 q;float dist;
    if(!ToTarget(world,q,dist))return;
    ScatterDepthPixel(q,dist);
    if(Flags.z!=0) {
        const uint2 maxp=TargetDimensions.xy-1;
        ScatterDepthPixel(uint2(min(q.x+1,maxp.x),q.y),dist);
        ScatterDepthPixel(uint2(q.x,min(q.y+1,maxp.y)),dist);
        ScatterDepthPixel(min(q+uint2(1,1),maxp),dist);
    }
}
[numthreads(8,8,1)]
void CSForwardOwner(uint3 id:SV_DispatchThreadID) {
    const uint2 p=id.xy;float3 world;
    if(!FromSource(p,world))return;
    uint2 q;float dist;
    if(!ToTarget(world,q,dist))return;
    const uint index=p.y*SourceDimensions.x+p.x;
    ScatterOwnerPixel(q,dist,index);
    if(Flags.z!=0) {
        const uint2 maxp=TargetDimensions.xy-1;
        ScatterOwnerPixel(uint2(min(q.x+1,maxp.x),q.y),dist,index);
        ScatterOwnerPixel(uint2(q.x,min(q.y+1,maxp.y)),dist,index);
        ScatterOwnerPixel(min(q+uint2(1,1),maxp),dist,index);
    }
}
float4 FallbackColor(uint2 p) {
    uint w,h;TargetRealColor.GetDimensions(w,h);
    if(!w||!h)return float4(0,0,0,1);
    float2 uv=(float2(p)+.5f)/float2(TargetDimensions.xy);
    uv=MapUV(uv,TargetColorRect);
    if(!Inside(uv,TargetColorRect))return float4(0,0,0,1);
    const float2 pad=.5f/float2(w,h);
    return TargetRealColor.SampleLevel(LinearClamp,
      clamp(uv,TargetColorRect.xy+pad,TargetColorRect.xy+TargetColorRect.zw-pad),0);
}
void NoForward(uint2 p,uint reason) {
    OutForwardColor[p]=FallbackColor(p);
    OutForwardConfidence[p]=0;
    OutForwardReject[p]=reason;
}
[numthreads(8,8,1)]
void CSForwardResolve(uint3 id:SV_DispatchThreadID) {
    const uint2 p=id.xy;
    if(p.x>=TargetDimensions.x||p.y>=TargetDimensions.y)return;
    uint owner=SourceOwner[p];
    if(owner==0xffffffffu){NoForward(p,1);return;}
    uint2 src=uint2(owner%SourceDimensions.x,owner/SourceDimensions.x);
    float3 world;
    if(!FromSource(src,world)){NoForward(p,2);return;}
    float2 targetUV;float targetZ;
    if(!Project(world,TargetClipFromWorld,targetUV,targetZ)){NoForward(p,4);return;}
    // Conservative visibility test against true RIGHT coarse depth. Set
    // Flags.x=0 for reverse R->L periphery (left target depth unavailable).
    float confidence=1.0f;
    if(Flags.x!=0) {
        uint dw=TargetDimensions.z,dh=TargetDimensions.w;
        if(dw==0||dh==0){NoForward(p,8);return;}
        const float2 dp=MapUV(targetUV,TargetDepthRect);
        if(!Inside(dp,TargetDepthRect)){NoForward(p,16);return;}
        const int2 texel=int2(floor(dp*float2(dw,dh)));
        if(texel.x<0||texel.y<0||texel.x>=int(dw)||texel.y>=int(dh)){
            NoForward(p,16);return;
        }
        const float depth=TargetDepth.Load(int3(texel,0));
        float3 visible;
        if(!ValidDepth(depth)||!Unproject(targetUV,depth,TargetWorldFromClip,visible)){
            NoForward(p,32);return;
        }
        const float err=length(world-visible);
        const float allowed=max(1e-4f,Limits.x+Limits.y*length(world-TargetCameraWorld.xyz));
        if(err>allowed){NoForward(p,64);return;}
        confidence=saturate(1.0f-err/allowed);
    }
    float2 colorUV;float colorZ;
    if(!Project(world,SourceColorClipFromWorld,colorUV,colorZ)){
        NoForward(p,128);return;
    }
    const float2 srcColorUV=MapUV(colorUV,SourceColorRect);
    if(!Inside(srcColorUV,SourceColorRect)){NoForward(p,256);return;}
    const uint2 xy=uint2(floor(srcColorUV*float2(SourceDimensions.zw)));
    if(xy.x>=SourceDimensions.z||xy.y>=SourceDimensions.w){NoForward(p,256);return;}
    OutForwardColor[p]=SourceColor.Load(int3(xy,0));
    OutForwardConfidence[p]=max(confidence,1e-6f);
    OutForwardReject[p]=0;
}
[numthreads(8,8,1)]
void CSHybridFuse(uint3 id:SV_DispatchThreadID) {
    const uint2 p=id.xy;
    if(p.x>=TargetDimensions.x||p.y>=TargetDimensions.y)return;
    const float fc=ForwardConfidence.Load(int3(p,0));
    const float bc=(Flags.y!=0) ? BackwardConfidence.Load(int3(p,0)) : 0.0f;
    const bool forwardOK=fc>=BlendParams.x;
    const bool backwardOK=bc>=BlendParams.y;
    if(forwardOK && (!backwardOK || fc>=bc)){
        OutHybridColor[p]=ForwardColor.Load(int3(p,0));
        OutHybridConfidence[p]=fc;
        OutHybridMode[p]=backwardOK?3u:2u;
    } else if(backwardOK) {
        OutHybridColor[p]=BackwardColor.Load(int3(p,0));
        OutHybridConfidence[p]=bc;OutHybridMode[p]=1u;
    } else {
        OutHybridColor[p]=FallbackColor(p);
        OutHybridConfidence[p]=0;OutHybridMode[p]=0u;
    }
}
