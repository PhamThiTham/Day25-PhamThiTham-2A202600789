"""Pricing & purchasing economics — measure in $/1M-token, not $/GPU-hr.

Figures are June-2026 as-of snapshots from the deck's RESEARCH dossier; treat
live prices as fast-moving (re-baseline before each cohort).
"""
from __future__ import annotations


def request_cost(
    input_tok: int,
    output_tok: int,
    price_in_per_m: float,
    price_out_per_m: float,
    cached_in: int = 0,
    cache_discount: float = 0.10,   # Anthropic cached-read ~0.1x (=-90%)
    batch: bool = False,
    batch_discount: float = 0.50,   # Batch API ~ -50%
) -> float:
    """USD cost of a single request. Cached input billed at cache_discount x price."""
    cached_in = min(max(0, cached_in), input_tok)
    uncached_in = input_tok - cached_in
    cost = (
        (uncached_in / 1e6) * price_in_per_m
        + (cached_in / 1e6) * price_in_per_m * cache_discount
        + (output_tok / 1e6) * price_out_per_m
    )
    if batch:
        cost *= batch_discount
    return cost


def dollars_per_million(total_cost_usd: float, total_tokens: int) -> float:
    """Aggregate unit economics: $ per 1,000,000 tokens served."""
    if total_tokens <= 0:
        return 0.0
    return total_cost_usd / (total_tokens / 1e6)


def discount_stack(
    batch: bool = False,
    cache_hit_frac: float = 0.0,
    batch_discount: float = 0.50,
    cache_discount: float = 0.10,
) -> float:
    """Effective fraction of the naive bill after stacking discounts (input-heavy view).

    Discounts MULTIPLY: cache applies to the cached share of input, batch to the
    whole bill. batch + 100% cache-hit -> 0.5 * 0.1 = 0.05 (~95% off).
    """
    cache_mult = cache_hit_frac * cache_discount + (1.0 - cache_hit_frac)
    batch_mult = batch_discount if batch else 1.0
    return cache_mult * batch_mult


def cache_is_worth_it(
    avg_cache_reads: float,
    write_cost_per_m: float,
    read_discount: float = 0.10,
) -> bool:
    """Determine if prompt caching is financially worthwhile.

    Prompt caching has a one-time write cost (storing the prefix), and each read
    is billed at read_discount × the normal price (e.g., 0.10 = 90% off).
    Caching is worth it when total savings from reads exceed the write cost.

    Args:
        avg_cache_reads: Average number of times a cached prefix is read.
        write_cost_per_m: Cost per million tokens to write/store the cache (USD).
        read_discount: Fraction of the normal price for cached reads (default 0.10).

    Returns:
        True if caching is worth it (savings >= write cost), False otherwise.
    """
    if avg_cache_reads <= 0 or write_cost_per_m <= 0:
        return False
    # Savings per read = (1 - read_discount) * write_cost_per_m
    # Total savings from all reads = reads * savings_per_read
    savings_per_read = (1.0 - read_discount) * write_cost_per_m
    total_savings = avg_cache_reads * savings_per_read
    # Caching is worth it when total savings cover the one-time write cost
    return total_savings >= write_cost_per_m


def break_even_utilization(discount_frac: float) -> float:
    """Utilization at which a commitment pays off ~= 1 - discount.

    A 45% reserved discount needs ~55% utilization (~13.2h/day) to beat on-demand.
    """
    return max(0.0, min(1.0, 1.0 - discount_frac))


# Per-GPU interruption rates (illustrative): premium GPUs like H100 are less
# likely to be reclaimed than cheaper ones like A10G.
GPU_INTERRUPT_RATES = {
    "H100": 0.03,
    "H200": 0.02,
    "A100": 0.05,
    "A10G": 0.10,
    "L4": 0.12,
    "B200": 0.02,
    "MI300X": 0.06,
}

# Reserved discount: 3yr is deeper than 1yr.
RESERVED_1YR_DISCOUNT = 0.25  # rough: (od - 1yr) / od
RESERVED_3YR_DISCOUNT = 0.45


def recommend_tier(
    hours_per_day: float,
    interruptible: bool,
    reserved_discount: float = 0.45,
    gpu_type: str | None = None,
    job_days: int | None = None,
) -> str:
    """Pick a purchasing tier from a workload's duty cycle + interruptibility.

    Enhanced version (Extension 1):
      - Uses GPU-specific interruption rates for spot suitability.
      - Compares 1yr vs 3yr reserved based on job duration.
      - Falls back to original simple policy if gpu_type/job_days not provided.

    Args:
        hours_per_day: Daily GPU-hours for the workload.
        interruptible: Whether the job can be interrupted.
        reserved_discount: Base reserved discount (used if gpu_type not given).
        gpu_type: Type of GPU (e.g. "H100", "A10G") for per-GPU rates.
        job_days: Duration of the job in days (for 1yr vs 3yr comparison).

    Returns:
        "spot", "reserved", or "on_demand".
    """
    duty = max(0.0, hours_per_day) / 24.0

    # Factor 1: Interruption rate by GPU type — if interruptible & low interruption
    # risk, spot is even more attractive; if high interruption risk, reserve may win.
    interrupt_rate = GPU_INTERRUPT_RATES.get(gpu_type, 0.05) if gpu_type else 0.05

    # Factor 2: Choose the best reserved term based on job duration.
    # If job_days is given and closer to 1yr (~365d), use 1yr pricing.
    # If job_days is closer to 3yr (~1095d), use 3yr pricing.
    if job_days is not None and gpu_type is not None:
        # 1yr reserved discount is shallower; 3yr is deeper
        if job_days >= 730:  # >= 2 years → 3yr reserved
            effective_discount = RESERVED_3YR_DISCOUNT
        elif job_days >= 300:  # ~1 year → 1yr reserved
            effective_discount = RESERVED_1YR_DISCOUNT
        else:
            effective_discount = reserved_discount
    else:
        effective_discount = reserved_discount

    be = break_even_utilization(effective_discount)

    # Tier decision logic
    if interruptible:
        if hours_per_day < 24:
            # Spot is better for interruptible jobs, but only if interruption
            # rate is low enough — otherwise reserved or on_demand wins.
            if interrupt_rate <= 0.08:  # low interruption risk → spot
                return "spot"
            # High interruption rate: even interruptible jobs may prefer reserved
            if duty >= be:
                return "reserved"
            return "on_demand"
        # 24/7 interruptible is unusual — treat as reserved if high duty
        elif duty >= be:
            return "reserved"
        return "on_demand"

    # Non-interruptible: standard duty-based logic
    if duty >= be:
        return "reserved"
    return "on_demand"


def spot_checkpoint_cost(
    job_hours: float,
    spot_hr: float,
    on_demand_hr: float,
    interrupt_rate: float = 0.05,      # per-hour chance (H100 spot ~<5%)
    ckpt_overhead_frac: float = 0.03,  # steady cost of writing checkpoints
    rework_hours_per_interrupt: float = 0.5,
) -> dict:
    """Effective cost of running a checkpointable job on spot vs on-demand.

    Interruptions waste the compute since the last checkpoint (rework); checkpointing
    adds a small steady overhead. Spot still wins for interruptible jobs.
    """
    expected_interrupts = job_hours * interrupt_rate
    rework_hours = expected_interrupts * rework_hours_per_interrupt
    effective_hours = job_hours * (1.0 + ckpt_overhead_frac) + rework_hours
    spot_cost = effective_hours * spot_hr
    on_demand_cost = job_hours * on_demand_hr
    savings_pct = (1.0 - spot_cost / on_demand_cost) * 100.0 if on_demand_cost > 0 else 0.0
    return {
        "spot_effective_hours": round(effective_hours, 2),
        "spot_cost": round(spot_cost, 2),
        "on_demand_cost": round(on_demand_cost, 2),
        "savings_pct": round(savings_pct, 1),
    }
