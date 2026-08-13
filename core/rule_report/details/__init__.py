"""Реестр форматтеров детальной телеметрии по правилам."""
from core.rule_report.details.contacts_long import _detail_contacts_long
from core.rule_report.details.contacts_short import _detail_contacts_short
from core.rule_report.details.omission import _detail_omission
from core.rule_report.details.platform_overlap import _detail_platform_overlap
from core.rule_report.details.top_contacts import _detail_top_contacts
from core.rule_report.details.top_platform import _detail_top_platform
from core.rule_report.details.window_geometry import _detail_window_geometry



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
