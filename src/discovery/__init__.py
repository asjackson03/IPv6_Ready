"""Módulo 1 — Descubrimiento de red y evaluación IPv6.

Expone las tres clases principales del módulo de discovery.
"""
from .scanner import NetworkScanner
from .ipv6_checker import IPv6Checker
from .inventory import InventoryManager

__all__ = ["NetworkScanner", "IPv6Checker", "InventoryManager"]
