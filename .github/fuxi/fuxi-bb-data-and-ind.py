#!/usr/bin/env python3
"""Gemini 2026-11-28 (bb12): fuxi-bb-data-and-ind.py ROOT...
Two targeted fixes for live 4G LTE (DOCOMO 440-10) on SM8550:
1. coachz_bb_qmux.h: bump CBQ_MAX_CLIENTS 64u -> 128u (+640 B total in __DATA).
   Fixes 'COACHZ baseband: data port: no client for service 26' (WDA Set Data Format)
   and CommCenter CBQ_ERR_CLIENT_IDS_EXHAUSTED (err 0x5) after CommCenter allocates 64 QMI clients.
2. coachz_baseband.cpp: handle unsolicited type=4 (INDICATION) NAS 0x24 (Serving System)
   and NAS 0x51 (Signal Info) on bb_reg_slot and bb_serving_slot, updating bb_radio
   (reg_state/cs/ps/mcc/mnc/rsrp), logging bb_radio_log(), and forwarding to host NAS clients
   via bb_nas_indicate().
Idempotent. Runs after port-ceb-baseband.py. Usage: fuxi-bb-data-and-ind.py ROOT..."""
import pathlib
import sys

QMUX_OLD = '#define CBQ_MAX_CLIENTS 64u'
QMUX_NEW = '#define CBQ_MAX_CLIENTS 128u  /* gemini bb12: 64 exhausted by CommCenter before WDA data-port client alloc */'

REG_OLD = '''        } else {
          printf("COACHZ register: answer message 0x%x: error %u, %u TLVs\\n", m, bb_reg.error, bb_reg.tlv_count);
        }
      }
    } else if (bb_serving_slot >= 0 && dst_port == CBQ_PORT_BASE + (uint32_t)bb_serving_slot &&'''

REG_NEW = '''        } else {
          printf("COACHZ register: answer message 0x%x: error %u, %u TLVs\\n", m, bb_reg.error, bb_reg.tlv_count);
        }
      } else if (size >= 7u && sdu[0] == 0x04u) {
        const uint32_t m = (uint32_t)(sdu[3] | sdu[4] << 8);
        if (m == CBN_NAS_GET_SERVING_SYSTEM && cbn_take_serving_system(&bb_radio, sdu, size)) {
          bb_radio_log();
          bb_nas_indicate(0x24u, sdu, size);
        } else if (m == CBN_NAS_GET_SIGNAL_INFO && cbn_take_signal(&bb_radio, sdu, size)) {
          bb_radio_log();
          bb_nas_indicate(0x51u, sdu, size);
        }
      }
    } else if (bb_serving_slot >= 0 && dst_port == CBQ_PORT_BASE + (uint32_t)bb_serving_slot &&'''

SRV_OLD = '''      if (read) {
        bb_serving.answered = 1;
        cbn_take_serving_system(&bb_radio, sdu, size);
        printf("COACHZ baseband: the serving system answer: error %u, %u TLVs\\n", bb_serving.error, bb_serving.tlv_count);
        bb_radio_log();
      }
    } else if (bb_signal_slot >= 0 && dst_port == CBQ_PORT_BASE + (uint32_t)bb_signal_slot &&'''

SRV_NEW = '''      if (read) {
        bb_serving.answered = 1;
        cbn_take_serving_system(&bb_radio, sdu, size);
        printf("COACHZ baseband: the serving system answer: error %u, %u TLVs\\n", bb_serving.error, bb_serving.tlv_count);
        bb_radio_log();
      } else if (size >= 7u && sdu[0] == 0x04u && (uint32_t)(sdu[3] | sdu[4] << 8) == CBN_NAS_GET_SERVING_SYSTEM) {
        if (cbn_take_serving_system(&bb_radio, sdu, size)) {
          bb_radio_log();
          bb_nas_indicate(0x24u, sdu, size);
        }
      }
    } else if (bb_signal_slot >= 0 && dst_port == CBQ_PORT_BASE + (uint32_t)bb_signal_slot &&'''

n_qmux = n_bb = 0
for root in sys.argv[1:]:
    r = pathlib.Path(root)
    for p in sorted(r.rglob('coachz_bb_qmux.h')):
        s = p.read_text()
        if 'CBQ_MAX_CLIENTS 128u' in s:
            print('bb-data-and-ind: qmux already', p)
            n_qmux += 1
            continue
        assert s.count(QMUX_OLD) == 1, f'{p}: QMUX_OLD count={s.count(QMUX_OLD)}'
        p.write_text(s.replace(QMUX_OLD, QMUX_NEW, 1))
        print('bb-data-and-ind: qmux patched', p)
        n_qmux += 1

    for p in sorted(r.rglob('coachz_baseband.cpp')):
        s = p.read_text()
        if 'sdu[0] == 0x04u' in s and 'cbn_take_serving_system(&bb_radio, sdu, size))' in s:
            print('bb-data-and-ind: bb already', p)
            n_bb += 1
            continue
        assert s.count(REG_OLD) == 1, f'{p}: REG_OLD count={s.count(REG_OLD)}'
        assert s.count(SRV_OLD) == 1, f'{p}: SRV_OLD count={s.count(SRV_OLD)}'
        s = s.replace(REG_OLD, REG_NEW, 1).replace(SRV_OLD, SRV_NEW, 1)
        p.write_text(s)
        print('bb-data-and-ind: bb patched', p)
        n_bb += 1

assert n_qmux >= 1, 'no coachz_bb_qmux.h patched'
assert n_bb >= 1, 'no coachz_baseband.cpp patched'
