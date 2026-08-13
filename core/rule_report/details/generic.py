"""Общие строки сработавших ролей для правил без собственного форматера.

Правила ``window_sinks``, ``sinks``, ``glass`` и ``glass_on_contacts``
формируют причины по-своему — для каждого есть отдельный сборщик. Прочие
правила получают простое описание ``reason``.
"""


def _window_sinks_failures(reason, role_details: dict) -> list:
    """Причины срабатывания правила ``window_sinks``."""
    if reason and str(reason).startswith("invalid_window_reference_count"):
        return [
            "нет семи mask окон: "
            f"{int(role_details.get('selected_windows') or 0)}/7"
        ]
    if reason == "invalid_window_masks":
        return [
            "нет segmentation mask окна: "
            + ", ".join(
                f"#{index}"
                for index in role_details.get(
                    "invalid_window_indices", []
                )
            )
        ]
    if reason == "invalid_sink_masks":
        return [
            "нет segmentation mask раковины: "
            + ", ".join(
                f"#{index}"
                for index in role_details.get(
                    "invalid_sink_indices", []
                )
            )
        ]
    if not reason:
        threshold = int(role_details.get("overlap_min_px") or 0)
        return [
            f"раковина #{hit.get('sink_index')} -> "
            f"окно #{hit.get('window_index')}: "
            f"overlap {hit.get('overlap_px')} px "
            f">= {threshold} px"
            for hit in role_details.get("hits") or []

        ]
    return []


def _sinks_failures(reason, role_details: dict) -> list:
    """Причины срабатывания правила ``sinks``."""
    if reason == "invalid_sink_masks":
        return [
            "нет segmentation mask shell: "
            + ", ".join(
                f"#{index}"
                for index in role_details.get(
                    "invalid_sink_indices", []
                )
            )
        ]
    if reason == "invalid_case_central_reference":
        return [
            "case_central reference: "
            f"{int(role_details.get('case_central_found') or 0)}/1"
        ]
    if reason == "no_valid_platform":
        return ["нет valid platform mask"]
    if reason == "invalid_platform_bbox":
        return ["нет valid platform bbox"]
    if reason == "insufficient_valid_contacts":
        return [
            "valid contact masks: "
            f"{int(role_details.get('valid_contacts') or 0)}/14"
        ]
    if reason == "invalid_contact_layout":
        counts = role_details.get("contact_group_counts") or {}
        return [
            "contact layout: "
            + ", ".join(
                f"{group}={int(counts.get(group) or 0)}/{expected}"
                for group, expected in (
                    ("L", 5), ("R", 5),
                    ("T", 2), ("B", 2),
                )
            )
        ]
    if not reason:
        return [
            f"shell #{hit.get('sink_index')}: forbidden "
            f"{hit.get('forbidden_pixels')} px; "
            f"central {hit.get('central_overlap_px')} px; "
            f"platform {hit.get('platform_overlap_px')} px; "


            f"contacts {hit.get('contacts_overlap_px')} px"
            for hit in role_details.get("hits") or []
        ]
    return []


def _glass_failures(_reason, role_details: dict) -> list:
    """Причины срабатывания правила ``glass`` (все пересечения стекла)."""
    return [
        f"glass #{hit.get('glass_index')} -> ЗАЧИСТКА: "

        f"platform {hit.get('platform_overlap_px')} px; "
        f"pin {hit.get('pin_overlap_px')} px; "
        f"ring {hit.get('ring_overlap_px')} px; "
        f"union {hit.get('cleanup_overlap_px')} px"
        for hit in role_details.get("hits") or []
    ]


def _glass_on_contacts_failures(reason, role_details: dict) -> list:
    """Причины срабатывания правила ``glass_on_contacts``."""
    if reason == "missing_glass_mask":
        return [
            "нет segmentation mask glass: "
            + ", ".join(
                f"#{index}"
                for index in role_details.get(
                    "invalid_glass_indices", []
                )
            )
        ]
    if reason == "no_valid_platform":
        return ["нет valid platform mask"]
    if reason == "invalid_platform_bbox":
        return ["нет valid platform bbox"]
    if reason == "insufficient_valid_contacts":
        return [
            "valid contact masks: "
            f"{int(role_details.get('valid_contacts') or 0)}/14"
        ]
    if reason == "invalid_contact_layout":
        counts = role_details.get("contact_group_counts") or {}
        return [
            "contact layout: "
            + ", ".join(
                f"{group}={int(counts.get(group) or 0)}/{expected}"
                for group, expected in (
                    ("L", 5), ("R", 5),
                    ("T", 2), ("B", 2),
                )
            )
        ]
    if reason and str(reason).startswith("wrong_pin_count"):
        return [f"pins: {int(role_details.get('pins_found') or 0)}/14"]
    if reason == "missing_pin_mask":
        return [
            "нет pin mask: "
            + ", ".join(
                f"#{index}"
                for index in role_details.get(
                    "invalid_pin_indices", []
                )
            )
        ]
    if reason and str(reason).startswith("invalid_case_count"):
        return [f"case: {int(role_details.get('case_found') or 0)}/1"]
    if reason and str(reason).startswith("invalid_case_central_count"):
        return [
            "case_central: "
            f"{int(role_details.get('case_central_found') or 0)}/1"
        ]
    if reason == "case_central_not_inside_case":
        return ["invalid case ring"]
    if reason == "empty_case_ring":
        return ["empty case ring"]

    if not reason:
        return [
            f"glass #{pair.get('glass_index')} -> "
            f"contact #{pair.get('contact_index')}: "
            f"overlap {pair.get('overlap_pixels')} px -> БРАК"
            for pair in role_details.get("pairs") or []

        ]
    return []


_GENERIC_RULE_BUILDERS = {
    "window_sinks": _window_sinks_failures,
    "sinks": _sinks_failures,
    "glass": _glass_failures,
    "glass_on_contacts": _glass_on_contacts_failures,
}


def _generic_failure_rows(rule_name: str, per_role: dict) -> list:
    """Строки сработавших ролей для правил без собственного форматтера.

    Для правил со своим сборщиком причин (``_GENERIC_RULE_BUILDERS``)
    вызывается он; остальные получают простое описание ``reason``.
    """
    failure_rows = []
    for role, role_details in per_role.items():
        if (
            not isinstance(role_details, dict)
            or not role_details.get("triggered")
        ):
            continue
        reason = role_details.get("reason")
        builder = _GENERIC_RULE_BUILDERS.get(rule_name)
        if builder is not None:
            failures = builder(reason, role_details)
        elif reason:
            failures = [str(reason)]
        else:
            failures = []
        if failures:
            failure_rows.append(f"{role}: " + "; ".join(failures))
    return failure_rows
