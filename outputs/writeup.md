# GPU FinOps Optimization — NimbusAI Write-up

## 1. Baseline vs. Optimized

| Metric | Baseline | Optimized | Savings |
|--------|----------|-----------|---------|
| Monthly spend | $27,133 | $14,825 | **45% ($12,308)** |
| $/1M-token | $6.488 | $1.126 | **82.6%** |
| Energy per query | 0.24 Wh | 0.24 Wh | — |
| Carbon per query | 0.091 gCO2e | 0.091 gCO2e | — |

The key insight: measuring in **$/1M-token** (82.6% savings) looks much better than monthly spend (45% savings) because inference optimization also serves more tokens per dollar via cascade + caching + batch.

## 2. Analysis by Lever

| Lever | Savings | % of total | Why it works |
|-------|---------|------------|-------------|
| **Inference** (cascade/cache/batch) | $1,212/mo | 9.8% | Cascade routes simple requests to small model (15× cheaper). Cache gives 90% discount on cached input. Batch gives 50% off. Combined the discount stack is 0.05× of naive. |
| **Purchasing** (spot/reserved) | $9,841/mo | 80.0% | Biggest lever. Training jobs on spot (3-5% interruption risk with checkpoint). Steady inference workloads on reserved (45% discount). |
| **Right-size util-lies** | $655/mo | 5.3% | Downgraded GPU-h100-4 and gpu-a10g-1 from H100/A10G to lower tier since they show high GPU-Util but low MFU. |
| **Kill idle GPUs** | $600/mo | 4.9% | GPU-h100-5 had 8 idle hours/day. Simply turning it off saves $600/mo. |

**Winner:** Purchasing strategy alone is 80% of total savings.

## 3. GPU-Util Lie

- **GPU flagged:** `gpu-h100-4` (98.2% GPU-Util, MFU = 0.194) and `gpu-a10g-1` (96.9% GPU-Util, MFU = 0.268)
- **Why:** nvidia-smi GPU-Util measures "clock active time", not actual compute throughput. These GPUs were memory-stalled or I/O-waiting.
- **Financial impact:** Right-sizing these reduces cost from $2.50/hr (H100) / $1.00/hr (A10G) to appropriate tiers, saving $655/month.

## 4. Extensions Implemented

### Extension 1 — Improved `recommend_tier()` with GPU-specific interruption rates + 1yr/3yr comparison

**What changed:**
- Added `GPU_INTERRUPT_RATES` dict: H100=3%, A10G=10%, L4=12%, etc.
- Added `RESERVED_1YR_DISCOUNT=0.25` vs `RESERVED_3YR_DISCOUNT=0.45`
- Jobs with >=730 days get 3yr reserved; >=300 days get 1yr reserved; shorter jobs keep original logic
- Interruptible jobs with high interruption risk (>8%) may be pushed to reserved or on_demand instead of spot

**Measurement:** Before: 39.1% savings → After: 38.3% savings. The slight decrease is because `job-dev-sandbox` (A10G, 8h/day, interruptible) now correctly goes to on_demand instead of spot, since A10G has 10% interruption risk which makes spot risky for a stable dev environment.

### Extension 3 — `cache_is_worth_it()` function

**What was added:** New function `cache_is_worth_it(avg_cache_reads, write_cost_per_m, read_discount=0.10)` in `finops/pricing.py`.

**Logic:** Prompt caching has a write cost (storing the prefix) and read savings (90% off per cached read). The function returns True only when total read savings >= write cost.

**Measurement:** For write_cost_per_m=$3.00 (large model input pricing):
- With 1 read: $0.30 savings vs $3.00 write → not worth it (False)
- With 10 reads: $3.00 savings vs $3.00 write → break-even (True at 10+ reads)
- With 50 reads: $15.00 savings vs $3.00 write → very worth it (True)

**Insight:** Cache is only worthwhile when the same prefix is reused at least ~10 times. For unique/cold-start requests, caching actually costs more.

## 5. Recommendations for NimbusAI

If I were the FinOps lead, my top 3 actions:

1. **Fix the purchasing tier immediately.** Switching training jobs to spot (with checkpoint automation) and steady inference to reserved gets 80% of total savings — $9,841/month with near-zero engineering effort.

2. **Deploy inference cascade routing.** Add a simple router: route simple queries to small model (15× cheaper), keep large model only for complex reasoning. This alone drives $/1M-token from $6.49 to $1.13 (82.6% reduction).

3. **Stop trusting nvidia-smi GPU-Util.** Add MFU/MBU monitoring to the observability stack. GPU-h100-4 showing 98% util with only 19% MFU means we're paying $2.50/hr for 20% of the FLOPs — downgrade or fix the workload.