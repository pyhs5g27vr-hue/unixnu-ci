#!/usr/bin/env python3
"""Grand-Slam v11:
1) BootWatchdogPolicy.c: fuxi-splash-reset=1.
2) AppleARMBacklight.cpp: fuxi-panel-hz=60|90|120.
3) GpuPowerProbe.cpp:
   - upstream native_adreno_gpu_interrupt(status) in gpuIrq()
   - default fuxi-gpu-restart=1
   - SAFE Metal whitelist: 4 proven system procs + 3 user apps (Preferences,MobileSafari,MobileSlideShow) — NO SpringBoard, NO mediaserverd!
4) FuxiAdspFirmware.cpp:
   - optional fuxi-fw-slot=b
   - export fuxi_modem_list_image() to list modem/spss/ipa/dtb filenames in modem_a:/image/
5) ModemProbe.cpp:
   - on PAS_INIT_IMAGE(0x26) failure, call fuxi_modem_list_image() AND scan SM8550 IMEM (0x14680000+0x2c000) for tzbsp_diag / ASCII TZ error log!
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
        '    accelerator->setProperty("NativeSandboxGrantProcess", "backboardd,iconservicesagent,WidgetRenderer_Default,PosterBoard,Preferences,MobileSafari,MobileSlideShow");\n',
        1,
    )
    t = t.replace(
        restart_anchor,
        '        if (bootArg("fuxi-gpu-restart", 1)) native_adreno_set_restart(fuxiGpuRestart, nullptr);',
        1,
    )
    p.write_text(t)
    print('patched GpuPowerProbe.cpp (safe 4+3 user apps whitelist, NO SpringBoard):', p)

def patch_fwslot(p: pathlib.Path):
    t = p.read_text()
    if 'fuxi_modem_probe_files' in t:
        print('already patched:', p)
        return
    inc_anchor = '#include <string.h>\n'
    names_anchor = '    static const char *const names[] = {"modem_a", "modem_b"};\n'
    end_anchor = 'extern "C" void sheng_fw_close(void *handle) {\n    if (handle) IOFree(handle, sizeof(ModemImage));\n}\n'
    assert t.count(inc_anchor) == 1, f'inc_anchor missing in {p}'
    assert t.count(names_anchor) == 1, f'names_anchor missing in {p}'
    assert t.count(end_anchor) == 1, f'end_anchor missing in {p}'
    t = t.replace(inc_anchor, inc_anchor + '#include <pexpert/pexpert.h>\n', 1)
    t = t.replace(
        names_anchor,
        '    char slot[8] = {};\n'
        '    const bool wantB = PE_parse_boot_argn("fuxi-fw-slot", slot, sizeof slot) && (slot[0] == \'b\' || slot[0] == \'B\');\n'
        '    const char *const names[] = {wantB ? "modem_b" : "modem_a", wantB ? "modem_a" : "modem_b"};\n',
        1,
    )
    probe_fn = '''
extern "C" void fuxi_modem_probe_files(void) {
    if (!gVolume) return;
    static const char *const cand[] = {
        "image/modem_dtb.mdt", "image/modem.mdt", "image/modem_dtb.mbn", "image/modem.mbn",
        "image/spss1t.b00", "image/spss1t.mdt", "image/ipa_fws.b00", "image/ipa_fws.mdt",
        "image/modem_pr/mcfg/configs/mcfg_sw/generic/common/wildcard/wildcard/mcfg_sw.mbn",
        "image/mba.mbn", "image/qdsp6m.qdb", "image/modemr.jsn"
    };
    for (unsigned i = 0; i < sizeof cand / sizeof cand[0]; ++i) {
        FatFile f = {};
        const int rc = fat_open(gVolume, cand[i], &f);
        if (!rc) IOLog("fuxi modem file: %s size=%u\\n", cand[i], f.size);
    }
}
'''
    t = t.replace(end_anchor, end_anchor + probe_fn, 1)
    p.write_text(t)
    print('patched FuxiAdspFirmware.cpp (fuxi-fw-slot + file probe):', p)

def patch_adsp(p: pathlib.Path):
    t = p.read_text()
    if 'fuxi adsp auth:' in t:
        print('already patched:', p)
        return
    anchor = '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n    if (!scmOk(scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0))) return -1;\n'
    assert t.count(anchor) == 1, f'adsp auth anchor missing in {p}'
    repl = (
        '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n'
        '    const ScmResult rInit = scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0);\n'
        '    IOLog("fuxi adsp auth: pas=0x%x init=0x%llx\\n", pas, (unsigned long long)rInit.x0);\n'
        '    if (!scmOk(rInit)) return -1;\n'
    )
    t = t.replace(anchor, repl, 1)
    p.write_text(t)
    print('patched AdspProbe.cpp:', p)

def patch_modem(p: pathlib.Path):
    t = p.read_text()
    if 'fuxi modem v12b:' in t:
        print('already patched:', p)
        return
    decl_anchor = 'void sheng_fw_close(void *handle);\n'
    auth_anchor = (
        '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n'
        '    if (!scmOk(scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0))) return -1;\n'
        '    if (image.mdt.relocatable && !scmOk(scm(QCOM_SCM_PAS_MEM_SETUP, qcom_scm_args(3, 0, 0, 0), pas, base, qcom_mdt_span(&image.mdt))))\n'
        '        return -2;\n'
        '    return 0;\n'
    )
    assert t.count(decl_anchor) == 1, f'decl_anchor missing in {p}'
    assert t.count(auth_anchor) == 1, f'auth_anchor missing in {p}'
    t = t.replace(decl_anchor, decl_anchor + 'void fuxi_modem_probe_files(void) __attribute__((weak));\n', 1)
    auth_new = (
        '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n'
        '    const ScmResult rInit = scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0);\n'
        '    IOLog("fuxi modem v12b: pas=0x%x phys=0x%llx bytes=%llu init=0x%llx/0x%llx\\n", pas, phys, bytes, (unsigned long long)rInit.x0, (unsigned long long)rInit.x1);\n'
        '    if (!scmOk(rInit)) {\n'
        '        if (pas == kPasDtb) {\n'
        '            Window im = {};\n'
        '            if (mapWindow(im, 0x146aa000ull, 0x1000ull)) {\n'
        '                const uint32_t diagPtr = rd(im, 0x720);\n'
        '                const uint32_t w1 = rd(im, 0x724), w2 = rd(im, 0x728), w3 = rd(im, 0x72c);\n'
        '                IOLog("fuxi tzlog: @146aa720=%08x %08x %08x %08x\\n", diagPtr, w1, w2, w3);\n'
        '                unmap(im);\n'
        '                if ((diagPtr >= 0x14680000u && diagPtr < 0x146ac000u) || (diagPtr >= 0x80000000u && diagPtr < 0xf0000000u)) {\n'
        '                    const uint64_t pg = diagPtr & ~0xfffull;\n'
        '                    const uint32_t pgOff = diagPtr & 0xfffu;\n'
        '                    Window dw = {};\n'
        '                    if (mapWindow(dw, pg, 0x4000ull)) {\n'
        '                        const uint32_t magic = rd(dw, pgOff + 0x00);\n'
        '                        const uint32_t ver   = rd(dw, pgOff + 0x04);\n'
        '                        const uint32_t roff  = rd(dw, pgOff + 0x1c);\n'
        '                        const uint32_t rlen  = rd(dw, pgOff + 0x20);\n'
        '                        IOLog("fuxi tzlog: hdr magic=%08x ver=%u ring_off=0x%x ring_len=0x%x\\n", magic, ver, roff, rlen);\n'
        '                        if (roff > 0 && roff < 0x3000u && rlen > 0 && roff + rlen <= 0x3f00u) {\n'
        '                            const uint32_t dumpLen = (rlen > 768u ? 768u : rlen) & ~3u;\n'
        '                            const uint32_t start = (rlen - dumpLen) & ~3u;\n'
        '                            char line[97];\n'
        '                            uint32_t pos = 0;\n'
        '                            for (uint32_t k = 0; k < dumpLen; k += 4) {\n'
        '                                const uint32_t w = rd(dw, pgOff + roff + start + k);\n'
        '                                for (unsigned b = 0; b < 4; b++) {\n'
        '                                    uint8_t c = (uint8_t)((w >> (b * 8u)) & 0xffu);\n'
        '                                    if (c == 0x0a || c == 0x0d || pos == 96) {\n'
        '                                        if (pos > 0) { line[pos] = 0; IOLog("fuxi tzlog: %s\\n", line); pos = 0; }\n'
        '                                        continue;\n'
        '                                    }\n'
        '                                    if (c >= 0x20 && c <= 0x7e) line[pos++] = (char)c;\n'
        '                                }\n'
        '                            }\n'
        '                            if (pos > 0) { line[pos] = 0; IOLog("fuxi tzlog: %s\\n", line); }\n'
        '                        }\n'
        '                        unmap(dw);\n'
        '                    }\n'
        '                }\n'
        '            }\n'
        '            native_modem_stats[12] = (int32_t)rInit.x0; native_modem_stats[13] = (int32_t)rInit.x1;\n'
        '        }\n'
        '        return -1;\n'
        '    }\n'
        '    if (image.mdt.relocatable && !scmOk(scm(QCOM_SCM_PAS_MEM_SETUP, qcom_scm_args(3, 0, 0, 0), pas, base, qcom_mdt_span(&image.mdt))))\n'
        '        return -2;\n'
        '    return 0;\n'
    )
    t = t.replace(auth_anchor, auth_new, 1)
    p.write_text(t)
    print('patched ModemProbe.cpp (v12b rd() tz-log):', p)

if __name__ == '__main__':
    mode = sys.argv[1]
    for a in sys.argv[2:]:
        p = pathlib.Path(a)
        if mode == 'watchdog': patch_watchdog(p)
        elif mode == 'backlight': patch_backlight(p)
        elif mode == 'gpupower': patch_gpupower(p)
        elif mode == 'fwslot': patch_fwslot(p)
        elif mode == 'adsp': patch_adsp(p)
        elif mode == 'modem': patch_modem(p)
        else: raise SystemExit(f'unknown mode {mode}')
