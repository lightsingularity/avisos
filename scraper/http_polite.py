"""Cliente HTTP que respeta robots.txt, limita la velocidad y (Camino B) se
presenta como un navegador para intentar pasar el filtro CloudFront del sitio.
"""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

BASE = "https://www.avisosdeocasion.com"

# Encabezados de un Chrome reciente en Windows. Algunos filtros (WAF) bloquean
# peticiones que no parecen de un navegador; esto intenta evitarlo. Nota: no se
# incluye "br" en Accept-Encoding porque requests no lo descomprime por defecto.
HEADERS_NAVEGADOR = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class ClienteEducado:
    def __init__(self, contacto: str = "", seg_entre_solicitudes: float = 1.0,
                 max_reintentos: int = 3, timeout: int = 30):
        # `contacto` se conserva por compatibilidad; en modo navegador no se envía
        # (un encabezado de contacto delataría que no es un navegador real).
        self.contacto = contacto
        self.intervalo = max(0.5, float(seg_entre_solicitudes))
        self.max_reintentos = max_reintentos
        self.timeout = timeout
        self._ultima = 0.0
        self.sesion = requests.Session()
        self.sesion.headers.update(HEADERS_NAVEGADOR)
        self._robots = urllib.robotparser.RobotFileParser()
        self._robots_cargado = False

    def cargar_robots(self) -> None:
        url = f"{BASE}/robots.txt"
        try:
            r = self.sesion.get(url, timeout=self.timeout)
            if r.status_code == 200:
                self._robots.parse(r.text.splitlines())
            else:
                self._robots.parse([])
            self._robots_cargado = True
        except requests.RequestException:
            raise RuntimeError("No se pudo leer robots.txt; se aborta la corrida por precaución.")

    def permitido(self, url: str) -> bool:
        if not self._robots_cargado:
            self.cargar_robots()
        # robots.txt solo prohíbe /mex/ y /old para "*"; nuestras rutas están permitidas.
        return self._robots.can_fetch("*", url)

    def get(self, url: str) -> requests.Response:
        if urlparse(url).netloc.endswith("avisosdeocasion.com") and not self.permitido(url):
            raise PermissionError(f"robots.txt no permite: {url}")
        espera = self.intervalo - (time.monotonic() - self._ultima)
        if espera > 0:
            time.sleep(espera)
        ultimo_error: Exception | None = None
        for intento in range(1, self.max_reintentos + 1):
            try:
                self._ultima = time.monotonic()
                r = self.sesion.get(url, timeout=self.timeout)
                if r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                # El sitio sirve XML/HTML en UTF-8 pero SIN declarar charset, y
                # entonces requests asume Latin-1 (acentos rotos y BOM "ï»¿").
                ctype = r.headers.get("Content-Type", "").lower()
                if "charset=" not in ctype and any(t in ctype for t in ("xml", "html", "text")):
                    r.encoding = "utf-8"
                return r
            except (requests.RequestException, requests.HTTPError) as e:
                ultimo_error = e
                time.sleep(2 ** intento)
        raise RuntimeError(f"Fallaron {self.max_reintentos} intentos para {url}: {ultimo_error}")