try:
    from qgis.PyQt.QtGui import QAction  # Qt6 / QGIS 4
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # Qt5 / QGIS 3
import os
from qgis.PyQt.QtGui import QIcon
from .dialog import QuoteConverterDialog

NAME = "Convertitore Quote ConveRgo"


class QuoteConverterPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dlg = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))
        self.action = QAction(icon, NAME, self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu(NAME, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginVectorMenu(NAME, self.action)
        self.iface.removeToolBarIcon(self.action)

    def run(self):
        self.dlg = QuoteConverterDialog(self.iface, self.iface.mainWindow())
        self.dlg.show()
