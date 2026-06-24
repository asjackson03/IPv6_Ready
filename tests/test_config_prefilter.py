"""Pruebas de ConfigPrefilter (Módulo 3a) — filtrado determinista sin LLM."""
from src.roadmap.config_prefilter import ConfigPrefilter


def test_prefilter_removes_comments_cisco():
    """Las líneas que son puramente comentario Cisco ('!') se eliminan."""
    raw = (
        "!\n"
        "! Last configuration change\n"
        "interface GigabitEthernet0/0\n"
        "!\n"
    )
    filtrado = ConfigPrefilter().prefilter(raw, vendor="cisco_ios")

    assert "!" not in filtrado
    assert "interface GigabitEthernet0/0" in filtrado


def test_prefilter_keeps_relevant_keywords():
    """Líneas con palabras clave (interface, ipv6, router...) se conservan."""
    raw = (
        "interface Vlan10\n"
        "ipv6 address 2001:db8::1/64\n"
        "router bgp 65001\n"
        "banner motd ^C Bienvenido ^C\n"   # sin keyword ni IP → se descarta
        "logging buffered 4096\n"           # sin keyword ni IP → se descarta
    )
    filtrado = ConfigPrefilter().prefilter(raw, vendor="cisco_ios")

    assert "interface Vlan10" in filtrado
    assert "ipv6 address 2001:db8::1/64" in filtrado
    assert "router bgp 65001" in filtrado
    assert "banner motd" not in filtrado
    assert "logging buffered" not in filtrado


def test_prefilter_keeps_ip_addresses():
    """Líneas con una IP se conservan aunque no tengan keyword explícito."""
    raw = (
        "description enlace al core\n"      # sin keyword ni IP → descarta
        "  10.0.0.1 255.255.255.0\n"        # IPv4 sin keyword → conserva
        "  neighbor fe80::1 remote\n"       # IPv6 sin keyword → conserva
    )
    filtrado = ConfigPrefilter().prefilter(raw, vendor="cisco_ios")

    assert "10.0.0.1" in filtrado
    assert "fe80::1" in filtrado
    assert "description enlace al core" not in filtrado


def test_estimate_reduction_calculation():
    """El porcentaje de reducción se calcula con números conocidos."""
    prefilter = ConfigPrefilter()
    # 10 líneas originales, 4 filtradas → 60% de reducción.
    raw = "\n".join(f"linea {i}" for i in range(10))
    filtrado = "\n".join(f"linea {i}" for i in range(4))

    stats = prefilter.estimate_reduction(raw, filtrado)

    assert stats["lineas_originales"] == 10
    assert stats["lineas_filtradas"] == 4
    assert stats["porcentaje_reduccion"] == 60.0


def test_config_prefilter_has_meaningful_content_true():
    """Texto con keywords técnicas reales y longitud suficiente → True."""
    texto = (
        "interface GigabitEthernet0/0\n"
        "ipv6 address 2001:db8::1/64\n"
        "router bgp 65001\n"
    )
    assert ConfigPrefilter().has_meaningful_content(texto) is True


def test_config_prefilter_has_meaningful_content_false():
    """Texto corto sin keywords ni IPs (caso real del bug) → False."""
    texto = "es capa 2, no tiene componente capa 3"
    assert ConfigPrefilter().has_meaningful_content(texto) is False
