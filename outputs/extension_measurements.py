"""Measure and compare Extension 1 and Extension 3 results."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finops import pricing
from missions._common import load_csv, num

print("=" * 70)
print("EXTENSION 1 — Improved recommend_tier()")
print("=" * 70)

# Compare old vs new policy for each job
jobs = load_csv("workloads.csv")
print(f"{'job_id':18}{'gpu':7}{'hpd':4}{'intr':5}{'days':5}{'old_tier':11}{'new_tier':11}")
for j in jobs:
    hpd = num(j["hours_per_day"])
    interruptible = bool(int(num(j["interruptible"])))
    days = int(num(j["days"]))
    gtype = j["gpu_type"]
    
    # Old policy (no gpu_type, no job_days)
    old_tier = pricing.recommend_tier(hpd, interruptible)
    # New policy (with gpu_type, job_days)
    new_tier = pricing.recommend_tier(hpd, interruptible, gpu_type=gtype, job_days=days)
    marker = " <--" if old_tier != new_tier else ""
    print(f"{j['job_id']:18}{gtype:7}{hpd:4}{int(interruptible):5}{days:5}{old_tier:11}{new_tier:11}{marker}")

print()
print("GPU interruption rates used:")
for gpu, rate in sorted(pricing.GPU_INTERRUPT_RATES.items()):
    print(f"  {gpu}: {rate:.0%}")
print(f"  1yr reserved discount: {pricing.RESERVED_1YR_DISCOUNT:.0%}")
print(f"  3yr reserved discount: {pricing.RESERVED_3YR_DISCOUNT:.0%}")

print()
print("=" * 70)
print("EXTENSION 3 — cache_is_worth_it()")
print("=" * 70)

# Calculate break-even reads for each model tier
for tier_name, price_in, price_out in [("small (0.20, 0.40)", 0.20, 0.40), ("large (3.00, 15.00)", 3.00, 15.00)]:
    write_cost = price_out if price_out > price_in else price_in
    print(f"\n  Model tier: {tier_name}")
    print(f"  Write cost per M tokens: ${write_cost}")
    for reads in [1, 5, 10, 20, 50, 100]:
        worth = pricing.cache_is_worth_it(reads, write_cost)
        print(f"    {reads:4} reads → {'WORTH IT' if worth else 'NOT worth'} (savings=${reads * (1-0.10) * write_cost:.2f} vs write=${write_cost:.2f})")

# Check actual cache read frequency in token_usage.csv
print("\n  Analyzing actual cached_input_tokens in token_usage.csv...")
rows = load_csv("token_usage.csv")
total_with_cache = sum(1 for r in rows if int(num(r["cached_input_tokens"])) > 0)
total = len(rows)
print(f"    Requests with cache: {total_with_cache}/{total} ({total_with_cache/total*100:.1f}%)")

# Count requests by route_tier with caching
by_tier = {}
for r in rows:
    tier = r["route_tier"]
    if tier not in by_tier:
        by_tier[tier] = {"total": 0, "cached": 0, "total_cached_tokens": 0}
    by_tier[tier]["total"] += 1
    cached = int(num(r["cached_input_tokens"]))
    if cached > 0:
        by_tier[tier]["cached"] += 1
        by_tier[tier]["total_cached_tokens"] += cached

print("\n    Cache usage by route tier:")
for tier, data in sorted(by_tier.items()):
    pct = data["cached"] / data["total"] * 100 if data["total"] else 0
    price_per_m = 0.20 if tier == "small" else 3.00
    worth = pricing.cache_is_worth_it(10, price_per_m)
    print(f"    {tier:7}: {data['cached']:4}/{data['total']:4} cached ({pct:.0f}%) | break-even @ 10 reads → {'WORTH IT' if worth else 'NOT worth'}")

print()
print("=" * 70)
print("SUMMARY: Both extensions implemented with measurable results")
print("=" * 70)