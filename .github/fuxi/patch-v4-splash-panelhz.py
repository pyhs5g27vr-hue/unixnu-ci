#!/usr/bin/env python3
"""Grand-Slam v9 enhancements:
1) BootWatchdogPolicy.c: fuxi-splash-reset=1 one-shot rename of stale SplashBoard/Snapshots.
2) AppleARMBacklight.cpp: read-only MDSS DPU panel Hz probe + optional fuxi-panel-hz=60|90|120.
3) GpuPowerProbe.cpp:
   - upstream native_adreno_gpu_interrupt(status) in gpuIrq()
   - default fuxi-gpu-restart=1
   - expanded SAFE foreground-app Metal whitelist (adds SpringBoard,Preferences,MobileSafari,MobileSlideShow,MobileNotes,MobileCal; excludes mediaserverd/daemons)
4) ShengBattery.cpp:
   - publish MaximumCapacityPercent + NominalChargeCapacity inside BatteryData (using real ADSP full_mah/design_mah, e.g. 4400/4500 = 98%)
5) FuxiAdspFirmware.cpp:
   - optional fuxi-fw-slot=b boot-arg
6) AdspProbe.cpp:
   - log phys/bytes on PAS_INIT_IMAGE
7) ModemProbe.cpp:
   - test Linux qcom_pas_load() order: PAS_INIT_IMAGE(0x26) BEFORE rails/assignDsm
   - if still rejected, retry after PAS_SHUTDOWN(0x26/4) and test QCOM_SCM_RO arginfo
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
        '    accelerator->setProperty("NativeSandboxGrantProcess", "backboardd,iconservicesagent,WidgetRenderer_Default,PosterBoard,SpringBoard,Preferences,MobileSafari,MobileSlideShow,MobileNotes,MobileCal");\n',
        1,
    )
    t = t.replace(
        restart_anchor,
        '        if (bootArg("fuxi-gpu-restart", 1)) native_adreno_set_restart(fuxiGpuRestart, nullptr);',
        1,
    )
    p.write_text(t)
    print('patched GpuPowerProbe.cpp (irq + safe foreground Metal whitelist + restart=1):', p)

def patch_battery(p: pathlib.Path):
    t = p.read_text()
    if 'MaximumCapacityPercent' in t:
        print('already patched:', p)
        return
    anchor = (
        '        if (OSDictionary *data = OSDictionary::withCapacity(6)) {\n'
        '            auto put = [&](const char *key, int64_t value) {\n'
        '                if (OSNumber *n = OSNumber::withNumber((unsigned long long)value, 32)) {data->setObject(key, n); n->release();}\n'
        '            };\n'
        '            put("StateOfCharge", s.percent);\n'
        '            if (s.raw_mah > 0) put("RaRawCurrentCapacity", s.raw_mah);\n'
        '            if (s.full_mah > 0) put("Qmax", s.full_mah);\n'
        '            if (s.design_mah > 0) put("DesignCapacity", s.design_mah);\n'
        '            if (s.cycles > 0) put("CycleCount", s.cycles);\n'
        '            if (s.voltage_mv > 0) put("Voltage", s.voltage_mv);\n'
    )
    assert t.count(anchor) == 1, f'battery anchor missing in {p}'
    repl = (
        '        const int64_t designMah = s.design_mah > 0 ? s.design_mah : 4500;\n'
        '        const int64_t healthPct = (s.full_mah > 0 && designMah > 0) ? (s.full_mah * 100 / designMah > 100 ? 100 : s.full_mah * 100 / designMah) : 0;\n'
        '        if (healthPct > 0) number("MaximumCapacityPercent", healthPct);\n'
        '        if (OSDictionary *data = OSDictionary::withCapacity(10)) {\n'
        '            auto put = [&](const char *key, int64_t value) {\n'
        '                if (OSNumber *n = OSNumber::withNumber((unsigned long long)value, 32)) {data->setObject(key, n); n->release();}\n'
        '            };\n'
        '            put("StateOfCharge", s.percent);\n'
        '            if (s.raw_mah > 0) put("RaRawCurrentCapacity", s.raw_mah);\n'
        '            if (s.full_mah > 0) {put("Qmax", s.full_mah); put("NominalChargeCapacity", s.full_mah);}\n'
        '            put("DesignCapacity", designMah);\n'
        '            if (healthPct > 0) put("MaximumCapacityPercent", healthPct);\n'
        '            if (s.cycles > 0) put("CycleCount", s.cycles);\n'
        '            if (s.voltage_mv > 0) put("Voltage", s.voltage_mv);\n'
    )
    t = t.replace(anchor, repl, 1)
    p.write_text(t)
    print('patched ShengBattery.cpp (MaximumCapacityPercent + BatteryData):', p)

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
    print('patched FuxiAdspFirmware.cpp:', p)

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
        '    IOLog("fuxi adsp auth: pas=0x%x phys=0x%llx bytes=%llu init=0x%llx/0x%llx\\n", pas, phys, bytes, (unsigned long long)rInit.x0, (unsigned long long)rInit.x1);\n'
        '    if (!scmOk(rInit)) return -1;\n'
    )
    t = t.replace(anchor, repl, 1)
    p.write_text(t)
    print('patched AdspProbe.cpp:', p)

def patch_modem(p: pathlib.Path):
    t = p.read_text()
    if 'fuxi modem v9:' in t:
        print('already patched:', p)
        return
    auth_anchor = (
        '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n'
        '    if (!scmOk(scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0))) return -1;\n'
        '    if (image.mdt.relocatable && !scmOk(scm(QCOM_SCM_PAS_MEM_SETUP, qcom_scm_args(3, 0, 0, 0), pas, base, qcom_mdt_span(&image.mdt))))\n'
        '        return -2;\n'
        '    return 0;\n'
    )
    start_anchor = (
        '    if ((rc = fuxi_adsp_qmp_request("{class: image, res: load_state, name: modem, val: on}", 3000))) {\n'
        '        fail(StLoadState, rc); release(gDtbImage); release(gMpssImage); return false;\n'
        '    }\n'
        '    stage(StLoadState);\n'
        '    if ((rc = rails())) {fail(StRails, rc); release(gDtbImage); release(gMpssImage); return false;}\n'
        '    stage(StRails);\n'
        '    if ((rc = assignDsm())) {fail(StDsm, rc); vote(0, 0); release(gDtbImage); release(gMpssImage); return false;}\n'
        '    stage(StDsm);\n'
        '\n'
        '    if ((rc = authenticateHeader(gDtbImage, kPasDtb, kDtbBase)) || (rc = loadSegments(gDtbImage, kDtbBase, kDtbSize)) ||\n'
        '        (rc = scmOk(scm(QCOM_SCM_PAS_AUTH_AND_RESET, qcom_scm_args(1, 0, 0, 0), kPasDtb, 0, 0)) ? 0 : -3)) {\n'
        '        fail(StDtb, rc); vote(0, 0); release(gDtbImage); release(gMpssImage); return false;\n'
        '    }\n'
    )
    assert t.count(auth_anchor) == 1, f'auth_anchor missing in {p}'
    assert t.count(start_anchor) == 1, f'start_anchor missing in {p}'
    auth_new = (
        '    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);\n'
        '    ScmResult rInit = scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0);\n'
        '    IOLog("fuxi modem v9: pas=0x%x phys=0x%llx bytes=%llu init_rw=0x%llx/0x%llx\\n", pas, phys, bytes, (unsigned long long)rInit.x0, (unsigned long long)rInit.x1);\n'
        '    if (!scmOk(rInit)) {\n'
        '        const ScmResult rSd = scm(QCOM_SCM_PAS_SHUTDOWN, qcom_scm_args(1, 0, 0, 0), pas, 0, 0);\n'
        '        const ScmResult rRo = scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RO, 0), pas, phys, 0);\n'
        '        rInit = scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0);\n'
        '        IOLog("fuxi modem v9: pas=0x%x after_sd=0x%llx ro=0x%llx/0x%llx retry_rw=0x%llx/0x%llx\\n",\n'
        '              pas, (unsigned long long)rSd.x0, (unsigned long long)rRo.x0, (unsigned long long)rRo.x1, (unsigned long long)rInit.x0, (unsigned long long)rInit.x1);\n'
        '        if (!scmOk(rInit)) return -1;\n'
        '    }\n'
        '    if (image.mdt.relocatable) {\n'
        '        const ScmResult rMem = scm(QCOM_SCM_PAS_MEM_SETUP, qcom_scm_args(3, 0, 0, 0), pas, base, qcom_mdt_span(&image.mdt));\n'
        '        IOLog("fuxi modem v9: pas=0x%x mem_setup=0x%llx/0x%llx\\n", pas, (unsigned long long)rMem.x0, (unsigned long long)rMem.x1);\n'
        '        if (!scmOk(rMem)) return -2;\n'
        '    }\n'
        '    return 0;\n'
    )
    start_new = (
        '    // Linux qcom_pas_load() order: init+load DTB metadata BEFORE qcom_pas_start() votes/load_state/auth_and_reset.\n'
        '    if ((rc = authenticateHeader(gDtbImage, kPasDtb, kDtbBase)) || (rc = loadSegments(gDtbImage, kDtbBase, kDtbSize))) {\n'
        '        fail(StDtb, rc); release(gDtbImage); release(gMpssImage); return false;\n'
        '    }\n'
        '    if ((rc = fuxi_adsp_qmp_request("{class: image, res: load_state, name: modem, val: on}", 3000))) {\n'
        '        fail(StLoadState, rc); release(gDtbImage); release(gMpssImage); return false;\n'
        '    }\n'
        '    stage(StLoadState);\n'
        '    if ((rc = rails())) {fail(StRails, rc); release(gDtbImage); release(gMpssImage); return false;}\n'
        '    stage(StRails);\n'
        '    if ((rc = assignDsm())) {fail(StDsm, rc); vote(0, 0); release(gDtbImage); release(gMpssImage); return false;}\n'
        '    stage(StDsm);\n'
        '\n'
        '    if ((rc = scmOk(scm(QCOM_SCM_PAS_AUTH_AND_RESET, qcom_scm_args(1, 0, 0, 0), kPasDtb, 0, 0)) ? 0 : -3)) {\n'
        '        fail(StDtb, rc); vote(0, 0); release(gDtbImage); release(gMpssImage); return false;\n'
        '    }\n'
    )
    t = t.replace(auth_anchor, auth_new, 1)
    t = t.replace(start_anchor, start_new, 1)
    p.write_text(t)
    print('patched ModemProbe.cpp (v9 Linux load-before-start order + shutdown/RO probe):', p)

if __name__ == '__main__':
    mode = sys.argv[1]
    for a in sys.argv[2:]:
        p = pathlib.Path(a)
        if mode == 'watchdog': patch_watchdog(p)
        elif mode == 'backlight': patch_backlight(p)
        elif mode == 'gpupower': patch_gpupower(p)
        elif mode == 'battery': patch_battery(p)
        elif mode == 'fwslot': patch_fwslot(p)
        elif mode == 'adsp': patch_adsp(p)
        elif mode == 'modem': patch_modem(p)
        else: raise SystemExit(f'unknown mode {mode}')
