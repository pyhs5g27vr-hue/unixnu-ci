#!/usr/bin/env python3
"""wifi-fastjoin.py — 内核侧 WiFi 快速加入：join 之后的第一次扫描只问上次的信道。

背景：内核驱动 `nw_cfg80211_control.c` 的 scan() 在没有带频点表时扫全部 41 个信道；
实测每 ~15 秒一次全扫，且状态机 stage 5↔6 来回振荡，用户侧感受就是「连上很慢」。
supplicant 极少在扫描里点名信道，但它在 join 时会带 NW_CONTROL_ATTR_FREQUENCY
（find_bss 就用它找 BSS）。所以记住上次 join 的频点，下一次无频点扫描只用它扫一次
（一发式：用完即清，扫不到就退回上游的全扫逻辑），把「全扫几秒」压成「单信道几十毫秒」。

用法：python3 wifi-fastjoin.py <仓库根>   幂等，找不到文件则报错退出。
"""
import sys
from pathlib import Path

NAME = 'nw_cfg80211_control.c'

DECL = '''/* fuxi: the channel the last join named. The first scan after it asks that one alone (one-shot; a miss
   falls back to the full sweep), so a join does not sit behind a 41-channel scan. */
static uint32_t last_join_frequency;
'''

HINT = '''  /* fuxi: ask the channel of the last join alone for this one scan; the retries stay full (see above). */
  uint32_t join_hint = 0;
  if (!freq_bytes && last_join_frequency) {
    join_hint = last_join_frequency;
    last_join_frequency = 0;
    freqs = (const u8 *)&join_hint;
    freq_bytes = sizeof join_hint;
  }
'''

ANCHOR_SCAN = '  unsigned channels = freq_bytes ? freq_bytes / 4 : ieee80211_get_num_supported_channels(wiphy);\n'
ANCHOR_CHANNEL = '  if (!channel || (channel->flags & IEEE80211_CHAN_DISABLED)) return NULL;\n'
REMEMBER = ANCHOR_CHANNEL + '  last_join_frequency = frequency; /* fuxi: the fast join\'s hint for the next scan */\n'


def patch(path: Path) -> bool:
    s = path.read_text()
    if 'last_join_frequency' in s:
        print('already patched:', path)
        return False
    assert s.count(ANCHOR_SCAN) == 1, 'scan anchor in %s' % path
    assert s.count(ANCHOR_CHANNEL) == 1, 'channel anchor in %s' % path
    # 1) 全局变量：放在第一个 scan() 之前
    first_scan = s.index('static int scan(struct cfg80211_registered_device *rdev')
    s = s[:first_scan] + DECL + '\n' + s[first_scan:]
    # 2) scan()：无频点表时用一发式提示
    s = s.replace(ANCHOR_SCAN, HINT + ANCHOR_SCAN, 1)
    # 3) find_bss()：记住 join 的频点
    s = s.replace(ANCHOR_CHANNEL, REMEMBER, 1)
    path.write_text(s)
    print('patched:', path)
    return True


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.')
    hits = [p for p in root.rglob(NAME) if p.is_file()]
    if not hits:
        sys.exit('no %s under %s' % (NAME, root))
    changed = 0
    for p in hits:
        try:
            changed += 1 if patch(p) else 0
        except AssertionError as e:
            sys.exit('%s: %s' % (p, e))
    print('files: %d, patched: %d' % (len(hits), changed))


if __name__ == '__main__':
    main()
