from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLabel,
                                 QPushButton, QLineEdit, QGroupBox, QProgressBar, QApplication,
                                 QCheckBox, QWidget)
from qgis.PyQt.QtCore import QSettings
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox, QgsFileWidget
from qgis.core import (QgsVectorFileWriter, QgsMapLayerProxyModel, QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsField, QgsFields, Qgis, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform)
from . import datum as dt
from .grid_gk2 import GK2Folder

# --- compatibilita' QGIS 3 (Qt5) / QGIS 4 (Qt6): enum "scoped" e tipi di campo
try:
    from qgis.PyQt.QtCore import QMetaType
    _USE_METATYPE = Qgis.QGIS_VERSION_INT >= 33800
except ImportError:
    _USE_METATYPE = False
if _USE_METATYPE:
    T_DOUBLE, T_STRING = QMetaType.Type.Double, QMetaType.Type.QString
else:
    from qgis.PyQt.QtCore import QVariant
    T_DOUBLE, T_STRING = QVariant.Double, QVariant.String

ML = getattr(Qgis, "MessageLevel", Qgis)  # Qgis.MessageLevel.X (nuovo) oppure Qgis.X (vecchio)


def _enum(cls, scope, name):
    """cls.Scope.Name (Qt6 / QGIS 4) oppure cls.Name (Qt5 / QGIS 3)."""
    try:
        return getattr(getattr(cls, scope), name)
    except AttributeError:
        return getattr(cls, name)


try:
    VECTOR_FILTER = Qgis.LayerFilter.VectorLayer
except AttributeError:
    VECTOR_FILTER = QgsMapLayerProxyModel.VectorLayer
DIR_MODE = _enum(QgsFileWidget, "StorageMode", "GetDirectory")
SAVE_MODE = _enum(QgsFileWidget, "StorageMode", "SaveFile")

SETTINGS_KEY = "quote_converter/gk2_folder"
SYSTEM_ITEMS = [("ETRF2000", "E2K"), ("ETRF89", "E89"), ("ED50", "E50"), ("ROMA40", "R40")]
HEIGHT_ITEMS = [("Auto (ellissoidica per ETRF, geoidica per gli altri)", "auto"),
                ("Ellissoidica", "ell"), ("Geoidica (ortometrica)", "ort"), ("Non modificare", "same")]
APPROX_EPSG = {"E2K": "EPSG:4258", "E89": "EPSG:4258", "E50": "EPSG:4230", "R40": "EPSG:4265"}


class SystemBox(QGroupBox):
    """Impostazioni di un sistema (partenza o arrivo) come in ConveRgo."""

    def __init__(self, title, is_output=False, parent=None):
        super().__init__(title, parent)
        self.is_output = is_output
        f = QFormLayout(self)
        self.cmbSys = QComboBox()
        for t, k in SYSTEM_ITEMS:
            self.cmbSys.addItem(t, k)
        self.cmbKind = QComboBox()
        self.cmbKind.addItem("Geografiche (lat/lon, gradi decimali)", "geo")
        self.cmbKind.addItem("Piane (UTM / Gauss-Boaga)", "plane")
        self.cmbZone = QComboBox()
        self.cmbOrigin = QComboBox()
        self.cmbOrigin.addItem("Greenwich", False)
        self.cmbOrigin.addItem("Monte Mario", True)
        self.cmbH = QComboBox()
        for t, k in HEIGHT_ITEMS:
            self.cmbH.addItem(t, k)
        if is_output:
            self.cmbH.addItem("Stessa di input", "same")
        f.addRow("Sistema geodetico", self.cmbSys)
        f.addRow("Tipo di coordinate", self.cmbKind)
        self.lblZone = QLabel("Fuso")
        f.addRow(self.lblZone, self.cmbZone)
        self.lblOrigin = QLabel("Origine longitudini")
        f.addRow(self.lblOrigin, self.cmbOrigin)
        f.addRow("Quota", self.cmbH)
        self.cmbSys.currentIndexChanged.connect(self._refresh)
        self.cmbKind.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_):
        sysk = self.cmbSys.currentData()
        plane = self.cmbKind.currentData() == "plane"
        old = self.cmbZone.currentData()
        self.cmbZone.blockSignals(True)
        self.cmbZone.clear()
        self.cmbZone.addItem("Automatico", "auto")
        if dt.plane_kind(sysk) == "GB":
            self.cmbZone.addItem("Ovest (fuso 1)", "W")
            self.cmbZone.addItem("Est (fuso 2)", "E")
        else:
            for z in (32, 33, 34):
                self.cmbZone.addItem("Fuso %d" % z, z)
        i = self.cmbZone.findData(old)
        self.cmbZone.setCurrentIndex(i if i >= 0 else 0)
        self.cmbZone.blockSignals(False)
        self.cmbZone.setVisible(plane)
        self.lblZone.setVisible(plane)
        show_origin = (sysk == "R40") and not plane
        self.cmbOrigin.setVisible(show_origin)
        self.lblOrigin.setVisible(show_origin)

    def get(self):
        return {"sys": self.cmbSys.currentData(), "kind": self.cmbKind.currentData(),
                "zone": self.cmbZone.currentData(), "mm": bool(self.cmbOrigin.currentData()),
                "h": self.cmbH.currentData()}


class QuoteConverterDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Convertitore Quote GK2 / ConveRgo")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)

        g0 = QGroupBox("Grigliati IGM")
        f0 = QFormLayout(g0)
        self.dirGk2 = QgsFileWidget()
        self.dirGk2.setStorageMode(DIR_MODE)
        self.dirGk2.setFilePath(QSettings().value(SETTINGS_KEY, "", type=str))
        self.chkApprox = QCheckBox("Fuori dai grigliati usa il calcolo approssimato di QGIS (solo planimetria; le quote usano sempre il GK2)")
        f0.addRow("Cartella dei grigliati (.GK2)", self.dirGk2)
        f0.addRow(self.chkApprox)
        lay.addWidget(g0)

        g1 = QGroupBox("Dati")
        f1 = QFormLayout(g1)
        self.cmbLayer = QgsMapLayerComboBox()
        self.cmbLayer.setFilters(VECTOR_FILTER)
        self.cmbX, self.cmbY, self.cmbZ = QgsFieldComboBox(), QgsFieldComboBox(), QgsFieldComboBox()
        self.cmbZ.setAllowEmptyFieldName(True)
        self.cmbLayer.layerChanged.connect(self._layer_changed)
        self.txtOut = QLineEdit("Quote convertite")
        f1.addRow("Layer", self.cmbLayer)
        f1.addRow("Campo X (Est / Lon)", self.cmbX)
        f1.addRow("Campo Y (Nord / Lat)", self.cmbY)
        f1.addRow("Campo Z (quota)", self.cmbZ)
        self.fileOut = QgsFileWidget()
        self.fileOut.setStorageMode(SAVE_MODE)
        self.fileOut.setFilter("GeoPackage (*.gpkg);;Shapefile (*.shp)")
        self.fileOut.setDialogTitle("Salva il layer convertito")
        f1.addRow("Nome layer di output", self.txtOut)
        f1.addRow("Salva su file (vuoto = layer temporaneo)", self.fileOut)
        lay.addWidget(g1)

        row = QHBoxLayout()
        self.boxIn = SystemBox("Input")
        self.boxOut = SystemBox("Output", is_output=True)
        self.boxOut.cmbKind.setCurrentIndex(1)
        row.addWidget(self.boxIn)
        row.addWidget(self.boxOut)
        w = QWidget()
        w.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w)

        self.progress = QProgressBar()
        lay.addWidget(self.progress)
        self.btn = QPushButton("Converti")
        self.btn.clicked.connect(self.run)
        lay.addWidget(self.btn)
        self._layer_changed(self.cmbLayer.currentLayer())

    def _layer_changed(self, layer):
        for c in (self.cmbX, self.cmbY, self.cmbZ):
            c.setLayer(layer)

    def _msg(self, text, level=ML.Info):
        self.iface.messageBar().pushMessage("Convertitore Quote ConveRgo", text, level=level, duration=12)

    # ------------------------------------------------------------------ calcolo
    @staticmethod
    def _htype(sysk, h):
        if h == "auto":
            return "ell" if sysk in ("E2K", "E89") else "ort"
        return h

    def run(self):
        layer = self.cmbLayer.currentLayer()
        if layer is None:
            return self._msg("Seleziona un layer.", ML.Warning)
        fx, fy, fz = self.cmbX.currentField(), self.cmbY.currentField(), self.cmbZ.currentField()
        if not (fx and fy):
            return self._msg("Seleziona i campi X e Y.", ML.Warning)
        si, so = self.boxIn.get(), self.boxOut.get()
        h_in = self._htype(si["sys"], si["h"])
        h_out = "same" if h_in == "same" else self._htype(so["sys"], so["h"])
        if h_out == "same":
            h_in = "same"
        if h_in != "same" and not fz:
            return self._msg("Seleziona il campo Z oppure imposta la quota su 'Non modificare'.", ML.Warning)

        need_grid = (si["sys"] != so["sys"]) or (h_in != "same" and h_in != h_out)
        F = None
        if need_grid:
            folder = self.dirGk2.filePath()
            if not folder:
                return self._msg("Indica la cartella dei grigliati .GK2.", ML.Warning)
            try:
                F = GK2Folder(folder)
            except Exception as e:
                return self._msg("Errore grigliati: %s" % e, ML.Critical)
            QSettings().setValue(SETTINGS_KEY, folder)

        approx_tr = {}

        def approx(a, b, lat, lon):
            key = (a, b)
            if key not in approx_tr:
                approx_tr[key] = QgsCoordinateTransform(
                    QgsCoordinateReferenceSystem(APPROX_EPSG[a]), QgsCoordinateReferenceSystem(APPROX_EPSG[b]),
                    QgsProject.instance().transformContext())
            p = approx_tr[key].transform(QgsPointXY(lon, lat))
            return p.y(), p.x()

        # CRS del layer di output
        if so["kind"] == "geo":
            crs_out = QgsCoordinateReferenceSystem(dt.epsg_geographic(so["sys"], so["mm"]))
        elif so["zone"] != "auto":
            crs_out = QgsCoordinateReferenceSystem(dt.epsg_plane(so["sys"], so["zone"]))
        else:
            crs_out = QgsCoordinateReferenceSystem(dt.epsg_geographic(so["sys"], False))

        fields = QgsFields()
        for f in layer.fields():
            fields.append(f)
        for name in ("X_out", "Y_out", "Z_out", "N_geoide", "CORR_QUOTA"):
            fields.append(QgsField(name, T_DOUBLE, "double", 20, 6))
        fields.append(QgsField("FUSO", T_STRING, "string", 10))
        fields.append(QgsField("METODO", T_STRING, "string", 12))
        out = QgsVectorLayer("Point?crs=%s" % crs_out.authid(), self.txtOut.text() or "Quote convertite", "memory")
        pr = out.dataProvider()
        pr.addAttributes(list(fields))
        out.updateFields()

        feats, skipped, n_approx = [], 0, 0
        total = layer.featureCount()
        self.progress.setMaximum(max(total, 1))
        for i, f in enumerate(layer.getFeatures()):
            if i % 200 == 0:
                self.progress.setValue(i)
                QApplication.processEvents()
            try:
                x, y = float(f[fx]), float(f[fy])
                z = float(f[fz]) if (fz and f[fz] not in (None, "")) else 0.0
                res = dt.convert_point(F, si, so, h_in, h_out, x, y, z, bool(fz),
                                       approx if self.chkApprox.isChecked() else None)
            except Exception:
                res = None
            if res is None:
                skipped += 1
                continue
            xo, yo, zo, n, zone, method, glat, glon = res
            if method == "approx":
                n_approx += 1
            nf = QgsFeature(out.fields())
            if so["kind"] == "geo" or so["zone"] != "auto":
                pt = QgsPointXY(xo, yo)
            else:
                pt = QgsPointXY(glon, glat)
            nf.setGeometry(QgsGeometry.fromPointXY(pt))
            corr = None
            if zo is not None and h_in != "same" and h_out != "same":
                try:
                    corr = z - zo if (h_in == "ell" and h_out == "ort") else zo - z
                except Exception:
                    corr = None
            nf.setAttributes(list(f.attributes()) + [xo, yo, zo, n, corr, str(zone) if zone is not None else None, method])
            feats.append(nf)
        pr.addFeatures(feats)
        out.updateExtents()
        layer_name = self.txtOut.text() or "Quote convertite"
        path = self.fileOut.filePath().strip()
        if path and not path.lower().endswith((".gpkg", ".shp")):
            path += ".gpkg"
        saved_to = None
        if path:
            res_layer, err = self._save_layer(out, path, layer_name)
            if res_layer is None:
                self._msg("Salvataggio non riuscito (%s): il layer resta temporaneo." % err, ML.Warning)
                QgsProject.instance().addMapLayer(out)
            else:
                QgsProject.instance().addMapLayer(res_layer)
                saved_to = path
        else:
            QgsProject.instance().addMapLayer(out)
        self.progress.setValue(total)
        msg = "%d punti convertiti" % len(feats)
        if saved_to:
            msg += " e salvati in %s" % saved_to
        if n_approx:
            msg += ", %d con calcolo approssimato (fuori dai grigliati)" % n_approx
        if skipped:
            msg += ", %d saltati (valori non validi o fuori dai grigliati)" % skipped
        self._msg(msg, ML.Warning if (skipped or n_approx) else ML.Success)

    def _save_layer(self, layer, path, name):
        """Scrive il layer in memoria su GeoPackage / Shapefile e lo ricarica. -> (layer, errore)."""
        low = path.lower()
        if low.endswith(".shp"):
            driver = "ESRI Shapefile"
        else:
            driver = "GPKG"
            if not low.endswith(".gpkg"):
                path += ".gpkg"
        try:
            opts = QgsVectorFileWriter.SaveVectorOptions()
            opts.driverName = driver
            opts.fileEncoding = "UTF-8"
            if driver == "GPKG":
                opts.layerName = name
            res = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer, path, QgsProject.instance().transformContext(), opts)
            err_code, err_msg = res[0], res[1]
            ok = _enum(QgsVectorFileWriter, "WriterError", "NoError")
            if err_code != ok:
                return None, err_msg or str(err_code)
            uri = path if driver != "GPKG" else "%s|layername=%s" % (path, name)
            saved = QgsVectorLayer(uri, name, "ogr")
            if not saved.isValid():
                return None, "file scritto ma non riaperto"
            return saved, ""
        except Exception as e:
            return None, str(e)
