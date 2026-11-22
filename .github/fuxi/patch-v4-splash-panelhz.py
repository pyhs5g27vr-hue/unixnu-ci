#!/usr/bin/env python3
"""Minimal v4/v5/v6 enhancements:
1) BootWatchdogPolicy.c: fuxi-splash-reset=1 one-shot rename of stale SplashBoard/Snapshots.
2) AppleARMBacklight.cpp: read-only MDSS DPU panel Hz probe (INTF_FRAME_COUNT + INTF_TEAR_INT_COUNT_VAL)
   + optional fuxi-panel-hz=60|90|120 Xiaomi 13 m3_38_0c_0a HS DCS timing switch (default 0 = off).
3) GpuPowerProbe.cpp:
   - upstream UniXNU-sheng/package/GpuPowerProbe.cpp:739 native_adreno_gpu_interrupt(status) in gpuIrq()
   - default fuxi-gpu-restart=1 so hangcheck automatically resets & replays on any stall/fault
   - grant all Metal clients in NativeSandboxGrantProcess ("*")
4) zzw-native-adreno-sandbox-grant.patch:
   - support "*" wildcard in NativeSandboxGrantProcess and honor client->getProperty("NativeSandboxGrant")
"""
import pathlib, sys

def patch_watchdog(p: pathlib.Path):
    t = p.read_text()
    if 'fuxi_boot_splash_reset' in t:
        print('already patched:', p)
        return
    fn_anchor = '// One comma-separated label at *c into the policy as a disabled key; advances *c past it.\n'
    call_anchor = ' fuxi_boot_state_aside(p,scratch);\n'
    assert t.count(fn_anchor) == 1, f'fn_anchor missing in {p}'
    assert t.count(call_anchor) == 1, f'call_anchor missing in {p}'
    splash_fn = (
        'static void fuxi_boot_splash_reset(proc_t p, uint64_t scratch) {\n'
        ' int want = 0;\n'
        ' PE_parse_boot_argn("fuxi-splash-reset", &want, sizeof(want));\n'
        ' if (want != 1) return;\n'
        ' static const char from[] = "/private/var/mobile/Library/SplashBoard/Snapshots";\n'
        ' int error = ENOENT;\n'
        ' char to[128];\n'
        ' for (unsigned n = 1; n <= 9; ++n) {\n'
        '  snprintf(to, sizeof(to), "%s.fuxi-old%u", from, n);\n'
        '  int32_t result = 0;\n'
        '  error = copyout(from, scratch, sizeof(from));\n'
        '  if (!error) error = copyout(to, scratch + 0x200, strlen(to) + 1);\n'
        '  if (error) break;\n'
        '  struct rename_args rn = {.from = scratch, .to = scratch + 0x200};\n'
        '  error = rename(p, &rn, &result);\n'
        '  if (error != EEXIST && error != ENOTEMPTY) break;\n'
        ' }\n'
        ' printf("fuxi splash reset: %s -> %s rc %d\\n", from, error ? "-" : to, error);\n'
        '}\n\n'
    )
    t = t.replace(fn_anchor, splash_fn + fn_anchor, 1)
    t = t.replace(call_anchor, call_anchor + ' fuxi_boot_splash_reset(p,scratch);\n', 1)
    p.write_text(t)
    print('patched BootWatchdogPolicy.c:', p)

def patch_backlight(p: pathlib.Path):
    t = p.read_text()
    if 'fuxiPanelHzThread' in t:
        print('already patched:', p)
        return
    inc_anchor = '#include <pexpert/pexpert.h>\n'
    dsi_anchor = 'int dsiBrightness(uint32_t level) {\n    return dsiSend(gDsi.va, 0xc0390003u, 0xff000051u | ((level & 0xff) << 16) | ((level >> 8) << 8), 2);\n}\n}  // namespace\n'
    start_anchor = '        backlight->release();\n        return;\n    }\n    if (!mapWindow(gGcc, kGcc, 0x60000)'
    assert t.count(inc_anchor) == 1, f'inc_anchor missing in {p}'
    assert t.count(dsi_anchor) == 1, f'dsi_anchor missing in {p}'
    assert t.count(start_anchor) == 1, f'start_anchor missing in {p}'

    hz_code = '''
int dsiSendRetry(uint32_t hdr, uint32_t pay, unsigned w) {
    int rc = 0;
    for (unsigned tries = 0; tries < 200; ++tries) {
        rc = dsiSend(gDsi.va, hdr, pay, w);
        if (rc != 2 && rc != 3) return rc;
        IOSleep(1);
    }
    return rc;
}

void fuxiPanelHzThread(void *, wait_result_t) {
    thread_set_thread_name(current_thread(), "fuxi-dpu-hz");
    IOSleep(15000);
    IODeviceMemory *mem = IODeviceMemory::withRange(0xae01000ull, 0x8f000ull);
    IOMemoryMap *mdpMap = mem ? mem->map(kIOMapAnywhere | kIOMapInhibitCache) : nullptr;
    if (mem) mem->release();
    if (!mdpMap) {IOLog("fuxi dpu hz: mdp map failed\\n"); return;}
    volatile uint32_t *mdp = reinterpret_cast<volatile uint32_t *>(mdpMap->getVirtualAddress());
    auto mrd = [&](uint32_t off) {return mdp[off / 4];};
    constexpr uint32_t kI1 = 0x35000;
    const uint32_t en = mrd(kI1 + 0x6c), cfg = mrd(kI1 + 0x04), sync = mrd(kI1 + 0x288);
    const uint32_t tear = mrd(kI1 + 0x284), autoCfg = mrd(kI1 + 0x2b4);
    const uint32_t f0 = mrd(kI1 + 0xac), te0 = mrd(kI1 + 0x298) >> 16;
    const uint64_t t0 = mach_absolute_time();
    IOSleep(1000);
    const uint32_t f1 = mrd(kI1 + 0xac), te1 = mrd(kI1 + 0x298) >> 16;
    uint64_t ns0 = 0;
    absolutetime_to_nanoseconds(mach_absolute_time() - t0, &ns0);
    IOLog("fuxi dpu hz: before en=%x cfg=%x tear=%x sync=%x auto=%x f=%u..%u df=%u te=%u..%u dte=%u dt=%uus\\n",
          en, cfg, tear, sync, autoCfg, f0, f1, f1 - f0, te0, te1, (te1 - te0) & 0xffffu, (unsigned)(ns0 / 1000));

    unsigned targetHz = 0;
    PE_parse_boot_argn("fuxi-panel-hz", &targetHz, sizeof(targetHz));
    if ((targetHz == 60 || targetHz == 90 || targetHz == 120) && gDsi.va && !gDsiHalt) {
        const uint32_t v60 = targetHz == 120 ? 0x00u : 0x08u;
        const uint32_t vbd = targetHz == 90 ? 0x01u : 0x04u;
        const uint32_t vf2 = targetHz == 90 ? 0x88u : 0x70u;
        struct Pkt {uint32_t hdr, pay; unsigned w;};
        const Pkt seq[8] = {
            {0xc0390003u, 0xff5a5af0u, 2},
            {0x80150060u | (v60 << 8), 0u, 1},
            {0xc0390004u, 0xbd3000b0u, 2},
            {0x801500bdu | (vbd << 8), 0u, 1},
            {0xc0390004u, 0xf21600b0u, 2},
            {0xc0390003u, 0xff0001f2u | (vf2 << 16), 2},
            {0x80150ff7u, 0u, 1},
            {0xc0390003u, 0xffa5a5f0u, 2},
        };
        int rc = 0;
        unsigned step = 0;
        for (; step < 8; ++step) {
            rc = dsiSendRetry(seq[step].hdr, seq[step].pay, seq[step].w);
            if (rc) break;
        }
        IOSleep(200);
        const uint32_t f2 = mrd(kI1 + 0xac), te2 = mrd(kI1 + 0x298) >> 16;
        const uint64_t t1 = mach_absolute_time();
        IOSleep(1000);
        const uint32_t f3 = mrd(kI1 + 0xac), te3 = mrd(kI1 + 0x298) >> 16;
        uint64_t ns1 = 0;
        absolutetime_to_nanoseconds(mach_absolute_time() - t1, &ns1);
        IOLog("fuxi dpu hz: after target=%u step=%u rc=%d f=%u..%u df=%u te=%u..%u dte=%u dt=%uus\\n",
              targetHz, step, rc, f2, f3, f3 - f2, te2, te3, (te3 - te2) & 0xffffu, (unsigned)(ns1 / 1000));
    }
    mdpMap->release();
}
'''

    t = t.replace(inc_anchor, '#include <kern/thread.h>\n' + inc_anchor, 1)
    t = t.replace(dsi_anchor,
                  'int dsiBrightness(uint32_t level) {\n    return dsiSend(gDsi.va, 0xc0390003u, 0xff000051u | ((level & 0xff) << 16) | ((level >> 8) << 8), 2);\n}\n'
                  + hz_code + '}  // namespace\n', 1)
    t = t.replace(start_anchor,
                  '        backlight->release();\n'
                  '        thread_t hzThread = nullptr;\n'
                  '        if (kernel_thread_start(fuxiPanelHzThread, nullptr, &hzThread) == KERN_SUCCESS) thread_deallocate(hzThread);\n'
                  '        return;\n    }\n    if (!mapWindow(gGcc, kGcc, 0x60000)', 1)
    p.write_text(t)
    print('patched AppleARMBacklight.cpp:', p)

def patch_gpupower(p: pathlib.Path):
    t = p.read_text()
    if 'native_adreno_gpu_interrupt' in t:
        print('already patched:', p)
        return
    decl_anchor = 'extern "C" bool native_adreno_preempt_irq() __attribute__((weak));   // NativeAdrenoPublish.cpp\n'
    irq_anchor = (
        '        if (gPreemptCall) thread_call_enter(gPreemptCall);\n'
        '    }\n'
        '    thread_wakeup(event_t(&gIrqCount));\n'
    )
    grant_anchor = '    accelerator->setProperty("NativeSandboxGrantProcess", "backboardd,iconservicesagent,WidgetRenderer_Default,PosterBoard");\n'
    restart_anchor = '        if (bootArg("fuxi-gpu-restart", 0)) native_adreno_set_restart(fuxiGpuRestart, nullptr);'
    assert t.count(decl_anchor) == 1, f'decl_anchor missing in {p}'
    assert t.count(irq_anchor) == 1, f'irq_anchor missing in {p}'
    assert t.count(grant_anchor) == 1, f'grant_anchor missing in {p}'
    assert t.count(restart_anchor) == 1, f'restart_anchor missing in {p}'
    t = t.replace(
        decl_anchor,
        decl_anchor + 'extern "C" void native_adreno_gpu_interrupt(uint32_t status) __attribute__((weak));   // NativeAdrenoPublish.cpp: asks for the completion pass\n',
        1,
    )
    t = t.replace(
        irq_anchor,
        '        if (gPreemptCall) thread_call_enter(gPreemptCall);\n'
        '    }\n'
        '    if (native_adreno_gpu_interrupt) native_adreno_gpu_interrupt(status);\n'
        '    thread_wakeup(event_t(&gIrqCount));\n',
        1,
    )
    t = t.replace(
        grant_anchor,
        '    accelerator->setProperty("NativeSandboxGrantProcess", "*");\n',
        1,
    )
    t = t.replace(
        restart_anchor,
        '        if (bootArg("fuxi-gpu-restart", 1)) native_adreno_set_restart(fuxiGpuRestart, nullptr);',
        1,
    )
    p.write_text(t)
    print('patched GpuPowerProbe.cpp (irq + grant=* + restart=1):', p)

def patch_sandbox_grant(p: pathlib.Path):
    t = p.read_text()
    old = '+	if (!list) {\n+		return false;\n+	}\n'
    new = '+	if (!list) {\n+		return false;\n+	}\n+	if (list->getCStringNoCopy()[0] == \'*\') {\n+		return true;\n+	}\n'
    if "getCStringNoCopy()[0] == '*'" in t:
        print('already patched:', p)
        return
    assert t.count(old) == 1, f'sandbox grant anchor missing in {p}'
    t = t.replace(old, new, 1)
    # Adjust hunk header line count from +4325,36 to +4325,39
    t = t.replace('@@ -4325,6 +4325,36 @@', '@@ -4325,6 +4325,39 @@', 1)
    t = t.replace('@@ -4353,7 +4383,7 @@', '@@ -4353,7 +4386,7 @@', 1)
    t = t.replace('@@ -4512,7 +4542,9 @@', '@@ -4512,7 +4545,9 @@', 1)
    t = t.replace('@@ -4520,6 +4552,7 @@', '@@ -4520,6 +4555,7 @@', 1)
    p.write_text(t)
    print('patched zzw-native-adreno-sandbox-grant.patch:', p)

if __name__ == '__main__':
    mode = sys.argv[1]
    for a in sys.argv[2:]:
        p = pathlib.Path(a)
        if mode == 'watchdog': patch_watchdog(p)
        elif mode == 'backlight': patch_backlight(p)
        elif mode == 'gpupower': patch_gpupower(p)
        elif mode == 'sandbox': patch_sandbox_grant(p)
        else: raise SystemExit(f'unknown mode {mode}')
