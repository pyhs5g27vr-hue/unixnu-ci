#!/usr/bin/env python3
"""Claude+Gemini 2026-11-28: fuxi-modem-irqfix.py ROOT... : Kerfand ceb99ca FuxiModemProbe.cpp allocates gOwner lazily
(ownerStorage -> IOMallocZero). Without fuxi-modem the modem thread never touches it, so the first AOP doorbell that AdspProbe's
ipccIrq forwards to fuxi_modem_ipcc_id() allocates inside the interrupt handler ->
'zalloc.c:6932 Calling {k,z}alloc from interrupt disabled context' (all3gpu 10:30, qos1 12:11; qos1 without sheng-adsp: no panic).
Fix: the pointer becomes file static and fuxi_modem_ipcc_id() returns while it is still NULL (nothing of ours is waiting then)."""
import pathlib, sys
OLD = ('Owner *ownerStorage()\n{\n    static Owner *owner;\n    if (!owner) owner = static_cast<Owner *>(IOMallocZero(sizeof(Owner)));\n'
       '    return owner;\n}\n')
NEW = ('Owner *gOwnerPtr;   // fuxi 11-28: file static, so the IPCC forwarder can check it without allocating\n'
       'Owner *ownerStorage()\n{\n    if (!gOwnerPtr) gOwnerPtr = static_cast<Owner *>(IOMallocZero(sizeof(Owner)));\n'
       '    return gOwnerPtr;\n}\n')
HEAD = 'extern "C" void fuxi_modem_ipcc_id(uint32_t id)\n{\n'
GUARD = ('    if (!gOwnerPtr) return;   // fuxi 11-28: interrupt context; no modem thread yet -> never allocate here (zalloc panic)\n')
n = 0
for root in sys.argv[1:]:
    for p in pathlib.Path(root).rglob('FuxiModemProbe.cpp'):
        s = p.read_text()
        assert s.count(OLD) == 1 and s.count(HEAD) == 1, f'{p}: ceb99ca shape not found'
        s = s.replace(OLD, NEW, 1).replace(HEAD, HEAD + GUARD, 1)
        p.write_text(s); n += 1
        print('modem irqfix:', p)
assert n >= 1, 'no FuxiModemProbe.cpp patched'
