import frappe


MASTER_OVERRIDE = "Master Override"
USE_GLOBAL_DEFAULT = "Use Global Default"
AUTOMATION_POLICY_SOURCES = (MASTER_OVERRIDE, USE_GLOBAL_DEFAULT)
AUTOMATION_LEVELS = ("Automatic", "Approval", "Signal Only")
SAFE_DEFAULT_AUTOMATION_LEVEL = "Approval"


def get_automation_policy_source(master):
    """Return the policy source while preserving pre-upgrade Master behaviour."""
    source = master.get("automation_policy_source") or MASTER_OVERRIDE
    return source if source in AUTOMATION_POLICY_SOURCES else MASTER_OVERRIDE


def get_effective_automation_level(master):
    """Resolve the immutable automation value to snapshot on a new Signal."""
    source = get_automation_policy_source(master)
    if source == USE_GLOBAL_DEFAULT:
        level = frappe.db.get_single_value(
            "CFG Kanban Settings", "default_automation_level"
        )
    else:
        level = master.get("automation_level")
    return level if level in AUTOMATION_LEVELS else SAFE_DEFAULT_AUTOMATION_LEVEL


def get_automation_policy_snapshot(master):
    return {
        "source": get_automation_policy_source(master),
        "configured_level": master.get("automation_level") or SAFE_DEFAULT_AUTOMATION_LEVEL,
        "effective_level": get_effective_automation_level(master),
    }
