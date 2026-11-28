#!/usr/bin/env python3
"""Gemini 2026-11-28: fuxi-adt-disable-jobs.py ROOT... : extend BootWatchdogPolicy.c so launchd disabled jobs
can also be supplied via ADT /chosen/sheng-disable-jobs (comma-separated, up to 1023 bytes, 0 boot-args bytes).
Works alongside existing boot-arg sheng-disable-jobs= and sheng-lite=1; bumps policy[] to 4096 bytes.
Usage: fuxi-adt-disable-jobs.py ROOT..."""
import pathlib
import sys

INC_ANCHOR = '#include <pexpert/pexpert.h>\n'
INC_ADD = '#include <pexpert/device_tree.h>\n'

BUF_OLD = 'static char policy[2048],jobs[200];\n'
BUF_NEW = 'static char policy[4096],jobs[200],dt_jobs[1024];\n'

PARSE_ANCHOR = ' if(!PE_parse_boot_argn("sheng-disable-jobs",jobs,sizeof(jobs)))jobs[0]=0;jobs[sizeof(jobs)-1]=0;\n'
PARSE_ADD = ''' dt_jobs[0]=0;
 {
  DTEntry chosen;
  void const *dt_prop=NULL;
  unsigned int dt_sz=0;
  if(SecureDTLookupEntry(NULL,"/chosen",&chosen)==kSuccess &&
     SecureDTGetProperty(chosen,"sheng-disable-jobs",&dt_prop,&dt_sz)==kSuccess && dt_prop && dt_sz) {
   size_t n=dt_sz;
   const char *src=(const char *)dt_prop;
   while(n && src[n-1]==0)--n;
   if(n>=sizeof(dt_jobs))n=sizeof(dt_jobs)-1;
   memcpy(dt_jobs,src,n);dt_jobs[n]=0;
   for(const char *c=dt_jobs;*c;++c)
    if(!((*c>='a'&&*c<='z')||(*c>='A'&&*c<='Z')||(*c>='0'&&*c<='9')||*c=='.'||*c=='-'||*c=='_'||*c==','))
     {dt_jobs[0]=0;break;}
   if(dt_jobs[0])printf("fuxi adt disable-jobs: %zu bytes\\n",strlen(dt_jobs));
  }
 }
'''

GUARD_OLD = ' if(!enabled && !jobs[0] && !lite && !no_fairplay)return 0;\n'
GUARD_NEW = ' if(!enabled && !jobs[0] && !dt_jobs[0] && !lite && !no_fairplay)return 0;\n'

LOOP_ANCHOR = ' for(const char *c=jobs;*c;) {if((error=append_job(&c)))return error;}\n'
LOOP_ADD = ' for(const char *c=dt_jobs;*c;) {if((error=append_job(&c)))return error;}\n'

n = 0
for root in sys.argv[1:]:
    for p in sorted(pathlib.Path(root).rglob('BootWatchdogPolicy.c')):
        s = p.read_text()
        if 'fuxi adt disable-jobs:' in s:
            print('adt-disable-jobs: already', p)
            n += 1
            continue
        if s.count(PARSE_ANCHOR) != 1 or s.count(BUF_OLD) != 1:
            print('adt-disable-jobs: skip', p)
            continue
        assert s.count(INC_ANCHOR) == 1, f'{p}: INC_ANCHOR count={s.count(INC_ANCHOR)}'
        assert s.count(BUF_OLD) == 1, f'{p}: BUF_OLD count={s.count(BUF_OLD)}'
        assert s.count(PARSE_ANCHOR) == 1, f'{p}: PARSE_ANCHOR count={s.count(PARSE_ANCHOR)}'
        assert s.count(GUARD_OLD) == 1, f'{p}: GUARD_OLD count={s.count(GUARD_OLD)}'
        assert s.count(LOOP_ANCHOR) == 1, f'{p}: LOOP_ANCHOR count={s.count(LOOP_ANCHOR)}'
        if INC_ADD not in s:
            s = s.replace(INC_ANCHOR, INC_ANCHOR + INC_ADD, 1)
        s = s.replace(BUF_OLD, BUF_NEW, 1)
        s = s.replace(PARSE_ANCHOR, PARSE_ANCHOR + PARSE_ADD, 1)
        s = s.replace(GUARD_OLD, GUARD_NEW, 1)
        s = s.replace(LOOP_ANCHOR, LOOP_ANCHOR + LOOP_ADD, 1)
        p.write_text(s)
        n += 1
        print('adt-disable-jobs:', p)
assert n >= 1, 'no BootWatchdogPolicy.c patched'
