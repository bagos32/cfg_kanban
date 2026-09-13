from dataclasses import dataclass


@dataclass(frozen=True)
class CycleAllocationPlan:
    nominal_qty: float
    remaining_demand_qty: float
    available_input_qty: float
    effective_qty: float
    short_reason: str | None


def calculate_cycle_allocation(nominal_qty, remaining_demand_qty, available_input_qty):
    """Return a bounded runtime allocation without changing the reusable card quantity."""
    nominal = max(0.0, float(nominal_qty or 0))
    remaining = max(0.0, float(remaining_demand_qty or 0))
    available = max(0.0, float(available_input_qty or 0))
    effective = min(nominal, remaining, available)
    reason = None
    if effective < nominal:
        limiting_reasons = []
        if remaining <= effective:
            limiting_reasons.append("Remaining Demand")
        if available <= effective:
            limiting_reasons.append("Insufficient Input")
        reason = " and ".join(limiting_reasons)
    return CycleAllocationPlan(nominal, remaining, available, effective, reason)
