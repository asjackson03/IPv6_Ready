"""Pruebas de CommandGuide (Módulo 3a) — conocimiento estático por fabricante."""
from src.roadmap.command_guide import CommandGuide


def test_get_command_suggestion_known_vendor():
    """Para 'cisco_ios' devuelve un comando sugerido no vacío y su patrón."""
    sugerencia = CommandGuide().get_command_suggestion("cisco_ios")

    assert sugerencia["comando_sugerido"].strip() != ""
    assert "running-config" in sugerencia["comando_sugerido"]
    assert sugerencia["patron_comentario"] == "!"


def test_get_command_suggestion_unknown_vendor():
    """Para un string aleatorio devuelve el fallback de 'desconocido'."""
    guide = CommandGuide()
    sugerencia = guide.get_command_suggestion("marca-inexistente-xyz")

    esperado = guide.get_command_suggestion("desconocido")
    assert sugerencia == esperado
    assert sugerencia["comando_sugerido"].strip() != ""
