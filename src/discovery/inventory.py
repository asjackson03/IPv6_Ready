"""inventory.py — Construcción, persistencia y reporte del inventario.

Contiene :class:`InventoryManager`, que transforma la lista de dispositivos
evaluados en un :class:`pandas.DataFrame`, lo guarda en disco (JSON/CSV) e
imprime un resumen ejecutivo coloreado en consola.
"""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
from colorama import Fore, Style, init as colorama_init
from tabulate import tabulate

# Inicializa colorama (autoreset para no arrastrar colores entre prints).
colorama_init(autoreset=True)

# Orden preferido de columnas en el inventario.
COLUMN_ORDER = [
    "ip", "mac", "hostname", "device_type", "vendor",
    "os_detected", "os_version", "ipv6_address",
    "ipv6_score", "ipv6_status", "recomendacion_basica",
    "open_ports", "ttl", "snmp_available", "firmware_version",
    "source", "evaluated_at",
]

# Color asociado a cada estado para el resumen en consola.
STATUS_COLORS = {
    "COMPATIBLE": Fore.GREEN,
    "PARCIAL": Fore.CYAN,
    "REQUIERE_UPGRADE": Fore.YELLOW,
    "INCOMPATIBLE": Fore.RED,
}


class InventoryManager:
    """Gestiona el inventario de dispositivos evaluados."""

    def build_inventory(self, evaluated_devices: list) -> pd.DataFrame:
        """Construye un DataFrame ordenado por ``ipv6_score`` descendente.

        Args:
            evaluated_devices: lista de dispositivos ya evaluados.

        Returns:
            DataFrame con las columnas ordenadas y las filas ordenadas por
            puntaje descendente.
        """
        if not evaluated_devices:
            return pd.DataFrame(columns=COLUMN_ORDER)

        df = pd.DataFrame(evaluated_devices)

        # Garantiza la presencia de todas las columnas conocidas y su orden.
        ordered = [c for c in COLUMN_ORDER if c in df.columns]
        extra = [c for c in df.columns if c not in COLUMN_ORDER]
        df = df[ordered + extra]

        if "ipv6_score" in df.columns:
            df = df.sort_values("ipv6_score", ascending=False).reset_index(drop=True)
        return df

    def save_results(
        self,
        df: pd.DataFrame,
        output_dir: str,
        formats: list | None = None,
    ) -> list[str]:
        """Guarda el inventario en disco en los formatos solicitados.

        Args:
            df: inventario a persistir.
            output_dir: carpeta destino (se crea si no existe).
            formats: lista con ``'json'`` y/o ``'csv'`` (por defecto ambos).

        Returns:
            Lista de rutas de los archivos generados.
        """
        if formats is None:
            formats = ["json", "csv"]

        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"ipv6_scan_{timestamp}"
        saved_paths: list[str] = []

        if "json" in formats:
            json_path = os.path.join(output_dir, f"{base}.json")
            df.to_json(json_path, orient="records", indent=2, force_ascii=False)
            saved_paths.append(json_path)
            print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} JSON guardado en: {json_path}")

        if "csv" in formats:
            csv_path = os.path.join(output_dir, f"{base}.csv")
            df.to_csv(csv_path, index=False, encoding="utf-8")
            saved_paths.append(csv_path)
            print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} CSV guardado en: {csv_path}")

        return saved_paths

    def print_summary(self, df: pd.DataFrame, saved_paths: list | None = None) -> None:
        """Imprime un resumen ejecutivo coloreado del inventario.

        Args:
            df: inventario a resumir.
            saved_paths: rutas de los reportes generados (opcional). Si se
                proporcionan, se muestran como última línea del resumen.
        """
        print()
        print(f"{Style.BRIGHT}{'=' * 60}")
        print(f"{Style.BRIGHT}  RESUMEN DE COMPATIBILIDAD IPv6")
        print(f"{Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}")

        if df.empty:
            print(f"{Fore.YELLOW}No hay dispositivos para resumir.{Style.RESET_ALL}")
            return

        total = len(df)

        # --- Tabla por estado (cantidad y % del total) -------------------
        counts = df["ipv6_status"].value_counts()
        status_rows = []
        for status in ["COMPATIBLE", "PARCIAL", "REQUIERE_UPGRADE", "INCOMPATIBLE"]:
            cantidad = int(counts.get(status, 0))
            pct = (cantidad / total) * 100 if total else 0
            color = STATUS_COLORS.get(status, "")
            status_rows.append([
                f"{color}{status}{Style.RESET_ALL}",
                cantidad,
                f"{pct:.1f}%",
            ])
        print()
        print(tabulate(
            status_rows,
            headers=["Estado", "Dispositivos", "% del total"],
            tablefmt="rounded_outline",
        ))

        # --- Score promedio ----------------------------------------------
        promedio = df["ipv6_score"].mean()
        print()
        print(f"{Style.BRIGHT}Score IPv6 promedio:{Style.RESET_ALL} "
              f"{self._color_score(promedio)}{promedio:.1f}/100{Style.RESET_ALL}  "
              f"({total} dispositivos analizados)")

        # --- Top 3 más críticos (score más bajo) -------------------------
        criticos = df.nsmallest(3, "ipv6_score")
        critic_rows = [
            [
                row["ip"],
                row["hostname"],
                f"{self._color_score(row['ipv6_score'])}{int(row['ipv6_score'])}{Style.RESET_ALL}",
                f"{STATUS_COLORS.get(row['ipv6_status'], '')}{row['ipv6_status']}{Style.RESET_ALL}",
            ]
            for _, row in criticos.iterrows()
        ]
        print()
        print(f"{Style.BRIGHT}Top 3 dispositivos más críticos:{Style.RESET_ALL}")
        print(tabulate(
            critic_rows,
            headers=["IP", "Hostname", "Score", "Estado"],
            tablefmt="rounded_outline",
        ))

        # --- Línea final con la ubicación del reporte --------------------
        print()
        if saved_paths:
            for path in saved_paths:
                print(f"{Fore.GREEN}Reporte guardado en:{Style.RESET_ALL} {path}")
        print(f"{Style.BRIGHT}{'=' * 60}{Style.RESET_ALL}")

    @staticmethod
    def _color_score(score: float) -> str:
        """Devuelve un color según el rango del puntaje."""
        if score >= 80:
            return Fore.GREEN
        if score >= 50:
            return Fore.CYAN
        if score >= 20:
            return Fore.YELLOW
        return Fore.RED
