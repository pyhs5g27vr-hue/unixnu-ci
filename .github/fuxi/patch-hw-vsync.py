#!/usr/bin/env python3
"""patch-hw-vsync.py — 在 AppleARMBacklight.cpp 里注入面板 vsync 中断探针（只统计，不改显示逻辑）。

用法（与 patch-v4-splash-panelhz.py 一致）：python3 patch-hw-vsync.py hwvsync <AppleARMBacklight.cpp ...>

为什么放这里：该文件已映射 MDSS/MDP 并有面板频率线程，注入点锚定在仓库自己注入的
`fuxi dpu hz: before` 行上，稳定。探针做三件事：
  1. 映射 MDSS 0x0ae00000 / MDP 0x0ae01000（SM8550 dtsi: reg 0x8f000）；
  2. 挂 MDSS 的 GIC 中断（SPI 83 → INTID 115，level high），开 MDP top0 的 INTF1/INTF2 vsync 位；
  3. 中断里 STATUS→CLEAR→按位计数，另有线程每 2 秒打印实测频率。

启动参数 `hw-vsync=1` 打开。纯观测：不写面板寄存器、不改时序，失败即放弃。
"""
import pathlib
import sys

CODE = r'''
/* hw-vsync probe: the panel's own vsync through the MDSS interrupt (SM8550 mdss@0x0ae00000, GIC SPI 83 -> INTID 115,
 * level high; MDP@0x0ae01000, top0 group bits 27/29 = INTF_1/INTF_2 vsync). Counted only: no display state changes. */
extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" int armcpu_spi_attach(uint32_t, bool, void (*)(void *), void *, uint32_t *, uint64_t *);
extern "C" int printf(const char *, ...);
extern "C" kern_return_t kernel_thread_start(thread_continue_t, void *, thread_t *);
static volatile uint8_t *hvMdss;
static volatile uint8_t *hvMdp;
static volatile uint64_t hvInt27, hvInt29, hvIntOther;
static void hvMonitor(void *, wait_result_t);
static void hvIrq(void *ctx) {
    (void)ctx;
    if (!hvMdp) return;
    uint32_t status = *(volatile uint32_t *)(hvMdp + 0x14);
    if (!status) return;
    *(volatile uint32_t *)(hvMdp + 0x18) = status;
    __asm__ volatile("dsb sy" ::: "memory");
    if (status & (1u << 27)) hvInt27++;
    if (status & (1u << 29)) hvInt29++;
    if (status & ~((1u << 27) | (1u << 29))) hvIntOther++;
}
static void hvAttach(void) {
    hvMdss = (volatile uint8_t *)ml_io_map(0x0ae00000u, 0x1000u);
    hvMdp = (volatile uint8_t *)ml_io_map(0x0ae01000u, 0x8f000u);
    if (!hvMdss || !hvMdp) { IOLog("fuxi vsync: map failed\n"); return; }
    *(volatile uint32_t *)(hvMdp + 0x18) = 0xffffffffu;
    __asm__ volatile("dsb sy" ::: "memory");
    uint32_t readback = 0;
    uint64_t router = 0;
    const int rc = armcpu_spi_attach(115u, false, hvIrq, NULL, &readback, &router);
    IOLog("fuxi vsync: spi 115 rc %d readback %x router %llx en %x st %x mdss %x\n", rc, readback,
          (unsigned long long)router, *(volatile uint32_t *)(hvMdp + 0x10),
          *(volatile uint32_t *)(hvMdp + 0x14), *(volatile uint32_t *)hvMdss);
    if (rc) return;
    *(volatile uint32_t *)(hvMdp + 0x10) =
        *(volatile uint32_t *)(hvMdp + 0x10) | (1u << 27) | (1u << 29);
    __asm__ volatile("dsb sy" ::: "memory");
    thread_t thread = THREAD_NULL;
    if (kernel_thread_start(hvMonitor, NULL, &thread) == KERN_SUCCESS) thread_deallocate(thread);
}
static void hvMonitor(void *, wait_result_t) {
    uint64_t last27 = 0, last29 = 0, lastOther = 0, lastT = mach_absolute_time();
    for (;;) {
        IOSleep(2000);
        const uint64_t t = mach_absolute_time(), now27 = hvInt27, now29 = hvInt29, nowOther = hvIntOther;
        uint64_t abs = 0;
        absolutetime_to_nanoseconds(t - lastT, &abs);
        const uint64_t ms = abs / 1000000ull, d27 = now27 - last27, d29 = now29 - last29;
        printf("fuxi vsync: %llu int27 %llu int29 %llu other %llu over %llu ms -> %llu.%03llu Hz (27), %llu Hz (29)\n",
               (unsigned long long)now27, (unsigned long long)now29, (unsigned long long)nowOther,
               (unsigned long long)ms, (unsigned long long)(ms ? d27 * 1000ull / ms : 0),
               (unsigned long long)(ms ? (d27 * 1000000ull / ms) % 1000ull : 0),
               (unsigned long long)(ms ? d29 * 1000ull / ms : 0));
        last27 = now27; last29 = now29; lastOther = nowOther; lastT = t;
    }
}
'''


def patch(p: pathlib.Path) -> bool:
    t = p.read_text()
    if 'hvAttach' in t:
        print('already patched:', p)
        return False
    anchor = 'IOLog("fuxi dpu hz: before'
    i = t.find(anchor)
    assert i > 0, 'fuxi dpu hz anchor missing in %s' % p
    line_start = t.rfind('\n', 0, i) + 1
    call = ('    {   /* hw-vsync=1: count the panel\'s INTF vsync interrupts */\n'
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
    print('patched hw-vsync into:', p)
    return True


def main():
    if len(sys.argv) < 3:
        sys.exit('usage: patch-hw-vsync.py hwvsync <AppleARMBacklight.cpp ...>')
    mode = sys.argv[1]
    for a in sys.argv[2:]:
        p = pathlib.Path(a)
        if not p.exists():
            continue
        if mode == 'hwvsync':
            patch(p)


if __name__ == '__main__':
    main()
