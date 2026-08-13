"""Реестр форматтеров детальной телеметрии и карточек замера по правилам."""
from core.rule_report.details.contacts_long import (
    _detail_contacts_long,
    contacts_long_metrics,
)
from core.rule_report.details.contacts_short import (
    _detail_contacts_short,
    contacts_short_metrics,
)
from core.rule_report.details.glass import (
    glass_metrics,
    glass_on_contacts_metrics,
)
from core.rule_report.details.omission import _detail_omission, omission_metrics
from core.rule_report.details.platform_overlap import (
    _detail_platform_overlap,
    platform_contacts_overlap_metrics,
)
from core.rule_report.details.sinks import sinks_metrics
from core.rule_report.details.top_contacts import (
    _detail_top_contacts,
    top_contacts_metrics,
)
from core.rule_report.details.top_platform import (
    _detail_top_platform,
    top_platform_metrics,
)
from core.rule_report.details.window_geometry import (
    _detail_window_geometry,
    window_geometry_metrics,
)
from core.rule_report.details.window_sinks import window_sinks_metrics


_DETAIL_FORMATTERS = {
    "window_geometry": _detail_window_geometry,
    "contacts_long": _detail_contacts_long,
    "contacts_short": _detail_contacts_short,
    "top_contacts": _detail_top_contacts,
    "top_platform": _detail_top_platform,
    "platform_contacts_overlap": _detail_platform_overlap,
    "long_omission": _detail_omission,
    "short_omission": _detail_omission,
}

ROLE_METRIC_BUILDERS = {
    "long_omission": omission_metrics,
    "short_omission": omission_metrics,
    "contacts_long": contacts_long_metrics,
    "contacts_short": contacts_short_metrics,
    "top_contacts": top_contacts_metrics,
    "top_platform": top_platform_metrics,
    "platform_contacts_overlap": platform_contacts_overlap_metrics,
    "window_geometry": window_geometry_metrics,
    "window_sinks": window_sinks_metrics,
    "sinks": sinks_metrics,
    "glass": glass_metrics,
    "glass_on_contacts": glass_on_contacts_metrics,
}
