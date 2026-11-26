#!/usr/bin/env python3
"""mu2-diag-patch.py : Dry-run verifier and exact ios17-grandslam.yml Python anchor patches for:
  a) GpuPowerProbe.cpp: native_adreno_owned_coherent default=1 + gpu-owned-coherent / sheng-gpu-owned-coherent boot-args
  b) NativeAdrenoPublish.cpp + NativeBridgeMetalFrontend.mm:
     - Kernel NativeAdrenoMethodNote (method 18): accept kind == 3 (text note, up to 30 words = 120 bytes) and IOLog to COM3 (capped at 64 lines)
     - Userspace NativeBridgeMetalFrontend.mm noteProblem(): forward non-harmless refusals (render pipeline descriptor/create, library, function, etc.)
       via tu_darwin_note(3, ...) (deduped, <=32 unique entries per process, <=160 bytes split into up to 2x80-byte chunks)
  c) Optional GpuPowerProbe.cpp:1349: deduped printf("gpu report: %.63s\\n", d.report) to COM3

Usage (dry-run check in WSL):
  python3 /mnt/e/DSH-Fuxi/dump/gemini/mu2-diag-patch.py --check
"""
from pathlib import Path
import sys

# =============================================================================
# BLOCK A + C: GpuPowerProbe.cpp (insert in ios17-grandslam.yml where GpuPowerProbe.cpp is patched)
# =============================================================================
GPUPOWER_PATCH = [
    (
        'extern "C" volatile uint32_t native_adreno_wc_enabled;\n',
        'extern "C" volatile uint32_t native_adreno_wc_enabled;\n'
        'extern "C" volatile uint32_t native_adreno_owned_coherent;\n',
        'GpuPowerProbe owned_coherent extern',
    ),
    (
        '    {unsigned wc = 1; PE_parse_boot_argn("sheng-gpu-wc", &wc, sizeof wc); native_adreno_wc_enabled = wc ? 1 : 0;}\n',
        '    {unsigned wc = 1; PE_parse_boot_argn("sheng-gpu-wc", &wc, sizeof wc); native_adreno_wc_enabled = wc ? 1 : 0;}\n'
        '    {unsigned oc = 1; if (!PE_parse_boot_argn("gpu-owned-coherent", &oc, sizeof oc)) PE_parse_boot_argn("sheng-gpu-owned-coherent", &oc, sizeof oc); native_adreno_owned_coherent = oc ? 1 : 0;}\n',
        'GpuPowerProbe owned_coherent boot-arg',
    ),
    (
        '    if (d.report[0]) snprintf(boot_progress_ext_wide[0], sizeof boot_progress_ext_wide[0], "R %.63s", d.report);\n',
        '    if (d.report[0]) {\n'
        '        snprintf(boot_progress_ext_wide[0], sizeof boot_progress_ext_wide[0], "R %.63s", d.report);\n'
        '        static char lastReport[64];\n'
        '        if (strncmp(lastReport, d.report, sizeof lastReport) != 0) {\n'
        '            strlcpy(lastReport, d.report, sizeof lastReport);\n'
        '            printf("gpu report: %.63s\\n", lastReport);\n'
        '        }\n'
        '    }\n',
        'GpuPowerProbe d.report to COM3',
    ),
]

# =============================================================================
# BLOCK B1: drivers/Adreno740/NativeAdrenoPublish.cpp (kernel side of NativeAdrenoMethodNote = 18)
# =============================================================================
PUBLISH_PATCH = [
    (
        '        if((note.kind!=NativeAdrenoNotePass && note.kind!=NativeAdrenoNotePipeline) || note.count>NativeAdrenoNoteWords)return kIOReturnBadArgument;\n',
        '        if(note.kind==3 && note.count>0 && note.count<=NativeAdrenoNoteWords) {\n'
        '            static volatile uint32_t fuxi_note_logged=0;\n'
        '            if(__atomic_fetch_add(&fuxi_note_logged,1,__ATOMIC_RELAXED)<64) {\n'
        '                char text[NativeAdrenoNoteWords*4+1];\n'
        '                const size_t nbytes=size_t(note.count)*4;\n'
        '                memcpy(text,note.words,nbytes);\n'
        '                text[nbytes]=0;\n'
        '                for(size_t i=0;i<nbytes && text[i];++i)if((unsigned char)text[i]<0x20 || (unsigned char)text[i]>0x7e)text[i]=\' \';\n'
        '                IOLog("fuxi metal-note[%d]: %s\\n",proc_selfpid(),text);\n'
        '            }\n'
        '            return kIOReturnSuccess;\n'
        '        }\n'
        '        if((note.kind!=NativeAdrenoNotePass && note.kind!=NativeAdrenoNotePipeline) || note.count>NativeAdrenoNoteWords)return kIOReturnBadArgument;\n',
        'NativeAdrenoPublish Note kind=3 IOLog',
    ),
]

# =============================================================================
# BLOCK B2: drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm (userspace noteProblem -> tu_darwin_note)
# Catches ALL non-harmless refusals: render pipeline descriptor (L5058), render pipeline create (L5104),
# library (failWith L4868/L4893), function (L1888), specialize, newLibraryWithSource (L4917), etc.
# Uses existing tu_darwin_note(uint32_t kind, const uint32_t *words, uint32_t count) in libvulkan_freedreno.dylib.
# =============================================================================
FRONTEND_PATCH = [
    (
        '  if(strcmp(line,gFirstProblem)) {\n'
        '   memcpy(gFirstProblem,line,sizeof line);\n'
        '   if(native_bridge_metal_problem_hook)native_bridge_metal_problem_hook(gFirstProblem);\n'
        '  }\n',
        '  if(strcmp(line,gFirstProblem)) {\n'
        '   memcpy(gFirstProblem,line,sizeof line);\n'
        '   if(native_bridge_metal_problem_hook)native_bridge_metal_problem_hook(gFirstProblem);\n'
        '  }\n'
        '  {\n'
        '   static std::set<std::string> fuxiSent;\n'
        '   const char *raw=what.UTF8String?:"?";\n'
        '   std::string msg(raw,strnlen(raw,160));\n'
        '   if(fuxiSent.size()<32 && fuxiSent.insert(msg).second) {\n'
        '    static bool (*noteFn)(uint32_t,const uint32_t *,uint32_t)=nullptr;\n'
        '    static bool looked=false;\n'
        '    if(!looked && !gLoaderPath.empty()) {\n'
        '     if(void *turnip=dlopen(gLoaderPath.c_str(),RTLD_NOW|RTLD_NOLOAD)) {\n'
        '      noteFn=(bool (*)(uint32_t,const uint32_t *,uint32_t))dlsym(turnip,"tu_darwin_note");\n'
        '      looked=true;\n'
        '     }\n'
        '    }\n'
        '    if(noteFn) {\n'
        '     for(size_t off=0;off<msg.size();off+=80) {\n'
        '      uint32_t words[21]={};\n'
        '      char *dst=(char *)words;\n'
        '      size_t pos=0;\n'
        '      if(off>0)dst[pos++]=\'+\';\n'
        '      const size_t chunk=msg.size()-off<80?msg.size()-off:80;\n'
        '      memcpy(dst+pos,msg.data()+off,chunk);\n'
        '      const uint32_t nwords=(uint32_t)((pos+chunk+4)/4);\n'
        '      (void)noteFn(3,words,nwords<=21?nwords:21);\n'
        '     }\n'
        '    }\n'
        '   }\n'
        '  }\n',
        'NativeBridgeMetalFrontend noteProblem -> tu_darwin_note',
    ),
]



def apply(path, patches):
    s = open(path).read()
    for old, new, label in patches:
        c = s.count(old)
        assert c == 1, 'ANCHOR FAIL [%s] in %s: count=%d' % (label, path, c)
        s = s.replace(old, new, 1)
        print('applied [%s] %s' % (label, path))
    open(path, 'w').write(s)

if __name__ == '__main__':
    mode, files = sys.argv[1], sys.argv[2:]
    patches = {'gpupower': GPUPOWER_PATCH, 'publish': PUBLISH_PATCH, 'frontend': FRONTEND_PATCH}[mode]
    assert len(files) == 1, ('expected exactly one file for', mode, files)
    apply(files[0], patches)
