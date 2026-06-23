"""Configuración de empaquetado para IPv6 Ready Analyzer."""
from setuptools import setup, find_packages

setup(
    name="ipv6-ready-analyzer",
    version="0.1.0",
    description="Prototipo de diagnóstico automatizado de compatibilidad IPv6",
    author="Andrés Martín",
    packages=find_packages(include=["src", "src.*"]),
    python_requires=">=3.9",
    install_requires=[
        "python-nmap==0.7.1",
        "pysnmp==4.4.12",
        "pandas==2.2.0",
        "python-dotenv==1.0.0",
        "colorama==0.4.6",
        "tqdm==4.66.1",
        "tabulate==0.9.0",
    ],
    extras_require={
        "dev": ["pytest==7.4.4"],
    },
    entry_points={
        "console_scripts": [
            "ipv6-analyzer=main:main",
        ],
    },
)
