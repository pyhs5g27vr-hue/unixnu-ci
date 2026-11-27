#!/usr/bin/env python3
# Claude+Gemini 11-28: early completed handlers as an opt-in test. Upstream b25e48e keeps fireEarly/NBWaitInFlight but switched them off
# (earlyOn() false: blur passes read unfinished frames, i343/i344). Boot arg fuxi-metal-early=N turns them on while at most N command
# buffers are in flight; absent or 0 = upstream behaviour, unchanged.
import sys
from pathlib import Path
p = Path(sys.argv[1]); s = p.read_text()
old = 'static bool earlyOn() {return false;}'
assert s.count(old) == 1, ('earlyOn anchor', s.count(old))
s = s.replace(old,
 'static int earlyDepth() {   // fuxi: boot arg fuxi-metal-early=N, read once\n'
 ' static int depth=-1;\n'
 ' if(depth<0){char a[1100]={};size_t n=sizeof a-1;int v=0;\n'
 '  if(sysctlbyname("kern.bootargs",a,&n,nullptr,0)==0){const char *q=strstr(a,"fuxi-metal-early=");if(q)v=atoi(q+17);}\n'
 '  depth=v>0?v:0;}\n'
 ' return depth;\n'
 '}\n'
 'static bool earlyOn() {return earlyDepth()>0;}')
old = ' if(!earlyEligible || encodedWork.passes==0 || !earlyOn())return;\n'
assert s.count(old) == 1, ('fireEarly anchor', s.count(old))
s = s.replace(old, old +
 ' {NSUInteger inFlight;@synchronized(gInFlight){inFlight=gInFlight.count;}if(inFlight>(NSUInteger)earlyDepth())return;}\n')
if '#include <sys/sysctl.h>' not in s and '#import <sys/sysctl.h>' not in s:
    s = '#include <sys/sysctl.h>\n' + s
p.write_text(s)
print('fuxi-metal-early: earlyOn() from boot arg, in-flight cap')
