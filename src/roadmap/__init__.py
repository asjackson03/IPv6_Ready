"""Módulo 3 — Generación de hoja de ruta de migración IPv6.

Módulo 3a (parser de configuración + chat guiado) ya disponible: expone la
guía de comandos por fabricante, el pre-filtrado determinista, el cliente del
LLM local y la sesión conversacional de levantamiento.
"""
from .command_guide import CommandGuide
from .config_prefilter import ConfigPrefilter
from .ollama_client import OllamaClient
from .topology_session import TopologySession

__all__ = [
    "CommandGuide",
    "ConfigPrefilter",
    "OllamaClient",
    "TopologySession",
]
