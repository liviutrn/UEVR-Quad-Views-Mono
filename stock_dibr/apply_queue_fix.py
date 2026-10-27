"""R3: observe actual live presentation queues, not only setup queue vtables."""
import pathlib, shutil, sys
root = pathlib.Path(sys.argv[1]).resolve()
here = pathlib.Path(__file__).resolve().parent
def edit(path, old, new):
    target = root/path
    source = target.read_text()
    if source.count(old) != 1:
        raise RuntimeError(f'{path}: expected one R3 anchor, got {source.count(old)}: {old[:100]}')
    target.write_text(source.replace(old, new))
shutil.copyfile(here/'QueueSubmitHook.hpp', root/'src/hooks/QueueSubmitHook.hpp')
hdr = 'src/hooks/D3D12Hook.hpp'
cpp = 'src/hooks/D3D12Hook.cpp'
edit(cpp, '#include "D3D12Hook.hpp"', '#include "D3D12Hook.hpp"\n#include "utility/Logging.hpp"')
edit(hdr, '#include "D3D12DepthStencilObserver.hpp"',
     '#include "D3D12DepthStencilObserver.hpp"\n#include "QueueSubmitHook.hpp"')
edit(hdr, '    std::unique_ptr<PointerHook> m_stock_execute_hook{}, m_stock_begin_hook{}, m_stock_end_hook{};',
     '''    stock_dibr::QueueSubmitHook m_stock_queue_hooks{&D3D12Hook::execute_command_lists};
    std::unique_ptr<PointerHook> m_stock_begin_hook{}, m_stock_end_hook{};''')
edit(cpp, '''        auto& execute_slot = (*(void***)command_queue)[10];
        m_stock_execute_hook = std::make_unique<PointerHook>(&execute_slot, (void*)&D3D12Hook::execute_command_lists);''',
     '''        if (!m_stock_queue_hooks.install(command_queue))
            spdlog::warn("[StockDIBR] Failed to hook setup queue submission");''')
edit(cpp, '    m_stock_execute_hook.reset();', '    m_stock_queue_hooks.clear();')
edit(cpp, '''    if (!self || !self->m_stock_execute_hook) return;
    self->m_stock_execute_hook->get_original<decltype(&D3D12Hook::execute_command_lists)>()(queue, n, lists);''',
     '''    if (!self) return; // QueueSubmitHook has already called this slot's original.''')
edit(cpp, '''        render::D3D12Diagnostics::get().begin_frame(
            d3d12->m_device,''', '''        // Queue implementations/wrappers discovered from the live swapchain
        // need their own slot hook. The dummy queue is not sufficient.
        if (d3d12->m_command_queue) {
            const auto before = d3d12->m_stock_queue_hooks.size();
            if (!d3d12->m_stock_queue_hooks.install(d3d12->m_command_queue)) {
                SPDLOG_ERROR_EVERY_N_SEC(2, "[StockDIBR] Failed to hook live presentation queue");
            } else if (before != d3d12->m_stock_queue_hooks.size()) {
                spdlog::info("[StockDIBR] Hooked live presentation queue 0x{:X}; submission slots={}",
                    reinterpret_cast<uintptr_t>(d3d12->m_command_queue), d3d12->m_stock_queue_hooks.size());
            }
        }
        render::D3D12Diagnostics::get().begin_frame(
            d3d12->m_device,''')
print('Applied R3 live-queue submission hook and shared production test helper')
