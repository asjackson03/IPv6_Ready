#!/usr/bin/env python3
"""main.py — Punto de entrada de IPv6 Ready Analyzer.

Orquesta el Módulo 1 (Discovery): descubre/carga dispositivos, evalúa su
compatibilidad IPv6, construye el inventario, lo guarda en disco y muestra
un resumen en consola.

Uso:
    python main.py --demo
    python main.py --target 192.168.1.0/24 --format json --verbose
"""
from __future__ import annotations

import argparse
import os
import sys

from colorama import Fore, Style, init as colorama_init
from dotenv import load_dotenv

from src import __version__
from src.discovery import NetworkScanner, IPv6Checker, InventoryManager
from src.classifier import ModelTrainer, DeviceClassifier

colorama_init(autoreset=True)

# Ruta por defecto al archivo de datos simulados.
MOCK_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "sample", "mock_devices.json",
)

# Ruta por defecto al dataset de entrenamiento del Módulo 2.
TRAINING_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "sample", "training_dataset.json",
)


def print_banner(classify: bool = False) -> None:
    """Imprime el banner de inicio del proyecto.

    Args:
        classify: si es True, indica que el Módulo 2 (clasificación ML)
            está activo en esta ejecución.
    """
    modulos = "Módulo 1: Discovery"
    if classify:
        modulos += "  +  Módulo 2: Classifier ML"
    banner = f"""{Fore.CYAN}{Style.BRIGHT}
 ___ ____            __     ____                _
|_ _|  _ \\__   __    / /_   |  _ \\ ___  __ _  __| |_   _
 | || |_) \\ \\ / /   | '_ \\  | |_) / _ \\/ _` |/ _` | | | |
 | ||  __/ \\ V /    | (_) | |  _ <  __/ (_| | (_| | |_| |
|___|_|     \\_/      \\___/  |_| \\_\\___|\\__,_|\\__,_|\\__, |
                                                   |___/
        A N A L Y Z E R   ·   IPv6 Ready Analyzer
{Style.RESET_ALL}{Fore.WHITE}  Prototipo de diagnóstico automatizado de compatibilidad IPv6
  Versión {__version__}  ·  {modulos}{Style.RESET_ALL}
"""
    print(banner)


def build_parser() -> argparse.ArgumentParser:
    """Define y devuelve el parser de argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        prog="ipv6-ready-analyzer",
        description="Diagnóstico automatizado de compatibilidad IPv6 en redes empresariales.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python main.py --demo\n"
            "  python main.py --target 192.168.1.0/24 --format json --verbose\n"
        ),
    )
    parser.add_argument(
        "--target",
        help="IP, CIDR o lista separada por comas a escanear (requerido salvo en --demo).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Usa datos simulados (mock_devices.json) sin escanear la red real.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Directorio de salida (por defecto data/raw/ o DEFAULT_OUTPUT_DIR del .env).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv", "both"],
        default="both",
        help="Formato de salida (por defecto: both).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Muestra información detallada durante la ejecución.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help=(
            "Usa argumentos nmap más ligeros ('-sV --version-intensity 2', "
            "sin -O) para acelerar el escaneo en redes grandes. Sacrifica la "
            "detección de sistema operativo a cambio de velocidad. "
            "Recomendado para rangos /22 o mayores."
        ),
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help=(
            "Entrena el clasificador ML (Módulo 2) con el dataset de "
            "entrenamiento antes de clasificar. Guarda el modelo y un "
            "reporte de entrenamiento en data/processed/."
        ),
    )
    parser.add_argument(
        "--classify",
        action="store_true",
        help=(
            "Activa el Módulo 2: clasifica cada dispositivo en LISTO/"
            "ACTUALIZABLE/REEMPLAZAR/EVALUAR con el modelo ML. Requiere un "
            "modelo entrenado (usa --train si aún no existe)."
        ),
    )
    parser.add_argument(
        "--topology",
        action="store_true",
        help=(
            "Modo de levantamiento conversacional (Módulo 3a). Flujo en "
            "terminal, SEPARADO de --demo/--target: guía al administrador para "
            "capturar y estructurar la configuración de los equipos de capa 3 "
            "y seguridad usando el LLM local (Ollama). Requiere el servicio "
            "Ollama corriendo."
        ),
    )
    return parser


def resolve_formats(fmt: str) -> list[str]:
    """Traduce el argumento --format a la lista esperada por InventoryManager."""
    return ["json", "csv"] if fmt == "both" else [fmt]


def run(args: argparse.Namespace) -> int:
    """Ejecuta el flujo completo del Módulo 1. Devuelve un código de salida."""
    load_dotenv()  # carga variables de .env si existe

    # Modo levantamiento conversacional (Módulo 3a): flujo completamente
    # separado del discovery/clasificación. Import perezoso para no exigir la
    # librería ollama cuando se usan los otros modos.
    if args.topology:
        from src.roadmap.topology_session import TopologySession
        TopologySession().run_interactive()
        return 0

    output_dir = args.output or os.getenv("DEFAULT_OUTPUT_DIR", "data/raw/")
    formats = resolve_formats(args.format)

    scanner = NetworkScanner(
        timeout=int(os.getenv("SCAN_TIMEOUT", "30")),
        verbose=args.verbose,
        fast=args.fast,
    )
    checker = IPv6Checker()
    inventory = InventoryManager()

    # 1) Obtener dispositivos -------------------------------------------------
    if args.demo:
        print(f"{Fore.CYAN}[MODO DEMO]{Style.RESET_ALL} Cargando datos simulados...")
        devices = scanner.load_mock_data(MOCK_DATA_PATH)
    else:
        if not args.target:
            print(
                f"{Fore.RED}[ERROR]{Style.RESET_ALL} En modo escaneo debes indicar "
                f"--target (IP o CIDR), o bien usar --demo.",
                file=sys.stderr,
            )
            return 2
        print(f"{Fore.CYAN}[MODO SCAN]{Style.RESET_ALL} Escaneando '{args.target}'...")
        devices = scanner.scan_network(args.target)

    if not devices:
        print(f"{Fore.YELLOW}[AVISO]{Style.RESET_ALL} No se obtuvieron dispositivos. "
              f"Finalizando.")
        return 0

    # 2) Evaluar compatibilidad IPv6 -----------------------------------------
    print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} Evaluando {len(devices)} dispositivo(s)...")
    try:
        from tqdm import tqdm
        iterator = tqdm(devices, desc="Evaluando IPv6", unit="disp.", disable=not sys.stdout.isatty())
    except ImportError:
        iterator = devices

    evaluated = [checker.evaluate_device(dev) for dev in iterator]

    # 3) Entrenar el modelo ML si se solicita (Módulo 2) ----------------------
    if args.train:
        print(f"{Fore.CYAN}[MÓDULO 2]{Style.RESET_ALL} Entrenando clasificador ML "
              f"con '{TRAINING_DATA_PATH}'...")
        trainer = ModelTrainer()
        metrics = trainer.train(TRAINING_DATA_PATH)
        report_path = os.path.join(trainer.model_dir, "training_report.txt")
        trainer.generate_training_report(metrics, output_path=report_path)
        print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} Modelo entrenado. "
              f"Accuracy en test: {metrics['accuracy'] * 100:.1f}%")
        print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} Reporte de entrenamiento: "
              f"{report_path}")

    # 4) Clasificar con el Módulo 2 si se solicita ----------------------------
    if args.classify:
        print(f"{Fore.CYAN}[MÓDULO 2]{Style.RESET_ALL} Clasificando dispositivos...")
        classifier = DeviceClassifier()
        evaluated = classifier.classify_batch(evaluated)

    # 5) Construir inventario -------------------------------------------------
    df = inventory.build_inventory(evaluated)

    # 6) Guardar resultados ---------------------------------------------------
    saved_paths = inventory.save_results(df, output_dir, formats=formats)

    # 7) Resumen en consola ---------------------------------------------------
    inventory.print_summary(df, saved_paths=saved_paths)
    inventory.print_quality_summary(df)
    if args.classify:
        inventory.print_ml_summary(df)

    return 0


def main() -> int:
    """Función principal: parsea argumentos, gestiona errores y Ctrl+C."""
    parser = build_parser()
    args = parser.parse_args()

    print_banner(classify=args.classify)

    try:
        return run(args)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[INTERRUMPIDO]{Style.RESET_ALL} "
              f"Ejecución cancelada por el usuario (Ctrl+C). Saliendo limpiamente.")
        return 130
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"\n{Fore.RED}[ERROR]{Style.RESET_ALL} {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
