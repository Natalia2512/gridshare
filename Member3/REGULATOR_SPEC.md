# Member 3 — Regulator Rule Specification

## 1. Primary objective

Maximise the fraction of **locally tradable renewable energy** that is exchanged through bilateral P2P trading.

The main KPI is:

`P2P utilisation = P2P energy traded / min(total community surplus, total community deficit)`

This is preferred to "minimise grid import" because, with the current project assumptions (no battery and no flexible load), net external-grid import is physically determined by total demand minus total PV. The regulator can change the trading route and incentives, but not that physical balance.

Target for the adaptive policy: **90% P2P utilisation when P2P trading is physically possible.**

Secondary KPIs: community external-energy cost, regulator incentive cost, locally used renewable share, and buyer-price fairness (Jain index).

## 2. Regulatory mechanisms

### P2P seller bonus

The regulator pays a bonus in EUR/kWh to P2P sellers. Member 2's matching engine applies it as:

`effective ask = seller limit price - regulator bonus`

A larger bonus therefore makes more buyer/seller pairs economically compatible.

### Green-first priority

In fixed and adaptive modes, green-oriented sellers receive priority when effective ask prices are tied. Price remains the primary matching criterion.

### Anti-gouging rule and one-step ban

A SELL order is marked as a violation when either condition is true:

- ask price > 90% of the grid retail tariff; or
- ask price > forecast price × 1.20.

Violations detected at step `t` are included in the policy for step `t+1`. Those prosumers are excluded from P2P for one step but may still settle through the aggregator, so the energy balance is never broken.

## 3. Scenario policies

### Baseline (`none`)

- bonus = 0
- priority = price only
- no bans/caps

Purpose: provide a clean price-only reference.

### Fixed

- bonus = 0.0125 EUR/kWh
- priority = green-first on price ties
- one-step anti-gouging bans

Purpose: test whether a simple fixed incentive improves local trading.

### Adaptive

Uses the same priority and anti-gouging rules, but updates the bonus from previous-step performance.

Let:

- `u[t-1]` = previous P2P utilisation
- `b[t-1]` = previous bonus
- target = 0.90
- gain = 0.02

Then:

`b[t] = clip(0.0125 + 0.05 × (0.90 - u[t-1]), 0, 0.06)`

This is a stateless proportional feedback rule. At the 90% target the bonus is the base 0.0125 EUR/kWh; below target it rises and above target it falls. The rule does not need to reconstruct a previous bonus from subsidy spending, so it remains well-defined even when previous P2P volume is zero.

If there was no physically tradable energy in the previous hour, the controller uses the base bonus of 0.0125 EUR/kWh and does not react to the zero P2P share. This prevents artificial incentive wind-up at night.

## 4. Determinism

For the same `previous_metrics` and simulation configuration, `get_policy()` always returns the same policy. No random number generator is used by the regulator.

## 5. Expected experiment

Run all scenarios with the same seed/input traces:

1. baseline
2. fixed
3. adaptive
4. adaptive + PV shortage

Compare P2P utilisation, total P2P kWh, external-grid import, external-energy cost, regulator bonus cost, renewable share, fairness, and number of bans.

The expected conclusion should be based on the simulation output, not assumed in advance. A useful result is a trade-off: adaptive incentives can increase P2P utilisation, but may require additional regulator subsidy.
