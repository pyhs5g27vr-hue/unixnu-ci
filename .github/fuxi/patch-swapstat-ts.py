#!/usr/bin/env python3
"""patch-swapstat-ts.py — 给内核注入的 `gpu swapstat` 行加时间戳，用于精确统计帧间隔。

注入点在 build-ios17-legacy-display.py 里（我们自己加的 swapstat 打印）。改动：
  printf("gpu swapstat ok %u ...
→ printf("%llu " "gpu swapstat ok %u ...
并在参数表最前面加 (unsigned long long)mach_absolute_time()。

这样每行带绝对时间，离线即可算出每帧间隔与分位数——比在核里做直方图更灵活，且改动极小。
"""
import pathlib
import sys

OLD_FMT = ("         '            printf(\"gpu swapstat ok %u kick %u xfer %u notready %u unvalidated %u direct %u"
           " fence %u present %u blank %u flip %u latch %u done %u slow %u max %u total %u depth %u\\\\n\",\\n'\n")
NEW_FMT = ("         '            printf(\"%llu \" \"gpu swapstat ok %u kick %u xfer %u notready %u unvalidated %u direct %u"
           " fence %u present %u blank %u flip %u latch %u done %u slow %u max %u total %u depth %u\\\\n\",\\n'\n"
           "         '                   (unsigned long long)mach_absolute_time(),\\n'\n")

MARK = 'printf("%llu " "gpu swapstat ok'


def patch(p: pathlib.Path) -> bool:
    t = p.read_text()
    if MARK in t:
        print('already patched:', p)
        return False
    if OLD_FMT not in t:
        sys.exit('swapstat format anchor missing in %s' % p)
    t = t.replace(OLD_FMT, NEW_FMT, 1)
    p.write_text(t)
    print('patched swapstat timestamp into:', p)
    return True


if __name__ == '__main__':
    for a in sys.argv[1:]:
        p = pathlib.Path(a)
        if p.exists():
            patch(p)
