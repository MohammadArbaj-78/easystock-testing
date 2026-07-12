"""
Centralized alert color system.

This is the single source of truth for how urgency is communicated
visually across the entire app: Expired = Red, 7 Days = Orange,
15 Days = Yellow, 30 Days = Blue. Any module that shows an
expiry-urgency indicator - Expiry Alerts, the Dashboard's warning card,
and any future module (e.g. a notifications preview, a printable
report) - imports ALERT_TYPE_DISPLAY from here rather than defining its
own colors.

This file exists specifically because of a real bug: the Dashboard's
expiry warning card was first built reading colors from
modules/alerts/service.py, which worked, but made it easy to miss that
two different color schemes could silently exist if a second module
ever needed the same colors and someone redefined them inline instead
of importing them. Centralizing in config/ (alongside product_schema.py,
which solves the same kind of "one definition, many consumers" problem
for product fields) makes this an explicit, app-wide contract instead of
an implicit dependency on one module's internals.
"""

# Alert type identifiers - the canonical names for each urgency bucket,
# used as dict keys throughout the app. Defined here (not duplicated in
# modules/alerts/service.py) so there is exactly one definition of what
# these buckets are called.
ALERT_TYPE_EXPIRED = "expired"
ALERT_TYPE_7_DAYS = "7_days"
ALERT_TYPE_15_DAYS = "15_days"
ALERT_TYPE_30_DAYS = "30_days"

ALL_ALERT_TYPES = [ALERT_TYPE_EXPIRED, ALERT_TYPE_7_DAYS, ALERT_TYPE_15_DAYS, ALERT_TYPE_30_DAYS]

# The one and only color/icon/label definition per alert type. Every
# module that needs to show an expiry urgency indicator - regardless of
# whether it's a full section (Expiry Alerts) or a single summary card
# (Dashboard) - reads from this dict, so the app can never end up with
# two different color stories for the same bucket again.
ALERT_TYPE_DISPLAY = {
    ALERT_TYPE_EXPIRED: {"label": "Expired", "color": "#D32F2F", "icon": "🔴"},
    ALERT_TYPE_7_DAYS: {"label": "Expiring in 7 Days", "color": "#F57C00", "icon": "🟠"},
    ALERT_TYPE_15_DAYS: {"label": "Expiring in 15 Days", "color": "#FBC02D", "icon": "🟡"},
    ALERT_TYPE_30_DAYS: {"label": "Expiring in 30 Days", "color": "#1976D2", "icon": "🔵"},
}


def render_alert_banner(message: str, alert_type: str) -> str:
    """Return an HTML string for a color-coded left-bordered alert
    banner, ready to pass to st.markdown(..., unsafe_allow_html=True).

    Both the Dashboard warning card and individual Expiry Alerts rows
    call this function so their visual structure (border thickness,
    padding, border-radius) is identical, not just the same color.

    Args:
        message: The text to display inside the banner.
        alert_type: One of the ALERT_TYPE_* constants defined above.

    Returns:
        An HTML div string with the correct color and icon.

    Raises:
        KeyError: If alert_type is not a known key - a programming
            error, not a user-facing one.
    """
    display = ALERT_TYPE_DISPLAY[alert_type]
    color = display["color"]
    icon = display["icon"]
    return (
        f"<div style='border-left: 4px solid {color}; padding: 0.5rem 1rem; "
        f"margin: 0.4rem 0; background-color: rgba(0,0,0,0.02); "
        f"border-radius: 4px;'>"
        f"{icon} <strong>{message}</strong>"
        f"</div>"
    )
