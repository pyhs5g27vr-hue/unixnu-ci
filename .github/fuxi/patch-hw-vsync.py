#!/usr/bin/env python3
"""patch-hw-vsync.py — 面板 vsync 中断探针（第三版：SM8550 DPU9 Command Mode INTF1_TEAR_INTR bit 2）。

用法：python3 patch-hw-vsync.py hwvsync <AppleARMBacklight.cpp ...>

第三版改动：
  SM8550 DPU9 上小米 13 Command Mode 面板的 TE 读指针 VSync 中断位于
  MDP_INTF_REV_7xxx_TEAR_OFF(1) = MDP + 0x35800 (EN) / 0x35804 (STATUS) / 0x35808 (CLEAR)
  的 bit 2（intr_tear_rd_ptr），而不是 Video Mode 的 MDP_SSPP_TOP0_INTR (+0x014) bit 27。
启动参数 hw-vsync=1 打开；纯观测，不改面板寄存器与时序。
"""
import pathlib
import sys

CODE = r'''
/* hw-vsync probe v3: SM8550 DPU9 cmd-mode INTF1 TEAR_INTR (MDP+0x35800 EN/0x35804 ST/0x35808 CLR, bit 2 = intr_tear_rd_ptr),
 * MDSS@0x0ae00000 / MDP@0x0ae01000, GIC SPI 83 -> INTID 115 level high.
 * The display driver may clear EN when reconfiguring, so hvMonitor re-arms 0x35800 bit 2 every 2 s. */
extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" int armcpu_spi_attach(uint32_t, bool, void (*)(void *), void *, uint32_t *, uint64_t *);
extern "C" int printf(const char *, ...);
extern "C" kern_return_t kernel_thread_start(thread_continue_t, void *, thread_t *);
static volatile uint8_t *hvMdss;
static volatile uint8_t *hvMdp;
static volatile uint64_t hvTear2, hvIntOther;
static void hvMonitor(void *, wait_result_t);
static inline uint32_t hvRd(uint32_t off) { return *(volatile uint32_t *)(hvMdp + off); }
static inline void hvWr(uint32_t off, uint32_t v) {
    *(volatile uint32_t *)(hvMdp + off) = v;
    __asm__ volatile("dsb sy" ::: "memory");
}
static void hvIrq(void *ctx) {
    (void)ctx;
    if (!hvMdp) return;
    const uint32_t tst = hvRd(0x35804u);
    if (tst & (1u << 2)) {
        hvWr(0x35808u, 1u << 2);         /* clear only our own tear_rd_ptr bit */
        hvTear2++;
    } else {
        hvIntOther++;
    }
}
static void hvAttach(void) {
    hvMdss = (volatile uint8_t *)ml_io_map(0x0ae00000u, 0x1000u);
    hvMdp = (volatile uint8_t *)ml_io_map(0x0ae01000u, 0x8f000u);
    if (!hvMdss || !hvMdp) { printf("fuxi vsync: map failed\n"); return; }
    hvWr(0x35808u, 1u << 2);
    uint32_t readback = 0;
    uint64_t router = 0;
    const int rc = armcpu_spi_attach(115u, false, hvIrq, NULL, &readback, &router);
    printf("fuxi vsync: spi 115 rc %d readback %x router %llx ten %x tst %x mdss %x\n", rc, readback,
           (unsigned long long)router, hvRd(0x35800u), hvRd(0x35804u), *(volatile uint32_t *)hvMdss);
    if (rc) return;
    hvWr(0x35800u, hvRd(0x35800u) | (1u << 2));
    thread_t thread = THREAD_NULL;
    if (kernel_thread_start(hvMonitor, NULL, &thread) == KERN_SUCCESS) thread_deallocate(thread);
}
static void hvMonitor(void *, wait_result_t) {
    uint64_t last2 = 0, lastT = mach_absolute_time();
    for (;;) {
        IOSleep(2000);
        const uint32_t ten = hvRd(0x35800u);
        if (!(ten & (1u << 2))) hvWr(0x35800u, ten | (1u << 2));
        const uint64_t t = mach_absolute_time();
        uint64_t ns = 0;
        absolutetime_to_nanoseconds(t - lastT, &ns);
        const uint64_t ms = ns / 1000000ull;
        const uint64_t now2 = hvTear2, nowOther = hvIntOther;
        const uint64_t d2 = now2 - last2;
        printf("fuxi vsync: tear2 %llu (+%llu) other %llu over %llu ms -> %llu.%03llu Hz (tear2) ten %x tst %x i1st %x topst %x\n",
               (unsigned long long)now2, (unsigned long long)d2,
               (unsigned long long)nowOther, (unsigned long long)ms,
               (unsigned long long)(ms ? d2 * 1000ull / ms : 0),
               (unsigned long long)(ms ? (d2 * 1000000ull / ms) % 1000ull : 0),
               hvRd(0x35800u), hvRd(0x35804u), hvRd(0x351c4u), hvRd(0x014u));
        last2 = now2; lastT = t;
    }
}
'''


def patch(p: pathlib.Path) -> bool:
    t = p.read_text()
    if 'hw-vsync probe v3' in t:
        print('already patched (v3):', p)
        return False
    anchor = 'IOLog("fuxi dpu hz: before'
    i = t.find(anchor)
    assert i > 0, 'fuxi dpu hz anchor missing in %s' % p
    line_start = t.rfind('\n', 0, i) + 1
    call = ('    {   /* hw-vsync=1: count the panel INTF vsync interrupts (v3: DPU9 INTF1_TEAR_INTR bit 2) */\n'
            '        unsigned hvOn = 0;\n'
            '        PE_parse_boot_argn("hw-vsync", &hvOn, sizeof(hvOn));\n'
            '        if (hvOn == 1) hvAttach();\n'
            '    }\n')
    t = t[:line_start] + call + t[line_start:]
    inc = '#include <pexpert/pexpert.h>\n'
    j = t.find(inc)
    assert j > 0, 'include anchor missing in %s' % p
    t = t[:j + len(inc)] + CODE + t[j + len(inc):]
    p.write_text(t)
    print('patched hw-vsync v3 into:', p)
    return True


def main():
    if len(sys.argv) < 3:
        sys.exit('usage: patch-hw-vsync.py hwvsync <AppleARMBacklight.cpp ...>')
    for a in sys.argv[2:]:
        p = pathlib.Path(a)
        if p.exists():
            patch(p)


if __name__ == '__main__':
    main()
