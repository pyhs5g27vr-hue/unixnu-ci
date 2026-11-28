#!/usr/bin/env python3
"""Gemini 2026-11-28 (bb9): fuxi-modem-quiet.py ROOT... : quiet the 1 Hz ~65-line/sec baseband UART printf storm
in coachz_baseband.cpp, FuxiModemProbe.cpp, and fuxi_modem.c so baseband coexists with 75 fps UI without >100 ms
console-lock frame spikes.
- Default ON (0 extra boot-args bytes); boot-arg fuxi-modem-quiet=0 restores full 1 Hz verbose reports.
- In quiet mode:
  * 'the modem offers service' (49 lines) prints ONLY when the service count changes (once after modem bring-up).
  * COACHZ summary + radio + PDP + channel opens print on second<=5, every 30 s, OR whenever servers/clients/
    sahara.state/activations/operating_mode/reg_state/have_plmn changes.
  * FUXI_MODEM and FUXI modem 1 Hz counters print on second<=5 or every 30 s (fuxi_rmtfs_flush, smp2p_dumped,
    crash_reason_read, syncStats still run every 1 s).
  * All event-driven logs (SAHARA, UIM, post-online, QMI errors, FUXI_STAGE) remain untouched.
Usage: fuxi-modem-quiet.py ROOT..."""
import pathlib
import sys

# 1. coachz_baseband.cpp
BB_ANCHOR = 'extern "C" void coachz_baseband_report(unsigned second)\n{\n  if (!bb_lock || !bb_published) return;\n  bb_pdp_report(second);\n  IOLockLock(bb_lock);\n  uint32_t clients = 0, servers = 0;\n  for (uint32_t i = 0; i < CBQ_MAX_CLIENTS; i++) clients += bb_qmux.client[i].used;\n  for (uint32_t i = 0; i < CBQ_MAX_SERVERS; i++) servers += bb_qmux.server[i].present;\n'
BB_NEW = '''extern "C" int fuxi_modem_is_quiet(void)
{
  static int checked = 0, quiet = 1;
  if (!checked) {
    uint32_t v = 1;
    if (PE_parse_boot_argn("fuxi-modem-quiet", &v, sizeof v)) quiet = (v != 0);
    checked = 1;
  }
  return quiet;
}

extern "C" void coachz_baseband_report(unsigned second)
{
  if (!bb_lock || !bb_published) return;
  const int quiet = fuxi_modem_is_quiet();
  IOLockLock(bb_lock);
  uint32_t clients = 0, servers = 0;
  for (uint32_t i = 0; i < CBQ_MAX_CLIENTS; i++) clients += bb_qmux.client[i].used;
  for (uint32_t i = 0; i < CBQ_MAX_SERVERS; i++) servers += bb_qmux.server[i].present;
  static uint32_t q_servers = ~0u, q_clients = ~0u, q_sahara = ~0u, q_act = ~0u;
  static uint8_t q_op = 0xff, q_reg = 0xff, q_plmn = 0xff;
  const bool srv_changed = (servers != q_servers);
  const bool changed = srv_changed || clients != q_clients || bb_sahara.state != q_sahara ||
                       bb_activations != q_act || bb_radio.operating_mode != q_op ||
                       bb_radio.reg_state != q_reg || (uint8_t)bb_radio.have_plmn != q_plmn;
  if (quiet && !changed && second > 5u && (second % 30u != 0u)) {
    IOLockUnlock(bb_lock);
    return;
  }
  q_servers = servers; q_clients = clients; q_sahara = bb_sahara.state; q_act = bb_activations;
  q_op = bb_radio.operating_mode; q_reg = bb_radio.reg_state; q_plmn = (uint8_t)bb_radio.have_plmn;
  IOLockUnlock(bb_lock);
  if (!quiet || second <= 5u || (second % 30u == 0u)) bb_pdp_report(second);
  IOLockLock(bb_lock);
'''

SRV_LOOP_OLD = '''  for (uint32_t i = 0; i < CBQ_MAX_SERVERS; i++) {
    const struct cbq_server *s = &bb_qmux.server[i];
    if (!s->present) continue;
    printf("COACHZ baseband: %u s: the modem offers service 0x%02x, version %u, instance %u, at node %u port %u\\n",
           second, s->service, s->version, s->instance, s->node, s->port);
  }'''
SRV_LOOP_NEW = '''  if (!quiet || srv_changed) {
  for (uint32_t i = 0; i < CBQ_MAX_SERVERS; i++) {
    const struct cbq_server *s = &bb_qmux.server[i];
    if (!s->present) continue;
    printf("COACHZ baseband: %u s: the modem offers service 0x%02x, version %u, instance %u, at node %u port %u\\n",
           second, s->service, s->version, s->instance, s->node, s->port);
  }
  }'''

# 2. FuxiModemProbe.cpp
MP_DECL = 'extern "C" void fuxi_modem_report(unsigned second);\n'
MP_DECL_NEW = MP_DECL + 'extern "C" int fuxi_modem_is_quiet(void);\n'
MP_START = '''            second++;
            /* The heartbeat goes out every second whether or not anything moved, so a silent link and a
             * dead thread do not look the same. The counters below say where the traffic stops. */'''
MP_START_NEW = '''            second++;
            if (!fuxi_modem_is_quiet() || second <= 5u || (second % 30u == 0u)) {
            /* The heartbeat goes out every second whether or not anything moved, so a silent link and a
             * dead thread do not look the same. The counters below say where the traffic stops. */'''

MP_END = '''            /* The bridge's own report: the QMI services the modem announced, the clients and the queue state. It is
             * the only place that names the service ids, and the service ids are how a client finds the service it
             * wants. Without this call the bridge stays silent and the announced services are never on the record. */
            fuxi_modem_report(second);'''
MP_END_NEW = '''            }
            /* The bridge's own report: the QMI services the modem announced, the clients and the queue state. It is
             * the only place that names the service ids, and the service ids are how a client finds the service it
             * wants. Without this call the bridge stays silent and the announced services are never on the record. */
            fuxi_modem_report(second);'''

MP_FATAL_OLD = '''            if (!gOwner.crash_reason_read && second > 20 && status.glink_rx_messages == gOwner.last_glink_rx &&
                status.glink_rx_data > 0) {
                gOwner.crash_reason_read = true;
                readCrashReason();
            }'''
MP_FATAL_NEW = MP_FATAL_OLD + '''
            static bool fatal_reason_read;
            if (gOwner.fatal && !fatal_reason_read) {
                fatal_reason_read = true;
                printf("FUXI_MODEM: %u s: fatal=1 detected, reading SMEM crash reason\\n", second);
                readCrashReason();
            }'''

# 3. fuxi_modem.c
FM_ANCHOR = '''    {
        extern void fuxi_rmtfs_flush(void);
        fuxi_rmtfs_flush();
    }
    printf("FUXI modem: %u s: link %s, QRTR tx %u rx %u again %u, servers %u, glink tx %u rx %u, "'''
FM_NEW = '''    {
        extern void fuxi_rmtfs_flush(void);
        extern int fuxi_modem_is_quiet(void);
        fuxi_rmtfs_flush();
        if (fuxi_modem_is_quiet() && second > 5u && (second % 30u != 0u)) return;
    }
    printf("FUXI modem: %u s: link %s, QRTR tx %u rx %u again %u, servers %u, glink tx %u rx %u, "'''

n_bb = n_mp = n_fm = 0
for root in sys.argv[1:]:
    r = pathlib.Path(root)
    for p in sorted(r.rglob('coachz_baseband.cpp')):
        s = p.read_text()
        if 'fuxi_modem_is_quiet' in s:
            print('modem-quiet: already', p); n_bb += 1; continue
        assert s.count(BB_ANCHOR) == 1, f'{p}: BB_ANCHOR={s.count(BB_ANCHOR)}'
        assert s.count(SRV_LOOP_OLD) == 1, f'{p}: SRV_LOOP_OLD={s.count(SRV_LOOP_OLD)}'
        s = s.replace(BB_ANCHOR, BB_NEW, 1).replace(SRV_LOOP_OLD, SRV_LOOP_NEW, 1)
        p.write_text(s); n_bb += 1; print('modem-quiet:', p)
    for p in sorted(r.rglob('FuxiModemProbe.cpp')):
        s = p.read_text()
        if 'fuxi_modem_is_quiet' in s:
            print('modem-quiet: already', p); n_mp += 1; continue
        assert s.count(MP_DECL) == 1, f'{p}: MP_DECL={s.count(MP_DECL)}'
        assert s.count(MP_START) == 1, f'{p}: MP_START={s.count(MP_START)}'
        assert s.count(MP_END) == 1, f'{p}: MP_END={s.count(MP_END)}'
        assert s.count(MP_FATAL_OLD) == 1, f'{p}: MP_FATAL_OLD={s.count(MP_FATAL_OLD)}'
        s = s.replace(MP_DECL, MP_DECL_NEW, 1).replace(MP_START, MP_START_NEW, 1).replace(MP_END, MP_END_NEW, 1).replace(MP_FATAL_OLD, MP_FATAL_NEW, 1)
        p.write_text(s); n_mp += 1; print('modem-quiet:', p)
    for p in sorted(r.rglob('fuxi_modem.c')):
        s = p.read_text()
        if 'fuxi_modem_is_quiet' in s:
            print('modem-quiet: already', p); n_fm += 1; continue
        assert s.count(FM_ANCHOR) == 1, f'{p}: FM_ANCHOR={s.count(FM_ANCHOR)}'
        s = s.replace(FM_ANCHOR, FM_NEW, 1)
        p.write_text(s); n_fm += 1; print('modem-quiet:', p)

assert n_bb >= 1 and n_mp >= 1 and n_fm >= 1, f'counts: bb={n_bb} mp={n_mp} fm={n_fm}'
