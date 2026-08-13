"""Совместимый вход к карточкам замера HMI.

Реализация живёт в :mod:`core.rule_report.cards` и билдерах
:mod:`core.rule_report.details`.
"""
from core.rule_report.cards import build_presence_summary, build_rule_summary

__all__ = ["build_presence_summary", "build_rule_summary"]
