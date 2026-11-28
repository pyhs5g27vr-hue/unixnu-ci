#!/usr/bin/env python3
"""Gemini 2026-11-28: fuxi-bb-post-online.py ROOT... : after bb_lpm_answer() puts the modem into low power
following SAHARA completion (needed so CommCenter sees Shutdown -> Offline), arm a one-shot timer (+12 s)
that sends NAS Set System Selection Preference (0x33: GSM/UMTS/LTE/NR, roaming any, CS+PS, until power cycle)
+ DMS Set Operating Mode ONLINE (0x2e: mode=0), then 3 s later reads back DMS mode + NAS system selection
and restarts serving-system polls. Defaults ON (0 boot-args bytes); fuxi-bb-post-online=0 disables it.
Runs after port-ceb-baseband.py. Usage: fuxi-bb-post-online.py ROOT..."""
import pathlib
import sys

LPM_ANCHOR = 'static int bb_lpm_answer(uint32_t dst_port, const uint8_t *sdu, uint32_t n)\n'
LPM_FWD = 'static void bb_post_online_arm(void);\n'

LPM_DONE_OLD = '    printf("COACHZ baseband: operating mode set to low power: error 0x%x\\n", error);\n    bb_lpm_pending = 0;\n'
LPM_DONE_NEW = '    printf("COACHZ baseband: operating mode set to low power: error 0x%x\\n", error);\n    bb_lpm_pending = 0;\n    bb_post_online_arm();\n'

RADIO_ANCHOR = '// The three requests, in the order they are worth asking in.\nstatic void bb_radio_step(void)\n'
POST_ONLINE_FN = r'''// gemini 2026-11-28: 12 s after SAHARA's post-boot low-power handshake finishes, send NAS 0x33 (roaming any)
// + DMS Set Operating Mode ONLINE (0x2e = 0) so the radio registers even if CommCenter never sends DMS ONLINE.
// Defaults ON (0 extra boot-args); fuxi-bb-post-online=0 disables.
static uint8_t bb_post_online_state;
static uint32_t bb_post_online_at, bb_post_online_txn = 0x4f00u;
static void bb_post_online_arm(void)
{
  if (bb_post_online_state != 0u) return;
  uint32_t on = 1;
  if (PE_parse_boot_argn("fuxi-bb-post-online", &on, sizeof on) && on == 0) {
    bb_post_online_state = 3u;
    printf("COACHZ post-online: off (fuxi-bb-post-online=0)\n");
    return;
  }
  bb_post_online_at = bb_now_ms() + 12000u;
  bb_post_online_state = 1u;
  printf("COACHZ post-online: armed for +12 s (at %u ms)\n", bb_post_online_at);
}
static void bb_post_online_step(void)
{
  if (bb_post_online_state == 0u || bb_post_online_state >= 3u) return;
  const uint32_t now = bb_now_ms();
  if (now < bb_post_online_at) return;
  const struct cbq_server *server = cbq_server_find(&bb_qmux, BB_DMS);
  if (!server) return;
  if (bb_dms_slot < 0) bb_dms_slot = cbq_client_alloc(&bb_qmux, CBQ_INTERNAL, BB_DMS);
  if (bb_dms_slot < 0) return;
  uint8_t sdu[16];
  uint32_t n;
  if (bb_post_online_state == 1u) {
    const struct cbq_server *nas = cbq_server_find(&bb_qmux, CBN_SVC_NAS);
    if (nas && bb_reg_slot >= 0) {
      uint8_t sel[48];
      uint32_t off = 0;
      const uint8_t mode[2] = {0x5c, 0x00}, roam[2] = {0xff, 0x00}, dom[4] = {0x02, 0, 0, 0}, dur = 0;
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x11, mode, 2);
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x14, roam, 2);
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x17, &dur, 1);
      off += cbd_tlv(sel + 7 + off, sizeof sel - 7u - off, 0x18, dom, 4);
      const uint32_t m = cbd_request(sel, ++bb_reg_txn, 0x0033u, off);
      bb_queue_tx(CBQ_PORT_BASE + (uint32_t)bb_reg_slot, nas->node, nas->port, sel, m);
      printf("COACHZ post-online: NAS set system selection (mode 0x5c, roaming any, CS+PS), txn 0x%x\n", bb_reg_txn);
    }
    const uint8_t online = 0;
    n = cbd_request(sdu, ++bb_post_online_txn, BB_DMS_SET_MODE, cbd_tlv(sdu + 7, sizeof sdu - 7u, 0x01, &online, 1));
    printf("COACHZ post-online: DMS set operating mode ONLINE, txn 0x%x, t %u\n", bb_post_online_txn, now);
    bb_post_online_at = now + 3000u;
    bb_post_online_state = 2u;
  } else {
    n = cbd_request(sdu, ++bb_post_online_txn, BB_DMS_GET_MODE, 0);
    printf("COACHZ post-online: DMS get operating mode, txn 0x%x, t %u\n", bb_post_online_txn, now);
    const struct cbq_server *nas = cbq_server_find(&bb_qmux, CBN_SVC_NAS);
    if (nas && bb_reg_slot >= 0) {
      uint8_t sel[32];
      const uint32_t m = cbn_build_request(sel, sizeof sel, ++bb_reg_txn, CBN_NAS_GET_SYSTEM_SELECTION);
      if (m) bb_queue_tx(CBQ_PORT_BASE + (uint32_t)bb_reg_slot, nas->node, nas->port, sel, m);
    }
    bb_reg_tries = 0;
    bb_post_online_state = 3u;
  }
  bb_queue_tx(CBQ_PORT_BASE + (uint32_t)bb_dms_slot, server->node, server->port, sdu, n);
}

'''

LOOP_ANCHOR = '  bb_online_step();   // claude 2026-11-27\n'
LOOP_ADD = '  bb_post_online_step();   // gemini 2026-11-28\n'

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('coachz_baseband.cpp')):
        s = p.read_text()
        if 'bb_post_online_step' in s:
            print('bb-post-online: already', p)
            n += 1
            continue
        for name, anc in [('LPM_ANCHOR', LPM_ANCHOR), ('LPM_DONE_OLD', LPM_DONE_OLD),
                          ('RADIO_ANCHOR', RADIO_ANCHOR), ('LOOP_ANCHOR', LOOP_ANCHOR)]:
            assert s.count(anc) == 1, f'{p}: {name} count={s.count(anc)}'
        s = s.replace(LPM_ANCHOR, LPM_FWD + LPM_ANCHOR, 1)
        s = s.replace(LPM_DONE_OLD, LPM_DONE_NEW, 1)
        s = s.replace(RADIO_ANCHOR, POST_ONLINE_FN + RADIO_ANCHOR, 1)
        s = s.replace(LOOP_ANCHOR, LOOP_ANCHOR + LOOP_ADD, 1)
        p.write_text(s)
        n += 1
        print('bb-post-online:', p)
assert n >= 1, 'no coachz_baseband.cpp patched'
