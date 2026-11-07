#!/usr/bin/env python3
"""B28: give native FRenderTarget virtual tables the same lifetime as DuoView.

Run after B26. Preserve render-thread readiness, three physical sources,
packet leases and fenced retirement; remove raw writes into retired resources.
"""
from pathlib import Path
import shutil
import sys


def one(s, old, new):
    if s.count(old) != 1:
        raise RuntimeError(f'B28 targets anchor count {s.count(old)}: {old[:100]!r}')
    return s.replace(old, new, 1)


def transform(s):
    gamma_start=s.index('float VRRenderTargetManager_Base::quadview_native_capture_display_gamma(')
    gamma_end=s.index('\nvoid VRRenderTargetManager_Base::service_quadview_native_target_retirements_after_present',gamma_start)
    s=s[:gamma_start]+'''float VRRenderTargetManager_Base::quadview_native_capture_display_gamma(const sdk::FRenderTarget*) {
    // A table can outlive its owner/world. The callback never follows the
    // viewport or manager pointer; GT refreshes the scalar for live targets.
    return quadview_cached_display_gamma.load(std::memory_order_relaxed);
}
''' + s[gamma_end:]
    start = s.index('struct VRRenderTargetManager_Base::QuadViewNativeTargetOwner {')
    end = s.index('\nbool VRRenderTargetManager_Base::create_ue58_ui_texture()', start)
    b = s[start:end]
    b=one(b, '''    auto* engine=sdk::UGameEngine::get();
    auto* world=engine ? engine->get_world() : nullptr;''',
        '''    // This point is GT-only. Cache the current engine gamma, retaining
    // the previous valid scalar while its viewport is temporarily unavailable.
    if (auto* viewport=get_viewport()) {
        const auto gamma=viewport->get_display_gamma();
        if (std::isfinite(gamma) && gamma>0.0f)
            quadview_cached_display_gamma.store(gamma,std::memory_order_relaxed);
    }
    auto* engine=sdk::UGameEngine::get();
    auto* world=engine ? engine->get_world() : nullptr;''')
    b = one(b, '    std::array<uintptr_t,100> hooked_vtable{};',
               '    const std::array<uintptr_t,100>* hooked_vtable{}; // Process-lifetime immutable table.')
    b = one(b, 'vtable==reinterpret_cast<uintptr_t>(hooked_vtable.data());',
               'hooked_vtable && vtable==reinterpret_cast<uintptr_t>(hooked_vtable->data());')
    restore_start = b.index('                if (owner->gamma_hooked) {')
    restore_end = b.index('                if (safe_to_delete && owner->rooted)', restore_start)
    b = b[:restore_start] + '''                // The hook is a static pure gamma override, just like DuoView.
                // Leave it installed until Unreal destroys its resource. Restoring
                // a saved vptr here can write into a freed/recycled FRenderTarget.
                // No hook table or callback ever refers back to this owner.
                owner->gamma_hooked=false;
''' + b[restore_end:]
    b = one(b, 'std::tuple_size<decltype(QuadViewNativeTargetOwner::hooked_vtable)>::value',
               'std::tuple_size<decltype(QuadViewNativeTargetOwner::original_vtable)>::value')
    b = one(b, '''            owner.hooked_vtable=owner.original_vtable;
            owner.hooked_vtable[*gamma_index]=reinterpret_cast<uintptr_t>(&VRRenderTargetManager_Base::quadview_native_capture_display_gamma);''',
        '''            // Deliberately process-lifetime, bounded to eight engine table variants.
            static auto* gamma_tables=new uevr::quadview::PersistentGammaTables<100>{};
            owner.hooked_vtable=gamma_tables->acquire(original_vtable,owner.original_vtable,*gamma_index,
                reinterpret_cast<uintptr_t>(&VRRenderTargetManager_Base::quadview_native_capture_display_gamma));
            if (!owner.hooked_vtable) {
                std::scoped_lock lock{quadview_native_target_mutex};
                if (quadview_native_target_build==build) quadview_native_target_build.reset();
                SPDLOG_ERROR("[TriView][B28] Persistent gamma-table capacity or identity rejected");
                return true;
            }''')
    b = one(b, 'reinterpret_cast<uintptr_t>(owner.hooked_vtable.data());',
               'reinterpret_cast<uintptr_t>(owner.hooked_vtable->data());')
    # Failed build cancellation must drop only plugin publication. Its engine
    # resource can still execute/destruct with the permanent gamma table.
    loops = [
        '''                for (auto& prior:build->owners) if (prior && prior->gamma_hooked) {
                    *reinterpret_cast<uintptr_t*>(prior->render_target)=prior->original_vtable_address;
                    prior->gamma_hooked=false;
                }
''',
        '''            for (auto& owner:build->owners) { if (owner && owner->gamma_hooked) {
                *reinterpret_cast<uintptr_t*>(owner->render_target)=owner->original_vtable_address;
                owner->gamma_hooked=false;
            }}
''',
        '''                for (auto& owner:build->owners) if (owner && owner->gamma_hooked) {
                    *reinterpret_cast<uintptr_t*>(owner->render_target)=owner->original_vtable_address;
                    owner->gamma_hooked=false;
                }
''',
    ]
    for loop in loops:
        b = one(b, loop, '                // B28: immutable gamma table remains valid through engine resource destruction.\n')
    # No saved-vptr restoration may remain in any cancellation/retirement path.
    if '=owner->original_vtable_address' in b or '=prior->original_vtable_address' in b:
        raise RuntimeError('B28 target retirement still writes saved vptrs')
    s = s[:start] + b + s[end:]
    return '#include "TriViewGammaTables.hpp"\n' + s


def main():
    base=Path(sys.argv[1])/'src/mods/vr'
    p=base/'FFakeStereoRenderingHook.cpp'
    updated=transform(p.read_text(encoding='utf-8'))
    h=base/'FFakeStereoRenderingHook.hpp'
    header=one(h.read_text(encoding='utf-8'),
        '    static float quadview_native_capture_display_gamma(const sdk::FRenderTarget* target);',
        '''    static float quadview_native_capture_display_gamma(const sdk::FRenderTarget* target);
    inline static std::atomic<float> quadview_cached_display_gamma{2.2f};''')
    p.write_text(updated,encoding='utf-8',newline='\n')
    h.write_text(header,encoding='utf-8',newline='\n')
    shutil.copyfile(Path(__file__).with_name('TriViewGammaTables.hpp'),base/'TriViewGammaTables.hpp')
    print('B28: bounded permanent Native Fix gamma tables; no writes into retired source targets')


if __name__=='__main__': main()
