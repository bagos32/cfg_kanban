CARD_STATES = (
    "Available", "Consumed", "Signal Created", "Replenishment Requested",
    "Production Released", "In Production", "Produced", "In Transit", "Blocked", "Inactive",
)
CYCLE_STATES = (
    "New", "Signalled", "Released", "In Production", "Packing In Progress",
    "Production Complete", "Waiting FG Receipt", "Completed", "Hold", "Blocked", "Cancelled",
)
EXECUTION_STATES = ("Not Ready", "Ready", "In Progress", "Paused", "Waiting Input", "Completed", "Blocked", "Cancelled")
HANDOFF_MODES = ("Physical Card Handoff", "Digital Quantity Handoff", "Full Batch Handoff", "Automatic Handoff")

