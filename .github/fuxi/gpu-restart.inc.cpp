// fuxi 2026-11-20: from matejkoo217/UniXNU-fuxi b76a167 package/GpuPowerProbe.cpp (gpuHwInit, gpuRestart).
// This base never installed a restart hook: hangCheck saw hangs (fuxi hang: detect) but recover() never ran.
void gpuHwInit() {
    gpuWr(A740_GBIF_HALT, 0); (void)gpuRd(A740_GBIF_HALT);
    gpuWr(A740_RBBM_GBIF_HALT, 0); (void)gpuRd(A740_RBBM_GBIF_HALT);
    gpuWr(A740_RBBM_SECVID_TSB_CNTL, 0);
    gpuWr64(A740_RBBM_SECVID_TSB_TRUSTED_BASE, 0);
    gpuWr(A740_RBBM_SECVID_TSB_TRUSTED_SIZE, 0);
    // a6xx_set_hwcg(true): gmu_cgc_mode 0x00020202, cgc delay 0x10111, hyst 0x5555, then the table unless already on.
    gmuWr(A740_GPU_GMU_AO_GMU_CGC_MODE_CNTL, 0x00020202);
    gmuWr(A740_GPU_GMU_AO_GMU_CGC_DELAY_CNTL, 0x10111);
    gmuWr(A740_GPU_GMU_AO_GMU_CGC_HYST_CNTL, 0x5555);
    if (gpuRd(A740_RBBM_CLOCK_CNTL) != 0x8aa8aa82) {
        for (unsigned i = 0; i < NATIVE_ADRENO_A740_HWCG_COUNT; ++i) gpuWr(NativeAdrenoA740Hwcg[i][0], NativeAdrenoA740Hwcg[i][1]);
        gpuWr(A740_RBBM_CLOCK_CNTL, 0x8aa8aa82);
    }
    gpuWr(A740_RBBM_GBIF_CLIENT_QOS_CNTL, 0x2120212);
    gpuWr(A740_UCHE_GBIF_GX_CONFIG, 0x10240e0);
    gpuWr(A740_RBBM_PERFCTR_GPU_BUSY_MASKED, 0xffffffff);
    gpuWr64(A740_UCHE_TRAP_BASE, 0x1fffffffff000ull);
    gpuWr64(A740_UCHE_WRITE_THRU_BASE, 0x1fffffffff000ull);
    gpuWr64(A740_UCHE_GMEM_RANGE_MIN, 0x1000000);                    // a740 family: SZ_16M
    gpuWr64(A740_UCHE_GMEM_RANGE_MAX, 0x1000000 + 3 * 0x100000 - 1);  // gmem 3 MiB
    gpuWr(A740_UCHE_CACHE_WAYS, 1u << 23);
    gpuWr(A740_CP_AHB_CNTL, 0x1);
    gpuWr(A740_RBBM_PERFCTR_CNTL, 0x1);
    gpuWr(A740_RBBM_INTERFACE_HANG_INT_CNTL, (1u << 30) | 0xcfffff);
    gpuWr(A740_UCHE_CLIENT_PF, (1u << 7) | 0x1);
    // a6xx_set_cp_protect: ACCESS_PROT_EN | ACCESS_FAULT_ON_VIOL_EN | LAST_SPAN_INF_RANGE, then a730_protect.
    gpuWr(A740_CP_PROTECT_CNTL, (1u << 0) | (1u << 1) | (1u << 3));
    for (unsigned i = 0; i < NATIVE_ADRENO_A740_PROTECT_COUNT; ++i)
        gpuWr(A740_CP_PROTECT + NativeAdrenoA740Protect[i][0], NativeAdrenoA740Protect[i][1]);
    gpuWr(A740_UCHE_CMDQ_CONFIG, (6u << 16) | (6u << 12) | (9u << 8) | (1u << 3) | (1u << 2) | 2u);
    // hw_apriv: A7XX_BR_APRIVMASK (ICACHE|RBFETCH|RBPRIVLEVEL|RBRPWB|CDREAD|CDWRITE) and A7XX_APRIV_MASK.
    gpuWr(A740_CP_APRIV_CNTL, 0x6f);
    gpuWr(A740_CP_BV_APRIV_CNTL, 0x0f);
    gpuWr(A740_CP_LPAC_APRIV_CNTL, 0x0f);
    gpuWr(A740_RB_CMP_DBG_ECO_CNTL, gpuRd(A740_RB_CMP_DBG_ECO_CNTL) | (1u << 11));
    // a6xx_set_ubwc_config, sm8550_data: UBWC 4.0 encoder, swizzle levels 2+3, highest bank bit 16 (hbb_lo 3, hbb_hi 0),
    // AMSBC on (>= 3.0), rgb565 predicator on (>= 4.0), min_acc_len_64b off, ubwc_mode off, uavflagprd_inv 2,
    // macrotile mode on.
    gpuWr(A740_RB_NC_MODE_CNTL, (1u << 11) | (1u << 4) | (3u << 1));
    gpuWr(A740_TPL1_NC_MODE_CNTL, 3u << 1);
    gpuWr(A740_SP_NC_MODE_CNTL, (2u << 4) | (3u << 1));
    for (uint32_t pipe = 1; pipe <= 2; ++pipe) {   // PIPE_BR, PIPE_BV
        gpuWr(A740_CP_APERTURE_CNTL_HOST, pipe << 12);
        gpuWr(A740_GRAS_NC_MODE_CNTL, 3u << 5);
    }
    gpuWr(A740_CP_APERTURE_CNTL_HOST, 0);           // PIPE_NONE
    gpuWr(A740_UCHE_MODE_CNTL, 3u << 21);
    gpuWr(A740_RBBM_NC_MODE_CNTL, 1);
    // A7XX_INT_MASK: bits 1,6,7,8,9,15,17,20,22,23,24,25,28,29. Nothing services the GPU interrupt yet; status is polled.
    gpuWr(A740_RBBM_INT_0_MASK, 0x33d283c2);
    gpuWr64(A740_CP_SQE_INSTR_BASE, gGpuBuffers[0].iova);
}
// The GPU restart after a hang (NativeAdrenoSubmit::recover, under the publish lock): a6xx_recover's reset for a GPU whose GMU it does
// not power-cycle (the adreno_has_gmu_wrapper branch: GBIF drained including its GX side, RBBM_SW_RESET_CMD asserted for at least
// 100 us, then released) followed by msm_gpu_hw_init's hw_init on the same ring: registers, ring, SQE start, a7xx_cp_init waited
// with a6xx_idle, and CP_SET_SECURE_MODE 0 again when the zap shader was loaded (a6xx_zap_shader_init returns 0 once loaded). The
// GMU keeps running and keeps the OOB GPU_SET vote; its power-collapse cycle needs a GMU stop and warm-boot path the GMU kit does
// not have. [0] restarts, [1] the step a failed one stopped at, [2] its status, [3] RBBM_STATUS after the reset.
extern "C" {uint32_t native_gpu_restart[4];}
IOReturn gpuRestart(void *, NativeAdrenoRing *ring, uint32_t completed) {
    uint32_t *r = native_gpu_restart;
    r[0] = r[0] + 1;
    auto fail = [&](uint32_t step, IOReturn status) {r[1] = step; r[2] = uint32_t(status); return status ? status : kIOReturnIOError;};
    if (!ring) return fail(1, kIOReturnBadArgument);
    if (gxOn()) gpuWr(A740_CP_SQE_CNTL, 3);
    // spin_until is bounded by ADRENO_IDLE_TIMEOUT (1 s); a GBIF register read is well under a microsecond, so 1000000 reads stay inside it.
    IOReturn status = ring->busHalt(true, 1000000);
    if (status) return fail(2, status);
    gpuWr(A740_RBBM_SW_RESET_CMD, 1); (void)gpuRd(A740_RBBM_SW_RESET_CMD); IODelay(1);
    IODelay(100);
    gpuWr(A740_RBBM_SW_RESET_CMD, 0); (void)gpuRd(A740_RBBM_SW_RESET_CMD); IODelay(1);
    r[3] = gpuRd(A740_RBBM_STATUS);
    gpuHwInit();
    status = ring->restart(completed);
    if (status) return fail(3, status);
    gpuWr64(A740_CP_BV_RB_RPTR_ADDR, gGpuBuffers[2].iova + 8);
    gpuWr(A740_CP_SQE_CNTL, 1);
    // The power-up list stays as a7xx_patch_pwrup_reglist wrote it at bring-up (pwrup_reglist_emitted).
    const NativeAdrenoRingIo rio{nullptr, ringWrite, ringRead, ringBarrier, nullptr, nullptr};
    const NativeAdrenoCpInitConfig config{gGpuBuffers[0].iova, gGpuBuffers[3].iova, 1};
    const NativeAdrenoRingClock clock{nullptr, ringNow, nullptr};
    NativeAdrenoCpInit init;
    uint32_t fence = 0;
    status = init.run(&rio, ring, &config, &fence, false);
    if (status) return fail(4, status);
    status = ring->idle(&clock, 1000000);
    if (status) return fail(5, status);
    if (native_gpu_zap[0] == 9) {
        uint32_t words[2] = {};
        if (AdrenoPM4Type7(0x66, 1, &words[0]) != AdrenoPM4Success) return fail(6, kIOReturnInternalError);
        status = ring->submitUnfenced(words, 2);
        if (!status) status = ring->idle(&clock, 1000000);
        if (status) return fail(6, status);
    }
    r[1] = 0; r[2] = 0;
    return kIOReturnSuccess;
}
