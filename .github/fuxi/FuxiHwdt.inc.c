// fuxi hardware watchdog (2026-11-16): a kernel-level hard hang (GPU freeze, USB gone, every thread stopped) must still end in
// fastboot. fuxi-hwdt=<seconds> (5..30) arms the SM8550 APSS watchdog (KPSS layout at 0x17c10000, 32768 Hz sleep clock, as the
// mainline sm8550.dtsi and qcom_wdt use it) with the bite after <seconds>, after first setting the PMIC SDAM reboot reason to
// "bootloader" (BootResetCore.h): a bite resets the SoC and the bootloader then stops in fastboot. A kernel thread pets it every
// second. fuxi-hwdt-test=<seconds> stops the petting after that long, to prove the bite path. Without fuxi-hwdt nothing is touched.
// Included at the end of BootWatchdogPolicy.c; fuxi_hwdt_start() runs once from sheng_boot_watchdog_policy (thread context).
#include <kern/thread.h>
#include <kern/clock.h>
#include <machine/machine_routines.h>
#include "BootResetCore.h"
// The exported machine_routines.h this file is built against has no ml_io_map (run 43774594661: implicit declaration).
extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
enum {FuxiWdtBase = 0x17c10000, FuxiWdtRst = 0x04 / 4, FuxiWdtEn = 0x08 / 4, FuxiWdtSts = 0x0c / 4, FuxiWdtBark = 0x10 / 4,
      FuxiWdtBite = 0x14 / 4, FuxiWdtHz = 32768};
static volatile uint32_t *fuxi_wdt;
static unsigned fuxi_hwdt_test;
volatile uint32_t fuxi_hwdt_state[4];   // [0] stage/error, [1] pets, [2] SDAM before, [3] SDAM after

static void fuxi_hwdt_thread(void *arg, wait_result_t wr) {
  (void)arg; (void)wr;
  for (unsigned n = 0;; ++n) {
    if (fuxi_hwdt_test && n >= fuxi_hwdt_test) {
      printf("fuxi hwdt: test, petting stopped after %u s\n", n);
      fuxi_hwdt_state[0] = 0x7e57;
      return;
    }
    fuxi_wdt[FuxiWdtRst] = 1;
    fuxi_hwdt_state[1] = fuxi_hwdt_state[1] + 1;
    delay_for_interval(1000, 1000 * 1000);   // 1000 x 1 ms
  }
}

static void fuxi_hwdt_start(void) {
  static int started;
  unsigned secs = 0;
  if (started) return;
  started = 1;
  if (!PE_parse_boot_argn("fuxi-hwdt", &secs, sizeof(secs)) || secs < 5) return;
  if (secs > 30) secs = 30;   // the bite counter is 20 bits of 32768 Hz
  (void)PE_parse_boot_argn("fuxi-hwdt-test", &fuxi_hwdt_test, sizeof(fuxi_hwdt_test));
  struct br_arbiter a;
  struct br_found f;
  bzero(&a, sizeof(a));
  bzero(&f, sizeof(f));
  a.core = (volatile uint32_t *)ml_io_map(0xc400000, 0x3000);
  a.cnfg = (volatile uint32_t *)ml_io_map(0xc42d000, 0x4000);
  if (!a.core || !a.cnfg || br_find(&a, &f) || f.owner != 0) {
    fuxi_hwdt_state[0] = 0xe1;
    printf("fuxi hwdt: SDAM not reachable, watchdog not armed\n");
    return;
  }
  unsigned off = BR_OBS_APID_STRIDE * (unsigned)f.apid;
  vm_offset_t obs_page = ml_io_map(0xc440000 + (off & ~4095u), 4096);
  volatile uint32_t *chn = (volatile uint32_t *)ml_io_map(0xc500000 + BR_CHNL_APID_STRIDE * (unsigned)f.apid, 4096);
  if (!obs_page || !chn) {fuxi_hwdt_state[0] = 0xe2; return;}
  uint8_t before = 0xff, after = 0xff;
  // Both pointers already select this APID (EE 0), so the APID argument is 0, as qcom_reset_request does it.
  int rc = br_set_bootloader((volatile uint32_t *)(obs_page + (off & 4095u)), chn, &a, 0, &before, &after);
  fuxi_hwdt_state[2] = before; fuxi_hwdt_state[3] = after;
  printf("fuxi hwdt: SDAM reboot reason %02x -> %02x rc %d\n", before, after, rc);
  if (rc) {fuxi_hwdt_state[0] = 0xe3; return;}
  fuxi_wdt = (volatile uint32_t *)ml_io_map(FuxiWdtBase, 0x1000);
  if (!fuxi_wdt) {fuxi_hwdt_state[0] = 0xe4; return;}
  const uint32_t ticks = secs * FuxiWdtHz;
  fuxi_wdt[FuxiWdtEn] = 0;
  fuxi_wdt[FuxiWdtRst] = 1;
  fuxi_wdt[FuxiWdtBark] = ticks;   // no bark interrupt (EN bit 1 stays clear): the bite is the action
  fuxi_wdt[FuxiWdtBite] = ticks;
  thread_t thread;
  if (kernel_thread_start(fuxi_hwdt_thread, NULL, &thread) != KERN_SUCCESS) {
    fuxi_hwdt_state[0] = 0xe5;
    printf("fuxi hwdt: no petting thread, watchdog left off\n");
    return;
  }
  thread_deallocate(thread);
  fuxi_wdt[FuxiWdtEn] = 1;
  fuxi_hwdt_state[0] = 1;
  printf("fuxi hwdt: armed, bite after %u s without petting (test %u)\n", secs, fuxi_hwdt_test);
}
