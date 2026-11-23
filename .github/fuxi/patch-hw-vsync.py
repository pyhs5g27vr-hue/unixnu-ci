#!/usr/bin/env python3
"""patch-hw-vsync.py — 面板 vsync 中断探针（第二版：周期重挂 + 只清自己的位）。

用法：python3 patch-hw-vsync.py hwvsync <AppleARMBacklight.cpp ...>

第二版相对第一版的三处改动（针对实测现象）：
  1. 第一版挂了 SPI 115 后 int27 永远为 0、却每秒看到 ~1000 次「其它位」中断 —— 说明显示驱动后来
     重写了 MDP INTR_EN，把我们的 bit27 抹掉。现在监控线程每 2 秒重新把 bit27 或进去（重挂）。
  2. 中断里只清 bit27/bit29，不再清整个 status（第一版会把显示驱动自己的中断源清掉）。
  3. 用 absolutetime_to_nanoseconds 正确换算窗口长度（第一版算出了 2e9 Hz 的假值）。
启动参数 hw-vsync=1 打开；纯观测，不改面板寄存器与时序。
"""
import pathlib
import sys

CODE = r'''
/* hw-vsync probe v2: SM8550 DPU9 intf_1 vsync = MDP_SSPP_TOP0_INTR bit 27 (intf_1 base 0x35000 = DSI0),
 * MDSS@0x0ae00000 / MDP@0x0ae01000, GIC SPI 83 -> INTID 115 level high.
 * The display driver rewrites INTR_EN after we attach, so the monitor thread re-arms bit 27 every 2 s. */
extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" int armcpu_spi_attach(uint32_t, bool, void (*)(void *), void *, uint32_t *, uint64_t *);
extern "C" int printf(const char *, ...);
extern "C" kern_return_t kernel_thread_start(thread_continue_t, void *, thread_t *);
static volatile uint8_t *hvMdss;
static volatile uint8_t *hvMdp;
static volatile uint64_t hvInt27, hvInt29, hvIntOther;
static void hvMonitor(void *, wait_result_t);
static inline uint32_t hvRd(uint32_t off) { return *(volatile uint32_t *)(hvMdp + off); }
static inline void hvWr(uint32_t off, uint32_t v) {
    *(volatile uint32_t *)(hvMdp + off) = v;
    __asm__ volatile("dsb sy" ::: "memory");
}
static void hvIrq(void *ctx) {
    (void)ctx;
    if (!hvMdp) return;
    const uint32_t status = hvRd(0x14);
    if (!status) return;
    const uint32_t mine = status & ((1u << 27) | (1u << 29));
    if (mine) hvWr(0x18, mine);          /* clear only our own bits; the driver clears its own */
    if (status & (1u << 27)) hvInt27++;
    if (status & (1u << 29)) hvInt29++;
    if (status & ~((1u << 27) | (1u << 29))) hvIntOther++;
}
static void hvAttach(void) {
    hvMdss = (volatile uint8_t *)ml_io_map(0x0ae00000u, 0x1000u);
    hvMdp = (volatile uint8_t *)ml_io_map(0x0ae01000u, 0x8f000u);
    if (!hvMdss || !hvMdp) { printf("fuxi vsync: map failed\n"); return; }
    hvWr(0x18, 0xffffffffu);
    uint32_t readback = 0;
    uint64_t router = 0;
    const int rc = armcpu_spi_attach(115u, false, hvIrq, NULL, &readback, &router);
    printf("fuxi vsync: spi 115 rc %d readback %x router %llx en %x st %x mdss %x\n", rc, readback,
           (unsigned long long)router, hvRd(0x10), hvRd(0x14), *(volatile uint32_t *)hvMdss);
    if (rc) return;
    hvWr(0x10, hvRd(0x10) | (1u << 27) | (1u << 29));
    thread_t thread = THREAD_NULL;
    if (kernel_thread_start(hvMonitor, NULL, &thread) == KERN_SUCCESS) thread_deallocate(thread);
}
static void hvMonitor(void *, wait_result_t) {
    uint64_t last27 = 0, last29 = 0, lastOther = 0, lastT = mach_absolute_time();
    for (;;) {
        IOSleep(2000);
        /* re-arm: the display driver owns INTR_EN and drops our bit when it reconfigures */
        const uint32_t en = hvRd(0x10);
        if (!(en & (1u << 27))) hvWr(0x10, en | (1u << 27));
        const uint64_t t = mach_absolute_time();
        uint64_t ns = 0;
        absolutetime_to_nanoseconds(t - lastT, &ns);
        const uint64_t ms = ns / 1000000ull;
        const uint64_t now27 = hvInt27, now29 = hvInt29, nowOther = hvIntOther;
        const uint64_t d27 = now27 - last27, d29 = now29 - last29;
        printf("fuxi vsync: int27 %llu (+%llu) int29 %llu (+%llu) other %llu over %llu ms -> %llu.%03llu Hz (27) en %x st %x\n",
               (unsigned long long)now27, (unsigned long long)d27,
               (unsigned long long)now29, (unsigned long long)d29,
               (unsigned long long)nowOther, (unsigned long long)ms,
               (unsigned long long)(ms ? d27 * 1000ull / ms : 0),
               (unsigned long long)(ms ? (d27 * 1000000ull / ms) % 1000ull : 0),
               hvRd(0x10), hvRd(0x14));
        last27 = now27; last29 = now29; lastOther = nowOther; lastT = t;
    }
}
'''


def patch(p: pathlib.Path) -> bool:
    t = p.read_text()
    if 'hw-vsync probe v2' in t:
        print('already patched (v2):', p)
        return False
    anchor = 'IOLog("fuxi dpu hz: before'
    i = t.find(anchor)
    assert i > 0, 'fuxi dpu hz anchor missing in %s' % p
    line_start = t.rfind('\n', 0, i) + 1
    call = ('    {   /* hw-vsync=1: count the panel INTF vsync interrupts (v2: re-armed every 2 s) */\n'
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
    print('patched hw-vsync v2 into:', p)
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
