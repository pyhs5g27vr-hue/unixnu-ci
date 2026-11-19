#!/usr/bin/env python3
"""fuxi 2026-11-20: GPU direct scanout for fuxi (port of UniXNU/ShengUfs f2d6a4a + 99d8bcd, sheng SM8550 = same SoC as fuxi).

1. NativeUfs.cpp: the display bank (stream 0x1c00) gets a stage 1 window on sheng-dpu-scanout=1+, native_ufs_dpu_map fills its slots,
   native_ufs_dpu_state bit 31 says the window is live (NativeLegacyDisplay::start checks it). TCR2 SEP=7 so IOVAs with bit 31 translate.
2. Ios17LegacyDisplayProbe.cpp: drop the strong stubs (native_ufs_dpu_map returning 0, native_ufs_dpu_state) that kept direct scanout off;
   both live in NativeUfs now (one kernel link, so keeping them would be a duplicate symbol).
Usage: dpu-scanout-port.py DIR...   (searches every NativeUfs.cpp and Ios17LegacyDisplayProbe.cpp under the DIRs)"""
import pathlib, re, sys

HELPERS = r'''
// fuxi: display bank stage 1 window (port of ShengUfs f2d6a4a + 99d8bcd).
extern "C" volatile uint32_t native_ufs_dpu_smmu[24];
extern "C" volatile uint32_t native_ufs_dpu_state;
extern "C" volatile uint32_t native_ufs_dpu_check[8];
constexpr uint32_t kDpuWindow = 0x10000000U, kDpuSlots = 4, kDpuSlotBytes = 32U << 20, kDpuSlotTables = kDpuSlotBytes >> 21;
static uint64_t *gDpuTables;
static uintptr_t gDpuCb;
static IOLock *gDpuLock;
static uintptr_t gDpuLiveCb;
constexpr uint32_t kDpuFaults = 0xc00001feU;
static void dpuClean (const void *start, size_t length)
{
  for (size_t off = 0; off < length; off += 64)
    __asm__ volatile ("dc civac, %0" :: "r" (static_cast<const uint8_t *> (start) + off) : "memory");
  __asm__ volatile ("dsb sy" ::: "memory");
}
static bool dpuTlbFlush (uintptr_t cb)
{
  write32 (cb, 0x618, 0); write32 (cb, 0x7f0, 0);
  __asm__ volatile ("dsb sy" ::: "memory");
  for (unsigned spin = 0; spin < 100000; ++spin) if (!(read32 (cb, 0x7f4) & 1)) return true;
  return false;
}
static void dpuEnable (uintptr_t cb, uint32_t bank, uint32_t oldSctlr)
{
  const size_t bytes = (2 + kDpuSlots * kDpuSlotTables) * 4096;
  IOBufferMemoryDescriptor *tables = IOBufferMemoryDescriptor::inTaskWithOptions (
    kernel_task, static_cast<IOOptionBits> (kIODirectionInOut) | static_cast<IOOptionBits> (kIOMemoryPhysicallyContiguous) |
    static_cast<IOOptionBits> (kIOMemoryMapperNone), bytes, 4096);
  gDpuLock = IOLockAlloc ();
  if (!tables || !gDpuLock) {native_ufs_dpu_state = 0xdead0002U; return;}
  uint64_t *l1 = static_cast<uint64_t *> (tables->getBytesNoCopy ());
  const uint64_t pa = tables->getPhysicalSegment (0, nullptr, kIOMemoryMapperNone);
  bzero (l1, bytes);
  const uint64_t attrs = (1ULL << 10) | (1ULL << 6);
  l1[0] = pa | 3;
  l1[2] = 0x80000000ULL | attrs | 1;
  l1[3] = 0xc0000000ULL | attrs | 1;
  for (uint32_t t = 0; t < kDpuSlots * kDpuSlotTables; ++t) l1[(kDpuWindow >> 21) + t] = (pa + (2 + t) * 4096ULL) | 3;
  dpuClean (l1, bytes);
  const uint32_t old[5] = {read32 (cb, 0x20), read32 (cb, 0x24), read32 (cb, 0x10), read32 (cb, 0x30), read32 (cb, 0x38)};
  gDpuLiveCb = cb;
  write32 (cb, 0x20, static_cast<uint32_t> (pa)); write32 (cb, 0x24, static_cast<uint32_t> (pa >> 32));
  write32 (cb, 0x10, 5U | (7U << 15));                // TCR2: 48-bit output, SEP 7 (99d8bcd)
  write32 (cb, 0x30, 32U | (1U << 23));               // T0SZ 32, non-cacheable walks, 4 KiB granule, no TTBR1
  write32 (cb, 0x38, 0x44);                           // MAIR attribute 0: normal non-cacheable
  __asm__ volatile ("dsb sy" ::: "memory");
  volatile uint32_t *c = native_ufs_dpu_check;
  c[0] = read32 (cb, 0x20); c[1] = read32 (cb, 0x30); c[2] = read32 (cb, 0x58);
  const auto undo = [&] (uint32_t why) {
    write32 (cb, 0x0, oldSctlr);
    __asm__ volatile ("dsb sy; isb" ::: "memory");
    write32 (cb, 0x20, old[0]); write32 (cb, 0x24, old[1]); write32 (cb, 0x10, old[2]); write32 (cb, 0x30, old[3]); write32 (cb, 0x38, old[4]);
    const uint32_t fsr = read32 (cb, 0x58);
    if (fsr & (1U << 30)) write32 (cb, 0x8, 1);
    if (fsr & kDpuFaults) write32 (cb, 0x58, fsr);
    dpuTlbFlush (cb);
    native_ufs_dpu_state = why;
  };
  if (c[0] != static_cast<uint32_t> (pa) || c[1] != (32U | (1U << 23))) {undo (0xdead0003U); return;}
  if (!dpuTlbFlush (cb)) {undo (0xdead0004U); return;}
  write32 (cb, 0x0, 1U | (1U << 5) | (1U << 6));      // SCTLR: M, CFRE, CFIE
  __asm__ volatile ("dsb sy; isb" ::: "memory");
  uint32_t fsr = 0, us = 0;
  for (; us < 50000; us += 500) {
    fsr = read32 (cb, 0x58);
    if (fsr & kDpuFaults) break;
    IODelay (500);
  }
  c[3] = fsr; c[7] = us;
  if (fsr & kDpuFaults) {
    c[4] = read32 (cb, 0x60); c[5] = read32 (cb, 0x64); c[6] = read32 (cb, 0x68);
    undo (0xdead0005U); return;
  }
  gDpuTables = l1; gDpuCb = cb;
  native_ufs_dpu_state = 0x80000000U | bank;
}
'''

PROBE = r'''
  // fuxi: the display streams (0x1c00, 0x1c02) and, with sheng-dpu-scanout, the display bank's stage 1 window (ShengUfs f2d6a4a).
  {
    uint32_t dpu = 0, scanout = 0;
    PE_parse_boot_argn ("sheng-dpu", &dpu, sizeof (dpu));
    PE_parse_boot_argn ("sheng-dpu-scanout", &scanout, sizeof (scanout));
    if (dpu >= 2 || scanout) {
      const uintptr_t s = gHost.smmu;
      const uint32_t idr0 = read32 (s, 0x20), idr1d = read32 (s, 0x24);
      const unsigned groups = (idr0 & 255) > 128 ? 128 : (idr0 & 255), banks = idr1d & 255;
      const unsigned pages = 1U << (((idr1d >> 28) & 7) + 1);
      native_ufs_dpu_smmu[1] = read32 (s, 0x0); native_ufs_dpu_smmu[2] = idr0; native_ufs_dpu_smmu[3] = idr1d;
      unsigned valid = 0;
      for (unsigned k = 0; k < 2; ++k) native_ufs_dpu_smmu[4 + 9 * k] = 0xffffffffU;
      for (unsigned i = 0; i < groups; ++i) {
        const uint32_t smr = read32 (s, 0x800 + 4 * i);
        if (!(smr & 0x80000000U)) continue;
        ++valid;
        const uint32_t mask = (smr >> 16) & 0x7fff;
        for (unsigned k = 0; k < 2; ++k) {
          volatile uint32_t *r = &native_ufs_dpu_smmu[4 + 9 * k];
          if (r[0] != 0xffffffffU || ((smr ^ (0x1c00U + 2 * k)) & 0x7fff & ~mask)) continue;
          const uint32_t s2cr = read32 (s, 0xc00 + 4 * i), bank = s2cr & 255;
          r[0] = i | (bank << 16); r[1] = smr; r[2] = s2cr;
          if (((s2cr >> 16) & 3) == 0 && bank < banks && (pages + banks) * 4096 <= 0xd0000) {
            const uintptr_t cb = s + (pages + bank) * 4096;
            r[3] = read32 (s, 0x1000 + 4 * bank); r[4] = read32 (s, 0x1800 + 4 * bank);
            r[5] = read32 (cb, 0x0); r[6] = read32 (cb, 0x20); r[7] = read32 (cb, 0x24); r[8] = read32 (cb, 0x30);
            native_ufs_dpu_smmu[22 + k] = read32 (cb, 0x58);
          }
        }
      }
      native_ufs_dpu_smmu[0] = 0x80000000U | groups | (valid << 8) | (banks << 16);
      const uint32_t found = native_ufs_dpu_smmu[4], bank = found >> 16;
      if (scanout && found != 0xffffffffU && bank < banks && ((native_ufs_dpu_smmu[6] >> 16) & 3) == 0 && !(native_ufs_dpu_smmu[9] & 1) &&
          ((native_ufs_dpu_smmu[7] >> 16) & 3) == 1) {
        dpuEnable (s + (pages + bank) * 4096, bank, native_ufs_dpu_smmu[9]);
      } else if (scanout) {
        native_ufs_dpu_state = 0xdead0001U;
      }
      printf ("fuxi dpu: smmu %#x stream %#x s2cr %#x cbar %#x sctlr %#x state %#x check fsr %#x far %#x:%#x us %u\n",
        native_ufs_dpu_smmu[0], native_ufs_dpu_smmu[4], native_ufs_dpu_smmu[6], native_ufs_dpu_smmu[7], native_ufs_dpu_smmu[9],
        native_ufs_dpu_state, native_ufs_dpu_check[3], native_ufs_dpu_check[5], native_ufs_dpu_check[4], native_ufs_dpu_check[7]);
    }
  }
'''

DEFS = r'''
// fuxi: display bank state (ShengUfs f2d6a4a). [0] bit 31 read | groups | valid << 8 | banks << 16; [1] sCR0 [2] IDR0 [3] IDR1;
// 0x1c00 at [4], 0x1c02 at [13]: group | bank << 16, SMR, S2CR, CBAR, CBA2R, SCTLR, TTBR0 lo/hi, TCR; [22],[23] FSR.
extern "C" volatile uint32_t native_ufs_dpu_smmu[24] = {};
// bit 31 + bank: window live; 0xdead000n: refused at step n (1 bank not as expected, 2 no memory, 3 registers ignored, 4 TLB sync, 5 fault).
extern "C" volatile uint32_t native_ufs_dpu_state = 0;
extern "C" volatile uint32_t native_ufs_dpu_check[8] = {};
extern "C" uint32_t native_ufs_dpu_live (unsigned reg)
{
  return gDpuLiveCb ? read32 (gDpuLiveCb, reg ? 0x58 : 0x0) : 0xffffffffU;
}
extern "C" uint32_t native_ufs_dpu_map (unsigned slot, const uint64_t *pages, unsigned count)
{
  if (!gDpuTables || slot >= kDpuSlots || count > kDpuSlotBytes / 4096) return 0;
  uint64_t *l3 = gDpuTables + 1024 + static_cast<size_t> (slot) * kDpuSlotTables * 512;
  const uint64_t attrs = (1ULL << 10) | (1ULL << 6);
  for (unsigned i = 0; i < kDpuSlotTables * 512; ++i) {
    if (i < count && (pages[i] & 0xfff)) return 0;
    l3[i] = i < count ? (pages[i] | attrs | 3) : 0;
  }
  dpuClean (l3, kDpuSlotTables * 4096);
  IOLockLock (gDpuLock);
  const bool synced = dpuTlbFlush (gDpuCb);
  IOLockUnlock (gDpuLock);
  return synced ? kDpuWindow + slot * kDpuSlotBytes : 0;
}
'''

def port_ufs(p):
    t = p.read_text()
    if 'native_ufs_dpu_map' in t:
        print(p, ': already has native_ufs_dpu_map'); return True
    a = t.find('static bool hostBringUp (')
    b = t.find('gHost.smmu = gHost.smmuMap->getVirtualAddress ();')
    if a < 0 or b < 0 or b < a:
        print(p, ': anchors missing (hostBringUp', a, 'smmu', b, ')', file=sys.stderr); return False
    b = t.index('\n', b) + 1
    t = t[:a] + HELPERS.lstrip('\n') + '\n' + t[a:b] + PROBE.lstrip('\n') + t[b:] + DEFS
    p.write_text(t); print(p, ': display bank window ported'); return True

def drop_stubs(p):
    t = p.read_text(); n0 = len(t)
    t = re.sub(r'(?m)^[ \t]*uint32_t native_ufs_dpu_map\(unsigned, const uint64_t \*, unsigned\) \{ return 0; \}\n', '', t)
    t = re.sub(r'(?m)^[ \t]*volatile uint32_t native_ufs_dpu_state;\n', '', t)
    if len(t) != n0: p.write_text(t); print(p, ': dpu stubs dropped')
    else: print(p, ': no dpu stubs')

ok = True; ufs = 0
for d in sys.argv[1:]:
    for p in pathlib.Path(d).rglob('NativeUfs.cpp'):
        ufs += 1; ok &= port_ufs(p)
    for p in pathlib.Path(d).rglob('Ios17LegacyDisplayProbe.cpp'):
        drop_stubs(p)
if not ufs: print('no NativeUfs.cpp found', file=sys.stderr); ok = False
sys.exit(0 if ok else 1)
