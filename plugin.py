import os

from qgis.PyQt.QtGui import QIcon

try:  # Qt6: QAction lives in QtGui
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5
    from qgis.PyQt.QtWidgets import QAction

MENU = "&Transit GTFS Builder"


class TransitGtfsBuilder:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dlg = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        self.action = QAction(
            icon, "Transit GTFS Builder", self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.dlg:
            self.dlg.close()
            self.dlg = None

    def run(self):
        if self.dlg is None:
            from .dialog import GtfsBuilderDialog

            self.dlg = GtfsBuilderDialog(self.iface, self.iface.mainWindow())
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
