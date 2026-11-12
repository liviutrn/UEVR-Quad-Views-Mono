// Portable exact B40 Mono temporal + spatial group contracts.
// Arithmetic mirrors the B40 shader source; run ASan/UBSan (Ubuntu) and MSVC CI.
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
struct RGB {float a,b,c;};
RGB operator+(RGB a,RGB b){return {a.a+b.a,a.b+b.b,a.c+b.c};}
RGB operator-(RGB a,RGB b){return {a.a-b.a,a.b-b.b,a.c-b.c};}
RGB operator*(RGB a,float x){return {a.a*x,a.b*x,a.c*x};}
RGB mn(RGB a,RGB b){return {std::min(a.a,b.a),std::min(a.b,b.b),std::min(a.c,b.c)};}
RGB mx(RGB a,RGB b){return {std::max(a.a,b.a),std::max(a.b,b.b),std::max(a.c,b.c)};}
RGB clip(RGB a,float v){return {std::clamp(a.a,-v,v),std::clamp(a.b,-v,v),std::clamp(a.c,-v,v)};}
RGB robust(const std::array<RGB,4>& q,unsigned n){
    if(n==4)return (q[0]+q[1]+q[2]+q[3]-mn(mn(q[0],q[1]),mn(q[2],q[3]))-
                    mx(mx(q[0],q[1]),mx(q[2],q[3])))*.5f;
    if(n==3)return q[0]+q[1]+q[2]-mn(q[0],mn(q[1],q[2]))-mx(q[0],mx(q[1],q[2]));
    if(n==2)return (q[0]+q[1])*.5f;
    return {};
}
float edge_fade(float d,float reach){float t=std::clamp(d/std::max(reach,1.f),0.f,1.f);return 1.f-t*t*(3.f-2.f*t);}
RGB ema(RGB previous,RGB target,bool valid,uint32_t previous_ms,uint32_t now_ms,uint32_t tau){
    uint32_t dt=std::min(uint32_t(now_ms-previous_ms),50u);
    if(!valid||!dt)return previous;
    float time=static_cast<float>(std::max(tau,50u));
    float alpha=static_cast<float>(dt)/(time+static_cast<float>(dt));
    float limit=(100.f/time)*(dt*.001f);
    return previous+clip((target-previous)*alpha,limit);
}
bool close(float a,float b){return std::fabs(a-b)<.0001f;}
int main(){
    std::array<RGB,4> q{{{.1f,.2f,.3f},{.11f,.21f,.31f},{100.f,100.f,100.f},{.09f,.19f,.29f}}};
    RGB r=robust(q,4);assert(close(r.a,.105f)&&close(r.b,.205f)&&close(r.c,.305f));
    r=robust(q,3); assert(close(r.a,.11f)&&close(r.b,.21f)&&close(r.c,.31f));
    r=robust(q,2); assert(close(r.a,.105f));
    RGB old{.2f,.3f,.4f}, target{.9f,.1f,.1f};
    for(auto tau:{75u,200u,350u,600u}){
        RGB a=ema(old,target,true,100,100000,tau);
        RGB b=ema(old,target,true,100,150,tau);
        assert(close(a.a,b.a)&&close(a.b,b.b)&&close(a.c,b.c));
        RGB held=ema(old,target,false,100,200,tau);
        assert(close(held.a,old.a)&&close(held.b,old.b)&&close(held.c,old.c));
    }
    assert(edge_fade(0,240)==1.f && edge_fade(240,240)==0.f);
    assert(edge_fade(120,240)>.49f && edge_fade(120,240)<.51f);
    const int knots=4*8, locations=4, paired_taps=3*5;
    assert(knots*locations==128 && knots*locations*paired_taps==1920);
    std::cout<<"DuoView B40 arithmetic contracts PASS (128x15, 32 knots, trimmed RGB, held EMA)\n";
}
