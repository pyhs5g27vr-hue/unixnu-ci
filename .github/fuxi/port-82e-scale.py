#!/usr/bin/env python3
"""fuxi logical display scaling from Kerfand 82e4615 onto the CI's 53f1320c base, verbatim (Claude 2026-11-20, user rule: port, don't rewrite).
82e4615 (README 2026-11-13): logical 1125x2436 scaled by the GPU (AdrenoMetal scanout_scale AIR kernel) to the 1080x2400 panel. On 53f the
iOS 17 kernel has no GPU scanout hand-off at all (Ios17LegacyDisplayProbe.cpp's native_legacy_gpu_offer is a weak no-op, NativeGOPPresenter is
not built, sheng-fb-gpu is not read), so the scale kernel alone would never run. Two modes:

  diffs KERFAND_DIR   (before the unixnu/diffs loop)
    - drivers_AdrenoMetal.diff = 53f's own (NativeAdrenoMetalPlugin.mm) + 82e's four files (GpuScanoutClient.h, GpuScanoutPresenter.h,
      bridge/FuxiScanoutScaleAir.c, shaders/scanout_convert.ll), minus GpuScanoutClient.h's first hunk: a comment rename (fb-gpu ->
      sheng-fb-gpu) that a0f0287 already carries, which made git apply reject the whole file. Its second hunk (the failed copy's result in
      the completion's low bits) is kept. The workflow must not SKIP_FILES GpuScanoutClient.h in this mode.
    - drivers_GopFramebuffer.diff = 82e's (same base 19ef3a7): logical-mode frames go to the GPU too (!(gScaled && half)), iOS 17's
      single-plane '&BGA' row in elements, the surface probe and the GOP USB screenshot (weak imports).
  tree FILE...        (after the device-ios17 tree is assembled; every existing copy is patched once)
    82e's GPU scanout hand-off: build-ios17-legacy-display.py builds NativeGOPPresenter (late static init) into the display archive,
    Ios17LegacyDisplayProbe.cpp starts the presenter with sheng-fb-gpu=1 and offers frames to it, build-ios17-stubs.py makes the
    hand-off no-ops and native_gop_wait_stats weak (the presenter defines them).
"""
import re, sys, urllib.request
from pathlib import Path

R82 = '82e46156e8e0cebd331a8e152954b5ca3ffff7c7'
R53 = '53f1320c12d924eb9c88616b4adf9e66786f18e9'
RAW = 'https://raw.githubusercontent.com/Kerfand/UniXNU-Fuxi-Arm64e-iOS17/%s/'

def get(rev, path):
    for i in range(3):
        try:
            return urllib.request.urlopen(RAW % rev + path, timeout=60).read().decode('utf-8', 'surrogateescape')
        except Exception as e:
            err = e
    raise SystemExit('fetch %s %s: %s' % (rev[:7], path, err))

def blocks(t):
    return [b for b in re.split(r'(?m)^(?=diff --git )', t) if b.startswith('diff --git ')]

def drop_first_hunk(block):
    head, *hunks = re.split(r'(?m)^(?=@@ )', block)
    assert len(hunks) == 2 and 'sheng-fb-gpu' in hunks[0] and '0xe00002b0u' in hunks[1], 'GpuScanoutClient.h hunks changed'
    return head + hunks[1]

def diffs(k):
    d = Path(k) / 'unixnu/diffs'
    own = blocks(get(R53, 'unixnu/diffs/drivers_AdrenoMetal.diff'))
    scale = blocks(get(R82, 'unixnu/diffs/drivers_AdrenoMetal.diff'))
    names = [b.split()[2][2:] for b in scale]
    assert names == ['GpuScanoutClient.h', 'GpuScanoutPresenter.h', 'bridge/FuxiScanoutScaleAir.c', 'shaders/scanout_convert.ll'], names
    assert not set(names) & {b.split()[2][2:] for b in own}
    scale[0] = drop_first_hunk(scale[0])
    (d / 'drivers_AdrenoMetal.diff').write_text(''.join(own + scale), encoding='utf-8', errors='surrogateescape')
    gop = get(R82, 'unixnu/diffs/drivers_GopFramebuffer.diff')
    assert '!(gScaled && half)' in gop
    (d / 'drivers_GopFramebuffer.diff').write_text(gop, encoding='utf-8', errors='surrogateescape')
    print('scale 82e: drivers_AdrenoMetal.diff = 53f + 82e (%s, GpuScanoutClient.h hunk 2 only); drivers_GopFramebuffer.diff = 82e' % ', '.join(names))

def once(s, old, new, what):
    assert s.count(old) == 1, (what, s.count(old))
    return s.replace(old, new, 1)

def legacy_display(s):
    if 'NativeGOPPresenter' in s: return None
    s = once(s, '# The launchd job policy (kits/sheng/BootWatchdogPolicy.c)',
        "# The GPU scanout hand-off (sheng-fb-gpu=1, as the iPadOS build-native-legacy-display.py builds it): the Metal plugin's\n"
        "# GpuScanoutClient copies each frame into the GOP scanout on the GPU through the Adreno driver's 0x7000 methods. Without it the iOS 17\n"
        "# display copied every frame on the CPU (native_legacy_copy_pixels, 2026-11-12 samples). Its static initializer runs late (probe).\n"
        "subprocess.run(['python3', str(ROOT / 'scripts/build-arm-driver.py'), 'NativeGOPPresenter'], check=True)\n"
        "gop_late = ROOT / 'build/native-gop-presenter/NativeGOPPresenter.late.o'\n"
        "run(['llvm-objcopy', '--remove-section=__DATA,__mod_init_func', '--globalize-symbol=__GLOBAL__sub_I_NativeGOPPresenter.cpp',\n"
        "     ROOT / 'build/native-gop-presenter/NativeGOPPresenter.o', gop_late])\n\n"
        '# The launchd job policy (kits/sheng/BootWatchdogPolicy.c)', 'gop build')
    return once(s, 'keyevents_late, policy_obj', 'keyevents_late, gop_late, policy_obj', 'archive')

def probe(s):
    if 'native_gop_presenter_create' in s: return None
    s = once(s, 'extern "C" void native_legacy_display_static_init(void) __asm__("__GLOBAL__sub_I_NativeLegacyDisplay.cpp");\n',
        'extern "C" void native_legacy_display_static_init(void) __asm__("__GLOBAL__sub_I_NativeLegacyDisplay.cpp");\n'
        '// The GPU scanout hand-off (drivers/GopFramebuffer/NativeGOPPresenter.cpp, boot-arg sheng-fb-gpu=1), as the iPadOS LegacyDisplayProbe.cpp\n'
        '// sets it up: created after the display started, attached to the resource service (not under the display subsystem node, whose\n'
        '// children the original display code enumerates), its framebuffer memory taken from the GOP nub.\n'
        'extern "C" void native_gop_presenter_static_init(void) __asm__("__GLOBAL__sub_I_NativeGOPPresenter.cpp");\n'
        'extern "C" IOService *native_gop_presenter_create(void);\n'
        'extern "C" void native_gop_presenter_set_source(IOService *presenter, IOService *nub);\n'
        'extern "C" bool native_gop_gpu_offer(IOService *, void *display, IOMemoryDescriptor *, uint64_t stride, uint32_t width, uint32_t height,\n'
        '    uint32_t format);\n'
        'static IOService *gpuHandoffPresenter;\n', 'decls')
    s = once(s, '__attribute__((weak)) bool native_legacy_gpu_offer(void *, IOMemoryDescriptor *, uint64_t, uint32_t, uint32_t, uint32_t) { return false; }\n'
                'void native_legacy_gpu_fallback_observed(int) { native_legacy_gpu_fallbacks = native_legacy_gpu_fallbacks + 1; }\n',
        '// Was a no-op returning false: every frame took the CPU copy. Hands the frame to the GPU when the presenter is up.\n'
        'bool native_legacy_gpu_offer(void *display, IOMemoryDescriptor *memory, uint64_t stride, uint32_t width, uint32_t height, uint32_t format)\n'
        '{ return gpuHandoffPresenter && native_gop_gpu_offer(gpuHandoffPresenter, display, memory, stride, width, height, format); }\n'
        'volatile int32_t native_legacy_gpu_last_status;\n'
        'void native_legacy_gpu_fallback_observed(int status) { native_legacy_gpu_last_status = status; native_legacy_gpu_fallbacks = native_legacy_gpu_fallbacks + 1; }\n',
        'offer')
    s = once(s, '\tnative_legacy_display_static_init();\n', '\tnative_legacy_display_static_init();\n\tnative_gop_presenter_static_init();\n', 'static init')
    return once(s, '\t\t\t\tactiveLegacyDisplay = display; activeNub = nub;\n',
        '\t\t\t\tactiveLegacyDisplay = display; activeNub = nub;\n'
        '\t\t\t\t{\n'
        '\t\t\t\t\tunsigned gpu = 0; PE_parse_boot_argn("sheng-fb-gpu", &gpu, sizeof gpu);\n'
        '\t\t\t\t\tif (gpu == 1) {\n'
        '\t\t\t\t\t\tIOService *handoff = native_gop_presenter_create();\n'
        '\t\t\t\t\t\tIOService *home = IOService::getResourceService();\n'
        '\t\t\t\t\t\tbool handoffAttached = false;\n'
        '\t\t\t\t\t\tif (handoff && home) native_gop_presenter_set_source(handoff, nub);\n'
        '\t\t\t\t\t\tif (handoff && home && handoff->init() && (handoffAttached = handoff->attach(home)) && handoff->start(home)) gpuHandoffPresenter = handoff;\n'
        '\t\t\t\t\t\telse { if (handoffAttached) handoff->detach(home); OSSafeReleaseNULL(handoff); }\n'
        '\t\t\t\t\t\tprintf("ios17 legacy display: GPU hand-off presenter %s\\n", gpuHandoffPresenter ? "started" : "failed");\n'
        '\t\t\t\t\t}\n'
        '\t\t\t\t}\n', 'presenter start')

def stubs(s):
    if '__attribute__((weak)) int native_gop_handoff_call' in s: return None
    s = once(s, "handoff_stubs = '''int native_gop_handoff_call(", "handoff_stubs = '''__attribute__((weak)) int native_gop_handoff_call(", 'handoff call')
    s = once(s, 'void *native_gop_handoff_memory(void) { return 0; }', '__attribute__((weak)) void *native_gop_handoff_memory(void) { return 0; }', 'handoff memory')
    return once(s, "'volatile int32_t native_touch_extent[4];', 'volatile uint32_t native_touch_edge_stats[4];'):",
        "'volatile int32_t native_touch_extent[4];', 'volatile uint32_t native_touch_edge_stats[4];',\n"
        "                 # NativeGOPPresenter.cpp (the GPU scanout hand-off, sheng-fb-gpu=1) defines its wait counters.\n"
        "                 'volatile uint64_t native_gop_wait_stats[7];'):", 'wait stats')

def tree(files):
    seen, done = set(), {}
    for f in map(Path, files):
        if not f.is_file(): print('scale 82e: %s not found' % f); continue
        r = f.resolve()
        if r in seen: continue
        seen.add(r)
        fn = {'build-ios17-legacy-display.py': legacy_display, 'Ios17LegacyDisplayProbe.cpp': probe, 'build-ios17-stubs.py': stubs}[f.name]
        s = fn(r.read_text())
        if s is None: print('scale 82e: %s already has it' % f)
        else: r.write_text(s); print('scale 82e: patched %s' % f)
        done[f.name] = True
    assert len(done) == 3, ('scale 82e: missing', done)

if __name__ == '__main__':
    if sys.argv[1] == 'diffs': diffs(sys.argv[2])
    elif sys.argv[1] == 'tree': tree(sys.argv[2:])
    else: raise SystemExit(__doc__)
