"""Cliente HTTP "educado": respeta robots.txt, limita la velocidad y se identifica.

Reglas:
- Nunca más de una solicitud cada `seg_entre_solicitudes` segundos.
- User-Agent honesto con correo de contacto del operador.
- Verifica robots.txt en cada corrida antes de tocar cualquier URL.
- Reintentos con espera exponencial ante errores 5xx o de red.
"""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

BASE = "https://www.avisosdeocasion.com"


class ClienteEducado:
    def __init__(self, contacto: str, seg_entre_solicitudes: float = 1.0,
                 max_reintentos: int = 3, timeout: int = 30):
        self.intervalo = max(0.5, float(seg_entre_solicitudes))
        self.max_reintentos = max_reintentos
        self.timeout = timeout
        self._ultima = 0.0
        self.sesion = requests.Session()
        self.sesion.headers.update({
            "User-Agent": f"InvestigacionInmobiliariaPersonal/1.0 (uso personal; contacto: {contacto})",
            "Accept-Language": "es-MX,es;q=0.9",
            "Cache-Control": "no-cache",
        })
        self._robots = urllib.robotparser.RobotFileParser()
        self._robots_cargado = False

    # ---------------- robots.txt ----------------
    def cargar_robots(self) -> None:
        """Lee robots.txt del sitio. Si no se puede leer, asumimos lo más restrictivo razonable."""
        url = f"{BASE}/robots.txt"
        try:
            r = self.sesion.get(url, timeout=self.timeout)
            if r.status_code == 200:
                self._robots.parse(r.text.splitlines())
            else:
                # Sin robots.txt accesible: el estándar permite rastrear, pero registramos.
                self._robots.parse([])
            self._robots_cargado = True
        except requests.RequestException:
            # Si ni robots.txt responde, mejor no rastrear nada hoy.
            raise RuntimeError("No se pudo leer robots.txt; se aborta la corrida por precaución.")

    def permitido(self, url: str) -> bool:
        if not self._robots_cargado:
            self.cargar_robots()
        return self._robots.can_fetch(self.sesion.headers["User-Agent"], url)

    # ---------------- GET con cortesía ----------------
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
                return r
            except (requests.RequestException, requests.HTTPError) as e:
                ultimo_error = e
                time.sleep(2 ** intento)  # 2s, 4s, 8s
        raise RuntimeError(f"Fallaron {self.max_reintentos} intentos para {url}: {ultimo_error}")
