// fuxi hardware watchdog (2026-11-16): a kernel-level hard hang (GPU freeze, USB gone, every thread stopped) must still end in
// fastboot. fuxi-hwdt=<seconds> (5..32) first sets the PMIC SDAM reboot reason to "bootloader" (BootResetCore.h), then arms the
// Gunyah hypervisor watchdog with bark = bite = <seconds>; a kernel thread pings it every second. fuxi-hwdt-test=<seconds> stops the
// pings after that long, to prove the bite path. Without fuxi-hwdt nothing is touched.
// The APSS WDT registers at 0x17c10000 belong to Gunyah: the first EL1 write gave a synchronous external abort (run 43778207871,
// far = map + 8). The hypervisor's own watchdog service is used instead, as the Linux gunyah_wdt driver (v8, 2025-11) does it:
// SMCCC fast calls, SMC32, owner vendor hyp: CONTROL 0x86000005 (arg 3 enable, 2 disable), STATUS 0x86000006, PING 0x86000007,
// SET_TIME 0x86000008 (bark ms, bite ms), max 32 s; a0 = 0 ok, -1 not supported.
// Included at the end of BootWatchdogPolicy.c; fuxi_hwdt_start() runs once from sheng_boot_watchdog_policy (thread context).
#include <kern/thread.h>
#include <kern/clock.h>
#include <machine/machine_routines.h>
#include "BootResetCore.h"
// The exported machine_routines.h this file is built against has no ml_io_map (run 43774594661: implicit declaration).
extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern kern_return_t kernel_thread_start_priority(thread_continue_t continuation, void *parameter, integer_t priority,
                                                  thread_t *new_thread);
enum {FuxiGhControl = 0x86000005, FuxiGhStatus = 0x86000006, FuxiGhPing = 0x86000007, FuxiGhSetTime = 0x86000008,
      FuxiGhEnable = 3, FuxiGhDisable = 2};
static unsigned fuxi_hwdt_test;
volatile uint32_t fuxi_hwdt_state[4];   // [0] stage/error, [1] pings, [2] SDAM before, [3] SDAM after
static unsigned fuxi_hwdt_bark = 1;   // claude 11-27: on by default (args are full); fuxi-hwdt-bark=0 turns it off
#include <kern/debug.h>
extern int armcpu_spi_attach(uint32_t, _Bool, void (*)(void *), void *, uint32_t *, uint64_t *) __attribute__((weak_import));
// Bark (claude + Gemini 11-27): XNU prints only the panic title here, so print the state first.
extern volatile uint32_t armcpu_core_timer[8] __attribute__((weak_import));
extern volatile uint32_t armcpu_core_sgi[8] __attribute__((weak_import));
extern int cpu_number(void) __attribute__((weak_import));
extern int proc_selfpid(void);
extern void proc_selfname(char *, int);
static void fuxi_hwdt_bark_irq(void *arg) {
  (void)arg;
  uint64_t mpidr = 0;
  __asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr));
  int cpu = (&cpu_number) ? cpu_number() : (int)((mpidr >> 8) & 0xffu);
  char pname[24] = {};
  proc_selfname(pname, sizeof(pname));
  int pid = proc_selfpid();
  uint64_t last_pc = 0;   // boot_progress_last_pc does not exist in this kernel (CI 45951203109 link error)
  printf("\n!!! FUXI HWDT BARK cpu=%d mpidr=%#llx pid=%d(%s) pings=%u bp_pc=%#llx !!!\n",
         cpu, (unsigned long long)mpidr, pid, pname, (unsigned)fuxi_hwdt_state[1], (unsigned long long)last_pc);
  if (&armcpu_core_timer && &armcpu_core_sgi) {
    printf("  timers: %u %u %u %u %u %u %u %u | sgi: %u %u %u %u %u %u %u %u\n",
           (unsigned)armcpu_core_timer[0], (unsigned)armcpu_core_timer[1],
           (unsigned)armcpu_core_timer[2], (unsigned)armcpu_core_timer[3],
           (unsigned)armcpu_core_timer[4], (unsigned)armcpu_core_timer[5],
           (unsigned)armcpu_core_timer[6], (unsigned)armcpu_core_timer[7],
           (unsigned)armcpu_core_sgi[0], (unsigned)armcpu_core_sgi[1],
           (unsigned)armcpu_core_sgi[2], (unsigned)armcpu_core_sgi[3],
           (unsigned)armcpu_core_sgi[4], (unsigned)armcpu_core_sgi[5],
           (unsigned)armcpu_core_sgi[6], (unsigned)armcpu_core_sgi[7]);
  }
  // Walk up to 16 kernel stack frames from the bark ISR through the interrupted exception frame.
  uint64_t fp = (uint64_t)(uintptr_t)__builtin_frame_address(0);
  printf("  bt:");
  for (unsigned i = 0; i < 16 && fp >= 0xffff000000000000ull && !(fp & 15u); ++i) {
    const uint64_t *frame = (const uint64_t *)(uintptr_t)fp;
    uint64_t next = frame[0];
    uint64_t lr = frame[1];
    printf(" %#llx", (unsigned long long)lr);
    if (next <= fp || next - fp > 0x10000ull) break;
    fp = next;
  }
  printf("\n");
  panic("fuxi hwdt bark: cpu=%d pid=%d(%s) pings=%u bp_pc=%#llx",
        cpu, pid, pname, (unsigned)fuxi_hwdt_state[1], (unsigned long long)last_pc);
}

// One SMCCC 1.1 call (x4..x17 preserved by the callee). Returns a0 as a signed 32-bit result.
static int32_t fuxi_gh_call(uint32_t fn, uint64_t a1, uint64_t a2) {
  register uint64_t x0 __asm__("x0") = fn;
  register uint64_t x1 __asm__("x1") = a1;
  register uint64_t x2 __asm__("x2") = a2;
  register uint64_t x3 __asm__("x3") = 0;
  // Clobbers as upstream matejkoo217/UniXNU-fuxi package/BootReset.c smc2(): x4..x17 are not trusted across the call.
  __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) : : "memory", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
                   "x12", "x13", "x14", "x15", "x16", "x17");
  return (int32_t)(uint32_t)x0;
}

static void fuxi_hwdt_thread(void *arg, wait_result_t wr) {
  (void)arg; (void)wr;
  for (unsigned n = 0;; ++n) {
    if (fuxi_hwdt_test && n >= fuxi_hwdt_test) {
      printf("fuxi hwdt: test, pings stopped after %u s\n", n);
      fuxi_hwdt_state[0] = 0x7e57;
      return;
    }
    (void)fuxi_gh_call(FuxiGhPing, 0, 0);
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
  if (secs > 32) secs = 32;   // Gunyah reserves values above 0x8000 ms
  (void)PE_parse_boot_argn("fuxi-hwdt-test", &fuxi_hwdt_test, sizeof(fuxi_hwdt_test));
  (void)PE_parse_boot_argn("fuxi-hwdt-bark", &fuxi_hwdt_bark, sizeof(fuxi_hwdt_bark));
  int32_t st = fuxi_gh_call(FuxiGhStatus, 0, 0);
  if (st != 0) {
    fuxi_hwdt_state[0] = 0xe0;
    printf("fuxi hwdt: Gunyah watchdog status %d, not armed\n", st);
    return;
  }
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
  const uint64_t ms = (uint64_t)secs * 1000;
  int32_t r1 = fuxi_gh_call(FuxiGhControl, FuxiGhDisable, 0);
  uint64_t bark_ms = ms;
  int bark_rc = -100;
  if (fuxi_hwdt_bark == 1 && secs >= 10 && armcpu_spi_attach) {
    bark_rc = armcpu_spi_attach(32, 0, fuxi_hwdt_bark_irq, NULL, NULL, NULL);
    if (bark_rc == 0) bark_ms = ms - 5000;
  }
  printf("fuxi hwdt: bark %llu ms bite %llu ms (attach rc %d)\n", (unsigned long long)bark_ms, (unsigned long long)ms, bark_rc);
  int32_t r2 = fuxi_gh_call(FuxiGhSetTime, bark_ms, ms);
  if (r2 != 0) {
    fuxi_hwdt_state[0] = 0xe4;
    printf("fuxi hwdt: SET_TIME %d (disable %d), not armed\n", r2, r1);
    return;
  }
  thread_t thread;
  // Highest kernel priority (MAXPRI_KERNEL 95), as upstream: a busy system must not starve the pings into a false bite.
  if (kernel_thread_start_priority(fuxi_hwdt_thread, NULL, 95, &thread) != KERN_SUCCESS) {
    fuxi_hwdt_state[0] = 0xe5;
    printf("fuxi hwdt: no ping thread, watchdog left off\n");
    return;
  }
  thread_deallocate(thread);
  int32_t r3 = fuxi_gh_call(FuxiGhControl, FuxiGhEnable, 0);
  (void)fuxi_gh_call(FuxiGhPing, 0, 0);
  fuxi_hwdt_state[0] = r3 == 0 ? 1 : 0xe6;
  printf("fuxi hwdt: Gunyah watchdog %s (enable %d), bite after %u s without pings (test %u)\n", r3 == 0 ? "armed" : "NOT armed", r3,
         secs, fuxi_hwdt_test);
}
