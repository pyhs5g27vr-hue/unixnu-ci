#!/usr/bin/env python3
"""Minimal v4/v5/v7 enhancements:
1) BootWatchdogPolicy.c: fuxi-splash-reset=1 one-shot rename of stale SplashBoard/Snapshots.
2) AppleARMBacklight.cpp: read-only MDSS DPU panel Hz probe + optional fuxi-panel-hz=60|90|120.
3) GpuPowerProbe.cpp:
   - upstream native_adreno_gpu_interrupt(status) in gpuIrq()
   - default fuxi-gpu-restart=1 so hangcheck automatically resets & replays on any stall/fault
   (Safe NativeSandboxGrantProcess whitelist preserved; no "*" wildcard.)
4) FuxiAdspFirmware.cpp:
   - optional fuxi-fw-slot=b boot-arg to mount modem_b before modem_a (default stays modem_a).
5) ModemProbe.cpp:
   - diagnostic logging in authenticateHeader() (pas/phys/bytes/mdt/hash/scm) + PAS_IS_SUPPORTED / PAS 4 probe on DTB failure.
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
    restart_anchor = '        if (bootArg("fuxi-gpu-restart", 0)) native_adreno_set_restart(fuxiGpuRestart, nullptr);'
    assert t.count(decl_anchor) == 1, f'decl_anchor missing in {p}'
    assert t.count(irq_anchor) == 1, f'irq_anchor missing in {p}'
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
        restart_anchor,
        '        if (bootArg("fuxi-gpu-restart", 1)) native_adreno_set_restart(fuxiGpuRestart, nullptr);',
        1,
    )
    p.write_text(t)
    print('patched GpuPowerProbe.cpp (irq + restart=1, safe whitelist):', p)

def patch_fwslot(p: pathlib.Path):
    t = p.read_text()
    if 'fuxi-fw-slot' in t:
        print('already patched:', p)
        return
    inc_anchor = '#include <string.h>\n'
    names_anchor = '    static const char *const names[] = {"modem_a", "modem_b"};\n'
    assert t.count(inc_anchor) == 1, f'inc_anchor missing in {p}'
    assert t.count(names_anchor) == 1, f'names_anchor missing in {p}'
    t = t.replace(inc_anchor, inc_anchor + '#include <pexpert/pexpert.h>\n', 1)
    t = t.replace(
        names_anchor,
        '    char slot[8] = {};\n'
        '    const bool wantB = PE_parse_boot_argn("fuxi-fw-slot", slot, sizeof slot) && (slot[0] == \'b\' || slot[0] == \'B\');\n'
        '    const char *const names[] = {wantB ? "modem_b" : "modem_a", wantB ? "modem_a" : "modem_b"};\n',
        1,
    )
    p.write_text(t)
    print('patched FuxiAdspFirmware.cpp (fuxi-fw-slot=b):', p)

def patch_modem(p: pathlib.Path):
    t = p.read_text()
    if 'fuxi modem auth:' in t:
        print('already patched:', p)
        return
    auth_anchor = (
        '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n'
        '    if (!scmOk(scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0))) return -1;\n'
        '    if (image.mdt.relocatable && !scmOk(scm(QCOM_SCM_PAS_MEM_SETUP, qcom_scm_args(3, 0, 0, 0), pas, base, qcom_mdt_span(&image.mdt))))\n'
        '        return -2;\n'
        '    return 0;\n'
    )
    assert t.count(auth_anchor) == 1, f'auth_anchor missing in {p}'
    auth_new = (
        '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n'
        '    const QcomMdtSegment &hs = image.mdt.segment[image.mdt.hash];\n'
        '    uint32_t w0 = 0, w1 = 0, h0 = 0, h1 = 0;\n'
        '    if (bytes >= 8) {memcpy(&w0, va, 4); memcpy(&w1, va + 4, 4);}\n'
        '    if (bytes >= image.mdt.header_size + 8) {memcpy(&h0, va + image.mdt.header_size, 4); memcpy(&h1, va + image.mdt.header_size + 4, 4);}\n'
        '    const ScmResult rInit = scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0);\n'
        '    IOLog("fuxi modem auth: pas=0x%x phys=0x%llx bytes=%llu hdr=%llu hash[%u]=0x%llx+%llu reloc=%u span=0x%llx elf=%08x/%08x hash=%08x/%08x init=0x%llx(%lld)/0x%llx\\n",\n'
        '          pas, phys, bytes, image.mdt.header_size, image.mdt.hash, hs.file_offset, hs.file_size, image.mdt.relocatable,\n'
        '          qcom_mdt_span(&image.mdt), w0, w1, h0, h1, (unsigned long long)rInit.x0, (long long)rInit.x0, (unsigned long long)rInit.x1);\n'
        '    if (!scmOk(rInit)) {\n'
        '        if (pas == kPasDtb) {\n'
        '            const ScmResult sDtb = scm(QCOM_SCM_PAS_IS_SUPPORTED, qcom_scm_args(1, QCOM_SCM_VAL, 0, 0), kPasDtb, 0, 0);\n'
        '            const ScmResult sMpss = scm(QCOM_SCM_PAS_IS_SUPPORTED, qcom_scm_args(1, QCOM_SCM_VAL, 0, 0), kPasMpss, 0, 0);\n'
        '            IOLog("fuxi modem auth: supported dtb=0x%llx/0x%llx mpss=0x%llx/0x%llx\\n",\n'
        '                  (unsigned long long)sDtb.x0, (unsigned long long)sDtb.x1, (unsigned long long)sMpss.x0, (unsigned long long)sMpss.x1);\n'
        '            const int mpssRc = authenticateHeader(gMpssImage, kPasMpss, kMpssBase);\n'
        '            IOLog("fuxi modem auth: probe mpss rc=%d\\n", mpssRc);\n'
        '            if (!mpssRc) scm(QCOM_SCM_PAS_SHUTDOWN, qcom_scm_args(1, 0, 0, 0), kPasMpss, 0, 0);\n'
        '            native_modem_stats[12] = (int32_t)rInit.x0; native_modem_stats[13] = (int32_t)rInit.x1;\n'
        '        }\n'
        '        return -1;\n'
        '    }\n'
        '    if (image.mdt.relocatable) {\n'
        '        const ScmResult rMem = scm(QCOM_SCM_PAS_MEM_SETUP, qcom_scm_args(3, 0, 0, 0), pas, base, qcom_mdt_span(&image.mdt));\n'
        '        IOLog("fuxi modem auth: pas=0x%x mem_setup base=0x%llx span=0x%llx x0=0x%llx/0x%llx\\n",\n'
        '              pas, base, qcom_mdt_span(&image.mdt), (unsigned long long)rMem.x0, (unsigned long long)rMem.x1);\n'
        '        if (!scmOk(rMem)) return -2;\n'
        '    }\n'
        '    return 0;\n'
    )
    t = t.replace(auth_anchor, auth_new, 1)
    p.write_text(t)
    print('patched ModemProbe.cpp (auth diagnostics):', p)

if __name__ == '__main__':
    mode = sys.argv[1]
    for a in sys.argv[2:]:
        p = pathlib.Path(a)
        if mode == 'watchdog': patch_watchdog(p)
        elif mode == 'backlight': patch_backlight(p)
        elif mode == 'gpupower': patch_gpupower(p)
        elif mode == 'fwslot': patch_fwslot(p)
        elif mode == 'modem': patch_modem(p)
        else: raise SystemExit(f'unknown mode {mode}')
