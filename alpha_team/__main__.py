"""Lancement : python -m alpha_team"""

import logging
import socket

import uvicorn

from .config import load_settings
from .server import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    print("\n=== Équipe Alpha ===")
    print(f"Sur ce Mac       : http://localhost:{settings.port}")
    print(f"Sur le téléphone : http://{socket.gethostname()}:{settings.port} (via Tailscale)")
    print(f"Jeton d'accès    : {settings.token}")
    print(f"Modèle par défaut: {settings.default_model}\n")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                log_level="warning")


if __name__ == "__main__":
    main()
