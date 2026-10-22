"""Lettore dei grigliati IGM GK2/GR2 (fogli 50K).

Il file GK2 contiene, tra gli altri, il blocco GEOIDE (ITALGEO2005) e le
trasformazioni planimetriche ETRF89<->ROMA40, ED50<->ROMA40 e
ETRF89<->ETRF2000.

Per il blocco GEOIDE i valori sono memorizzati dal NORD-EST: la prima riga e'
il bordo nord e la prima colonna il bordo est. Per usare coordinate
geografiche con origine SUD-OVEST, la matrice viene quindi ribaltata sulle
righe. L'interpolazione e' bilineare, come richiesto per l'uso del grigliato.
"""

import os
import re

import numpy as np


GEOID_ROWS = 10
GEOID_COLS = 14
GEOID_STEP_LAT = 2.0 / 60.0
GEOID_STEP_LON = 2.0 / 60.0

SHIFT_ROWS = 6
SHIFT_COLS = 6
SHIFT_STEP_LAT = 5.0 / 60.0
SHIFT_STEP_LON = 7.5 / 60.0


class GK2ParseError(ValueError):
    """Errore durante il parsing di un file GK2."""


def parse_gk2(path):
    """Parsa un GK2 in blocchi, preservando l'ordine dei valori numerici."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        txt = fh.read()

    toks = re.findall(
        r'"[^"]*"|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?',
        txt
    )

    blocks = []
    cur = None

    for tok in toks:
        if tok.startswith('"'):
            hdr = tok[1:-1]

            # Ogni nuovo token testuale apre un nuovo blocco se il precedente
            # aveva gia' ricevuto numeri; i primi due token sono parte
            # dell'header.
            if cur is None:
                cur = {"hdr": [], "nums": []}
                blocks.append(cur)
            elif cur["nums"]:
                cur = {"hdr": [], "nums": []}
                blocks.append(cur)

            cur["hdr"].append(hdr)

        elif cur is not None:
            cur["nums"].append(float(tok))

    return blocks


def _block(blocks, name):
    """Restituisce il primo blocco che contiene il nome richiesto."""
    for block in blocks:
        if name in block["hdr"]:
            return block

    return None


class ShiftGrid:
    """Griglia per le trasformazioni planimetriche."""

    def __init__(self, arrays, lat0, lon0):
        self.arrs = [
            np.asarray(array, dtype="float64").reshape(
                SHIFT_ROWS, SHIFT_COLS
            )
            for array in arrays
        ]

        if not self.arrs:
            raise GK2ParseError(
                "Numero di componenti griglia non valido"
            )

        self.lat0 = float(lat0)
        self.lon0 = float(lon0)

        self.lat_max = (
            self.lat0 + (SHIFT_ROWS - 1) * SHIFT_STEP_LAT
        )
        self.lon_max = (
            self.lon0 + (SHIFT_COLS - 1) * SHIFT_STEP_LON
        )

    def contains(self, lat, lon):
        """Verifica se il punto ricade nella griglia."""
        return (
            self.lat0 <= lat <= self.lat_max
            and self.lon0 <= lon <= self.lon_max
        )

    def margin(self, lat, lon):
        """Restituisce la distanza minima dal bordo della griglia."""
        return min(
            (lat - self.lat0) / SHIFT_STEP_LAT,
            (self.lat_max - lat) / SHIFT_STEP_LAT,
            (lon - self.lon0) / SHIFT_STEP_LON,
            (self.lon_max - lon) / SHIFT_STEP_LON
        )

    def values(self, lat, lon):
        """Interpolazione bilineare dei valori della griglia."""
        row = (lat - self.lat0) / SHIFT_STEP_LAT
        col = (lon - self.lon0) / SHIFT_STEP_LON

        row0 = min(
            max(int(np.floor(row)), 0),
            SHIFT_ROWS - 2
        )
        col0 = min(
            max(int(np.floor(col)), 0),
            SHIFT_COLS - 2
        )

        frac_row = row - row0
        frac_col = col - col0

        out = []

        for array in self.arrs:
            value = (
                array[row0, col0]
                * (1 - frac_col)
                * (1 - frac_row)
                + array[row0, col0 + 1]
                * frac_col
                * (1 - frac_row)
                + array[row0 + 1, col0]
                * (1 - frac_col)
                * frac_row
                + array[row0 + 1, col0 + 1]
                * frac_col
                * frac_row
            )

            out.append(float(value))

        return tuple(out)


class GK2Sheet:
    """Singolo foglio GK2."""

    def __init__(self, path):
        self.path = path

        blocks = parse_gk2(path)

        geo = _block(blocks, "GEOIDE")

        if geo is None:
            raise GK2ParseError(
                "Blocco GEOIDE non trovato"
            )

        # ---------------------------------------------------------
        # GRIGLIE PLANIMETRICHE
        # ---------------------------------------------------------

        self.shift_ed50 = None
        self.shift_e89r40 = None
        self.shift_e2k = None

        block = _block(blocks, "ETRF89-ROMA40")

        if block is not None and len(block["nums"]) >= 74:
            values = block["nums"]

            lat0 = values[72]
            lon0 = values[73]

            self.shift_e89r40 = ShiftGrid(
                [values[:36], values[36:72]],
                lat0,
                lon0
            )

            ed50 = _block(blocks, "ED50-ROMA40")

            if ed50 is not None and len(ed50["nums"]) >= 72:
                ed_values = ed50["nums"]

                # Il blocco ED50-ROMA40 usa la stessa origine della
                # griglia ETRF89-ROMA40, come specificato dal formato GK2.
                self.shift_ed50 = ShiftGrid(
                    [ed_values[:36], ed_values[36:72]],
                    lat0,
                    lon0
                )

        block = _block(blocks, "ETRF89-ETRF2000")

        if block is not None and len(block["nums"]) >= 110:
            values = block["nums"]

            self.shift_e2k = ShiftGrid(
                [
                    values[:36],
                    values[36:72],
                    values[72:108]
                ],
                values[108],
                values[109]
            )

        # ---------------------------------------------------------
        # GEOIDE / ITALGEO2005
        # ---------------------------------------------------------

        values = geo["nums"]

        expected = GEOID_ROWS * GEOID_COLS + 4

        if len(values) < expected:
            raise GK2ParseError(
                "Blocco GEOIDE incompleto: %d numeri, "
                "attesi almeno %d"
                % (len(values), expected)
            )

        grid_size = GEOID_ROWS * GEOID_COLS

        # I 4 valori finali sono origine SW (lat, lon)
        # e due valori di servizio.
        self.lat0 = float(values[grid_size])
        self.lon0 = float(values[grid_size + 1])

        raw = np.asarray(
            values[:grid_size],
            dtype="float64"
        ).reshape(
            GEOID_ROWS,
            GEOID_COLS
        )

        # Nel blocco GEOIDE i valori sono ordinati da Nord a Sud
        # per righe, mentre le colonne crescono da Ovest a Est.
        #
        # Il ribaltamento delle righe porta quindi la prima riga
        # della matrice all'origine Sud.
        self.arr = raw[::-1, :]

        self.rows = GEOID_ROWS
        self.cols = GEOID_COLS

        self.step_lat = GEOID_STEP_LAT
        self.step_lon = GEOID_STEP_LON

        self.lat_max = (
            self.lat0
            + (self.rows - 1) * self.step_lat
        )

        self.lon_max = (
            self.lon0
            + (self.cols - 1) * self.step_lon
        )

        self.name = os.path.basename(path)

    def contains(self, lon, lat):
        """Verifica se il punto ricade nel foglio GK2."""
        eps = 1e-10

        return (
            self.lon0 - eps <= lon <= self.lon_max + eps
            and self.lat0 - eps <= lat <= self.lat_max + eps
        )

    def margin(self, lon, lat):
        """Restituisce la distanza minima dal bordo."""
        return min(
            lon - self.lon0,
            self.lon_max - lon,
            lat - self.lat0,
            self.lat_max - lat
        )

    def value(self, lon, lat):
        """Restituisce l'ondulazione N interpolata bilinearmente in metri."""
        if not self.contains(lon, lat):
            return None

        col = (lon - self.lon0) / self.step_lon
        row = (lat - self.lat0) / self.step_lat

        col0 = min(
            max(int(np.floor(col)), 0),
            self.cols - 2
        )

        row0 = min(
            max(int(np.floor(row)), 0),
            self.rows - 2
        )

        frac_col = col - col0
        frac_row = row - row0

        a00 = self.arr[row0, col0]
        a10 = self.arr[row0, col0 + 1]
        a01 = self.arr[row0 + 1, col0]
        a11 = self.arr[row0 + 1, col0 + 1]

        return float(
            a00 * (1 - frac_col) * (1 - frac_row)
            + a10 * frac_col * (1 - frac_row)
            + a01 * (1 - frac_col) * frac_row
            + a11 * frac_col * frac_row
        )


class GK2Folder:
    """Collezione di GK2.

    Il foglio viene scelto automaticamente in base al punto.
    """

    def __init__(self, folder):
        self.folder = folder
        self.sheets = []

        for name in sorted(
            os.listdir(folder),
            key=str.lower
        ):
            extension = os.path.splitext(name)[1].lower()

            if extension not in (".gk2", ".gr2"):
                continue

            path = os.path.join(folder, name)

            try:
                sheet = GK2Sheet(path)
            except (GK2ParseError, OSError, UnicodeError):
                # Un file GK2 non valido o non leggibile viene ignorato.
                # Gli altri grigliati continuano a essere caricati.
                continue

            self.sheets.append(sheet)

        if not self.sheets:
            raise GK2ParseError(
                "Nessun file .GK2/.GR2 valido in %s"
                % folder
            )

        self._crs = None

    @property
    def crs(self):
        """Restituisce il CRS geografico ETRF89."""
        if self._crs is None:
            from qgis.core import QgsCoordinateReferenceSystem

            self._crs = QgsCoordinateReferenceSystem(
                "EPSG:4258"
            )

        return self._crs

    def _best(self, attr, lat, lon):
        """Trova la griglia più adatta al punto."""
        candidates = []

        for sheet in self.sheets:
            grid = getattr(sheet, attr)

            if grid is not None and grid.contains(lat, lon):
                candidates.append(
                    (
                        grid.margin(lat, lon),
                        sheet,
                        grid
                    )
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: item[0],
            reverse=True
        )

        return candidates[0][2]

    def shift_ed50_roma40(self, lat, lon):
        """Restituisce i parametri ED50 -> ROMA40."""
        grid = self._best(
            "shift_ed50",
            lat,
            lon
        )

        return (
            grid.values(lat, lon)
            if grid is not None
            else None
        )

    def shift_etrf89_roma40(self, lat, lon):
        """Restituisce i parametri ETRF89 -> ROMA40."""
        grid = self._best(
            "shift_e89r40",
            lat,
            lon
        )

        return (
            grid.values(lat, lon)
            if grid is not None
            else None
        )

    def shift_etrf2000_etrf89(self, lat, lon):
        """Restituisce i parametri ETRF2000 -> ETRF89."""
        grid = self._best(
            "shift_e2k",
            lat,
            lon
        )

        return (
            grid.values(lat, lon)
            if grid is not None
            else None
        )

    def value(self, lon, lat, return_sheet=False):
        """Restituisce l'ondulazione del geoide.

        Se return_sheet=True restituisce una tupla:
            (valore, nome_foglio)

        Se nessun foglio copre il punto restituisce None oppure:
            (None, None)
        """

        candidates = [
            sheet
            for sheet in self.sheets
            if sheet.contains(lon, lat)
        ]

        if not candidates:
            return (
                (None, None)
                if return_sheet
                else None
            )

        # In caso di sovrapposizione scegli il foglio nel cui interno
        # il punto e' piu' lontano dai bordi.
        #
        # Per i GK2 sovrapposti i valori coincidono entro la precisione
        # del grigliato.
        sheet = max(
            candidates,
            key=lambda item: item.margin(lon, lat)
        )

        value = sheet.value(lon, lat)

        return (
            (value, sheet.name)
            if return_sheet
            else value
        )