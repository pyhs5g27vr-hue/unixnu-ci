#!/usr/bin/env python3
"""wifi-fastjoin.py — 内核侧 WiFi 扫描范围收窄 + 快速加入。

两个改动，都在 `nw_cfg80211_control.c`：

1. **扫描只问已知信道**（主收益）：`scan()` 在没有频点表时，原来扫全部 41 个信道（实测一次 6.7 秒，
   每 6.7 秒一轮，用户点网络时若正撞上就得等它扫完——这就是"连上慢"）。现在改成：用上一次扫描里
   真正有网络的信道集合（约 10 个）去扫，每第 4 次仍做全扫兜底（网络换信道也能发现）。
2. **join 的频点提示**：`find_bss()` 记住上次 join 的信道，下一次无频点扫描把它也算进提示集合。

用法：python3 wifi-fastjoin.py <仓库根>   幂等；找不到文件则报错退出。
"""
import sys
from pathlib import Path

NAME = 'nw_cfg80211_control.c'

DECL = '''/* fuxi: the channels the known networks are on (gathered as the scan results are built) and the one the last join
   named. A scan that names no channel asks those alone, with a full sweep every fourth: a phone that knows its
   access points does not spend 41 channels of radio time every scan. */
static uint32_t seen_frequencies[16];
static unsigned seen_count, scans_since_full;
static uint32_t last_join_frequency;
'''

HINT = '''  /* fuxi: ask the known networks' channels (and the last join's) instead of all of them, with a full sweep
     every fourth scan so a network that moved is still found. */
  uint32_t hint_frequencies[16];
  unsigned hint_count = 0;
  if (!freq_bytes) {
    scans_since_full++;
    const int full_sweep = seen_count == 0 || scans_since_full % 4 == 0;
    if (full_sweep) {
      scans_since_full = 0;
    } else {
      for (unsigned i = 0; i < seen_count && hint_count < 16; i++) hint_frequencies[hint_count++] = seen_frequencies[i];
      if (last_join_frequency) {
        unsigned i = 0;
        while (i < hint_count && hint_frequencies[i] != last_join_frequency) i++;
        if (i == hint_count && hint_count < 16) hint_frequencies[hint_count++] = last_join_frequency;
      }
      last_join_frequency = 0;
      freqs = (const u8 *)hint_frequencies;
      freq_bytes = (size_t)hint_count * sizeof(uint32_t);
    }
  }
'''

ANCHOR_SCAN = '  unsigned channels = freq_bytes ? freq_bytes / 4 : ieee80211_get_num_supported_channels(wiphy);\n'
ANCHOR_CHANNEL = '  if (!channel || (channel->flags & IEEE80211_CHAN_DISABLED)) return NULL;\n'
REMEMBER_JOIN = ANCHOR_CHANNEL + '  last_join_frequency = frequency; /* fuxi: the fast join hint for the next scan */\n'
ANCHOR_SNAPSHOT = '''    const struct cfg80211_bss_ies *ies = rcu_dereference(entry->pub.ies);
    if (!ies || !entry->pub.channel) continue;
'''
REMEMBER_SEEN = ANCHOR_SNAPSHOT + '''    {   /* fuxi: this scan's networks, the channels the next scan asks alone */
      const uint32_t center = entry->pub.channel->center_freq;
      unsigned i = 0;
      while (i < seen_count && seen_frequencies[i] != center) i++;
      if (i == seen_count) {
        if (seen_count == 0) scans_since_full = 0;
        if (seen_count < 16) seen_frequencies[seen_count++] = center;
      }
    }
'''
ANCHOR_RESET = '''static int snapshot_build(struct cfg80211_registered_device *rdev) {
  snapshot_free(); struct bss_snapshot **tail = &snapshot;
'''
RESET_SEEN = '''static int snapshot_build(struct cfg80211_registered_device *rdev) {
  snapshot_free(); struct bss_snapshot **tail = &snapshot;
  seen_count = 0;   /* fuxi: the channels gathered below are this scan's own */
'''


def patch(path: Path) -> bool:
    s = path.read_text()
    if 'seen_frequencies' in s:
        print('already patched:', path)
        return False
    for anchor, what in ((ANCHOR_SCAN, 'scan'), (ANCHOR_CHANNEL, 'channel'),
                         (ANCHOR_SNAPSHOT, 'snapshot'), (ANCHOR_RESET, 'reset')):
        assert s.count(anchor) == 1, '%s anchor in %s (%d)' % (what, path, s.count(anchor))

    first_scan = s.index('static int scan(struct cfg80211_registered_device *rdev')
    s = s[:first_scan] + DECL + '\n' + s[first_scan:]
    s = s.replace(ANCHOR_SCAN, HINT + ANCHOR_SCAN, 1)
    s = s.replace(ANCHOR_CHANNEL, REMEMBER_JOIN, 1)
    s = s.replace(ANCHOR_SNAPSHOT, REMEMBER_SEEN, 1)
    s = s.replace(ANCHOR_RESET, RESET_SEEN, 1)
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
