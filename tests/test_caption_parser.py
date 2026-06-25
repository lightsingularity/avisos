"""Clasificación de tipo/transacción a partir del título (caption_parser)."""
from scraper.caption_parser import clasificar_titulo


def test_titulo_canonico_lee_el_tipo_de_su_posicion():
    assert clasificar_titulo("Se vende casa en FRACC BUENOS AIRES") == ("venta", "casa")
    assert clasificar_titulo("Se renta departamento en TORRE WEST") == ("renta", "departamento")
    assert clasificar_titulo("Se vende terreno en SIERRA ALTA") == ("venta", "terreno")
    assert clasificar_titulo(
        "Venta de bodegas y naves industriales en REAL DE PALMAS") == ("venta", "bodega_nave")


def test_tipo_en_nombre_de_zona_no_voltea_la_clasificacion():
    # El nombre de la colonia/zona contiene una palabra de tipo: NO debe ganar.
    # (Antes "departamento" se detectaba por subcadena dentro de "LOS DEPARTAMENTOS".)
    assert clasificar_titulo("Se vende casa en LOS DEPARTAMENTOS") == ("venta", "casa")
    assert clasificar_titulo("Se renta casa en PRIVADA LOCALES") == ("renta", "casa")


def test_titulo_no_canonico_cae_a_subcadena():
    # Sin el formato "Se {trans} {tipo} en {zona}" se hace el mejor esfuerzo.
    assert clasificar_titulo("Casa remodelada, excelente precio")[1] == "casa"
    assert clasificar_titulo(None) == (None, None)
    assert clasificar_titulo("anuncio sin tipo ni transacción") == (None, None)
