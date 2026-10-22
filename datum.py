"""Catena di trasformazioni geografiche ETRF2000 <-> ETRF89 <-> ROMA40 <-> ED50 con i grigliati IGM,
e proiezioni UTM / Gauss-Boaga. Longitudini sempre da Greenwich (gradi decimali)."""
import math

from .tmerc import TMerc

CHAIN = ["E2K", "E89", "R40", "E50"]
NAMES = {"E2K": "ETRF2000", "E89": "ETRF89", "R40": "ROMA40", "E50": "ED50"}
MONTE_MARIO = 12.0 + 27.0 / 60.0 + 8.4 / 3600.0  # lon Monte Mario - lon Greenwich del suo meridiano


class OutsideGrid(Exception):
    pass


def _need(v):
    if v is None:
        raise OutsideGrid()
    return v


def _step(F, a, b, lat, lon, h):
    """Un passo della catena, da a a b (adiacenti). Ritorna (lat, lon, h)."""
    ia, ib = CHAIN.index(a), CHAIN.index(b)
    forward = ib > ia
    lo = min(ia, ib)
    pair = (CHAIN[lo], CHAIN[lo + 1])
    if pair == ("E2K", "E89"):
        # E2K = E89 + s ; posizione: coordinate E2K (iterazione per l'inverso)
        if forward:
            s = _need(F.shift_etrf2000_etrf89(lat, lon))
            return lat - s[0] / 3600.0, lon - s[1] / 3600.0, h - s[2]
        p, q = lat, lon
        for _ in range(3):
            s = _need(F.shift_etrf2000_etrf89(p, q))
            p, q = lat + s[0] / 3600.0, lon + s[1] / 3600.0
        return p, q, h + s[2]
    if pair == ("E89", "R40"):
        # E89 = R40 + s ; posizione: coordinate ROMA40
        if forward:  # E89 -> R40
            p, q = lat, lon
            for _ in range(3):
                s = _need(F.shift_etrf89_roma40(p, q))
                p, q = lat - s[0] / 3600.0, lon - s[1] / 3600.0
            return p, q, h
        s = _need(F.shift_etrf89_roma40(lat, lon))  # R40 -> E89
        return lat + s[0] / 3600.0, lon + s[1] / 3600.0, h
    # ("R40", "E50"): ED50 = ROMA40 + s ; posizione: coordinate ROMA40
    if forward:  # R40 -> E50
        s = _need(F.shift_ed50_roma40(lat, lon))
        return lat + s[0] / 3600.0, lon + s[1] / 3600.0, h
    p, q = lat, lon  # E50 -> R40
    for _ in range(3):
        s = _need(F.shift_ed50_roma40(p, q))
        p, q = lat - s[0] / 3600.0, lon - s[1] / 3600.0
    return p, q, h


def geo_convert(F, src, dst, lat, lon, h=0.0):
    """Converte coordinate geografiche (e quota ellissoidica) tra due sistemi con i grigliati.
    Solleva OutsideGrid se un punto non e' coperto."""
    i, j = CHAIN.index(src), CHAIN.index(dst)
    step = 1 if j > i else -1
    k = i
    while k != j:
        lat, lon, h = _step(F, CHAIN[k], CHAIN[k + step], lat, lon, h)
        k += step
    return lat, lon, h


# ---------------------------------------------------------------- proiezioni
def projection(system, kind, zone):
    """TMerc per il sistema ('E2K','E89','E50','R40') e il fuso.
    kind: 'UTM' (zone 32/33/34) o 'GB' (zone 'W'/'E')."""
    if kind == "GB":
        return TMerc("INTL", 9 if zone == "W" else 15, 0.9996, 1500000.0 if zone == "W" else 2520000.0)
    ell = "INTL" if system == "E50" else "GRS80"
    return TMerc(ell, 6 * int(zone) - 183, 0.9996, 500000.0)


def plane_kind(system):
    return "GB" if system == "R40" else "UTM"


def auto_zone(system, lon):
    if plane_kind(system) == "GB":
        return "W" if lon < 12.0 else "E"
    return min(34, max(32, int(math.floor((lon + 180.0) / 6.0)) + 1))


def geo_to_plane(system, lat, lon, zone="auto"):
    z = auto_zone(system, lon) if zone == "auto" else zone
    e, n = projection(system, plane_kind(system), z).forward(lat, lon)
    return e, n, z


def plane_to_geo(system, east, north, zone="auto"):
    """Con fuso 'auto' prova i fusi disponibili e prende quello coerente con la longitudine."""
    zs = [zone] if zone != "auto" else (["W", "E"] if plane_kind(system) == "GB" else [32, 33, 34])
    best = None
    for z in zs:
        lat, lon = projection(system, plane_kind(system), z).inverse(east, north)
        if zone != "auto" or auto_zone(system, lon) == z:
            return lat, lon, z
        best = best or (lat, lon, z)
    return best


def epsg_geographic(system, monte_mario=False):
    return {"E2K": "EPSG:6706", "E89": "EPSG:4258", "E50": "EPSG:4230",
            "R40": "EPSG:4806" if monte_mario else "EPSG:4265"}[system]


def epsg_plane(system, zone):
    if system == "R40":
        return "EPSG:3003" if zone == "W" else "EPSG:3004"
    base = {"E2K": 6704, "E89": 25800, "E50": 23000}[system]
    if system == "E2K":
        return "EPSG:%d" % (6704 + (int(zone) - 32 + 3))  # 6707, 6708, 6709
    return "EPSG:%d" % (base + int(zone))


def to_geographic(si, x, y):
    """Coordinate di partenza (dict si) -> (lat, lon) geografiche Greenwich."""
    if si["kind"] == "plane":
        lat, lon, _ = plane_to_geo(si["sys"], x, y, si["zone"])
        return lat, lon
    lat, lon = y, x
    if si["sys"] == "R40" and si["mm"]:
        lon += MONTE_MARIO
    return lat, lon


def from_geographic(so, lat, lon):
    """(lat, lon) Greenwich nel sistema di arrivo -> (X, Y, fuso)."""
    if so["kind"] == "plane":
        return geo_to_plane(so["sys"], lat, lon, so["zone"])
    if so["sys"] == "R40" and so["mm"]:
        lon -= MONTE_MARIO
    return lon, lat, None


def convert_point(F, si, so, h_in, h_out, x, y, z, has_z=True, approx=None):
    """Converte un punto seguendo la logica altimetrica dei GK2/ConveRgo.

    Punto fondamentale per le quote:
      * il blocco GEOIDE ITALGEO2005 del GK2 e' riferito alla realizzazione
        ETRF89;
      * se l'input e' ETRF2000, la quota ellissoidica viene prima riportata
        in ETRF89 usando il componente dh del blocco ETRF89-ETRF2000;
      * N viene quindi interpolata nel blocco GEOIDE in ETRF89;
      * H = h_ETRF89 - N e h_ETRF89 = H + N;
      * solo dopo la conversione altimetrica la quota ellissoidica viene,
        se necessario, riportata dal sistema ETRF89 al sistema di output.

    Questo ordine e' quello che consente di riprodurre i risultati ConveRgo
    con i grigliati GK2.
    """
    src, dst = si["sys"], so["sys"]
    lat, lon = to_geographic(si, x, y)
    used = {"approx": False}

    def geo(a, b, la, lo, h=0.0):
        if a == b:
            return la, lo, h
        if F is None:
            raise OutsideGrid()
        try:
            return geo_convert(F, a, b, la, lo, h)
        except OutsideGrid:
            if approx is None:
                raise
            # Il modello approssimato e' ammesso solo per la componente
            # planimetrica. Non deve mai essere usato per inventare N o dh.
            used["approx"] = True
            p, q = approx(a, b, la, lo)
            return p, q, h

    # ---------------------- planimetria pura / quota invariata
    if h_in == "same" or h_out == "same":
        z_o = z if has_z else None
        lat_o, lon_o, _ = geo(src, dst, lat, lon, 0.0)
        xo, yo, zone = from_geographic(so, lat_o, lon_o)
        return xo, yo, z_o, None, zone, ("approx" if used["approx"] else "grigliati"), lat_o, lon_o

    if not has_z:
        raise OutsideGrid()

    # ---------------------- quota ellissoidica <-> ortometrica
    if h_in == h_out:
        # Nessuna trasformazione altimetrica: se la quota e' ellissoidica,
        # il dh del passaggio di datum va mantenuto.
        lat_o, lon_o, z_o = geo(src, dst, lat, lon, z)
        xo, yo, zone = from_geographic(so, lat_o, lon_o)
        return xo, yo, z_o, None, zone, ("approx" if used["approx"] else "grigliati"), lat_o, lon_o

    if F is None:
        raise OutsideGrid()

    # Con GK2 il geoide e' applicato in ETRF89. Portiamo quindi sempre il
    # punto (e, per le quote ellissoidiche, anche h) in ETRF89 prima di N.
    if h_in == "ell":
        lat89, lon89, h89 = geo(src, "E89", lat, lon, z)
    elif h_in == "ort":
        lat89, lon89, _ = geo(src, "E89", lat, lon, 0.0)
        h89 = None
    else:
        raise OutsideGrid()

    n = F.value(lon89, lat89)
    if n is None:
        # Non esiste un grigliato GEOIDE valido in ETRF89: mai usare un valore
        # approssimato per la quota.
        return None

    if h_in == "ell" and h_out == "ort":
        # h_E89 = H + N
        H = h89 - n
        z_o = H
    elif h_in == "ort" and h_out == "ell":
        # H = h_E89 - N
        h89 = z + n
        lat_o, lon_o, z_o = geo("E89", dst, lat89, lon89, h89)
        xo, yo, zone = from_geographic(so, lat_o, lon_o)
        return xo, yo, z_o, n, zone, ("approx" if used["approx"] else "grigliati"), lat_o, lon_o
    else:
        raise OutsideGrid()

    # Da H ortometrica a un'altra quota ortometrica non serve alcuna
    # trasformazione verticale: la quota resta H anche cambiando datum.
    lat_o, lon_o, _ = geo(src, dst, lat, lon, 0.0)
    xo, yo, zone = from_geographic(so, lat_o, lon_o)
    return xo, yo, z_o, n, zone, ("approx" if used["approx"] else "grigliati"), lat_o, lon_o
