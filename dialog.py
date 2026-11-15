import os

from qgis.PyQt.QtCore import QDate, QTime, QTimeZone, Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox,
                                 QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                                 QCompleter, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                                 QTabWidget, QTimeEdit, QVBoxLayout, QWidget)
from qgis.core import Qgis, QgsProject, QgsVectorLayer
from qgis.gui import QgsFieldComboBox, QgsMapLayerComboBox

from .data import LANGUAGES, ROUTE_TYPES, TIMEZONES
from .gtfs_core import DAYS, build_feed, export_feed, validate

def _layer_filter(kind):
    try:
        return getattr(Qgis.LayerFilter, kind)
    except Exception:
        from qgis.core import QgsMapLayerProxyModel
        return getattr(QgsMapLayerProxyModel, kind)


def _info_level():
    try:
        return Qgis.MessageLevel.Info
    except AttributeError:
        return Qgis.Info


class GtfsBuilderDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Transit GTFS Builder")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self._agency_tab()
        self._layers_tab()
        self._service_tab()
        self._export_tab()

    # ---------------------------------------------------------------- tabs
    def _agency_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.agency_name = QLineEdit("")
        self.agency_url = QLineEdit("https://www.example.com")
        self.agency_tz = QComboBox()
        self.agency_tz.addItems(TIMEZONES)
        self._searchable(self.agency_tz)
        self.agency_tz.setCurrentText(self._system_timezone())
        self.agency_lang = QComboBox()
        for name, code in LANGUAGES:
            self.agency_lang.addItem("%s (%s)" % (name, code), code)
        self._searchable(self.agency_lang)
        self.agency_lang.setCurrentIndex(max(self.agency_lang.findData("en"), 0))
        self.route_type = QComboBox()
        for label, val in ROUTE_TYPES:
            self.route_type.addItem(label, val)
        self.route_type.setCurrentIndex(max(self.route_type.findData(3), 0))
        f.addRow("Agency name", self.agency_name)
        f.addRow("Agency URL", self.agency_url)
        f.addRow("Timezone", self.agency_tz)
        f.addRow("Language", self.agency_lang)
        f.addRow("Vehicle type", self.route_type)

        days_row = QHBoxLayout()
        self.day_boxes = []
        for d in DAYS:
            cb = QCheckBox(d[:3].capitalize())
            cb.setChecked(True)
            self.day_boxes.append(cb)
            days_row.addWidget(cb)
        f.addRow("Service days", days_row)
        self.start_date = QDateEdit(QDate.currentDate())
        self.start_date.setCalendarPopup(True)
        self.end_date = QDateEdit(QDate.currentDate().addYears(1))
        self.end_date.setCalendarPopup(True)
        f.addRow("Valid from", self.start_date)
        f.addRow("Valid until", self.end_date)
        self.tabs.addTab(w, "1. Agency")

    def _layers_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.stops_cb = QgsMapLayerComboBox()
        self.stops_cb.setFilters(_layer_filter("PointLayer"))
        self.stop_name_f = QgsFieldComboBox()
        self.stop_id_f = QgsFieldComboBox()
        self.routes_cb = QgsMapLayerComboBox()
        self.routes_cb.setFilters(_layer_filter("LineLayer"))
        self.route_id_f = QgsFieldComboBox()
        self.route_short_f = QgsFieldComboBox()
        self.route_long_f = QgsFieldComboBox()
        self.route_head_f = QgsFieldComboBox()
        self.route_first_f = QgsFieldComboBox()
        self.route_last_f = QgsFieldComboBox()
        for cb in (self.stop_name_f, self.stop_id_f, self.route_id_f, self.route_short_f,
                   self.route_long_f, self.route_head_f, self.route_first_f, self.route_last_f):
            cb.setAllowEmptyFieldName(True)
        self._link(self.stops_cb, [(self.stop_name_f, ("stop_name", "name")),
                                   (self.stop_id_f, ("stop_id", "id"))])
        self._link(self.routes_cb, [(self.route_id_f, ("route_id", "id")),
                                    (self.route_short_f, ("short_name", "route_short_name")),
                                    (self.route_long_f, ("long_name", "route_long_name", "name")),
                                    (self.route_head_f, ("headway_min", "headway")),
                                    (self.route_first_f, ("first_dep", "first")),
                                    (self.route_last_f, ("last_dep", "last"))])
        f.addRow(QLabel("<b>Stops (point layer)</b>"))
        f.addRow("Layer", self.stops_cb)
        f.addRow("Name field", self.stop_name_f)
        f.addRow("ID field (optional)", self.stop_id_f)
        f.addRow(QLabel("<b>Routes (line layer)</b>"))
        f.addRow("Layer", self.routes_cb)
        f.addRow("Route ID (optional)", self.route_id_f)
        f.addRow("Short name (optional)", self.route_short_f)
        f.addRow("Long name (optional)", self.route_long_f)
        f.addRow("Headway, min (optional)", self.route_head_f)
        f.addRow("First departure (optional)", self.route_first_f)
        f.addRow("Last departure (optional)", self.route_last_f)
        self.buffer_m = QSpinBox()
        self.buffer_m.setRange(1, 2000)
        self.buffer_m.setValue(75)
        self.buffer_m.setSuffix(" m")
        f.addRow("Stop-to-route distance", self.buffer_m)
        btn = QPushButton("Create empty stops and routes layers to digitize")
        btn.clicked.connect(self._create_templates)
        f.addRow(btn)
        self.tabs.addTab(w, "2. Layers")

    def _service_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        self.headway = QDoubleSpinBox()
        self.headway.setRange(0.5, 480)
        self.headway.setValue(10)
        self.headway.setSuffix(" min")
        self.first_dep = QTimeEdit(QTime(6, 0))
        self.first_dep.setDisplayFormat("HH:mm")
        self.last_dep = QTimeEdit(QTime(21, 0))
        self.last_dep.setDisplayFormat("HH:mm")
        self.speed = QDoubleSpinBox()
        self.speed.setRange(1, 120)
        self.speed.setValue(18)
        self.speed.setSuffix(" km/h")
        self.dwell = QSpinBox()
        self.dwell.setRange(0, 600)
        self.dwell.setValue(20)
        self.dwell.setSuffix(" s")
        self.both_dirs = QCheckBox("Also generate the return direction")
        self.both_dirs.setChecked(True)
        f.addRow("Default headway", self.headway)
        f.addRow("First departure", self.first_dep)
        f.addRow("Last departure", self.last_dep)
        f.addRow("Average speed", self.speed)
        f.addRow("Time at each stop", self.dwell)
        f.addRow(self.both_dirs)
        f.addRow(QLabel("Route fields on the Layers tab override these defaults per route."))
        self.tabs.addTab(w, "3. Service")

    def _export_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.out_dir = QLineEdit(os.path.expanduser("~"))
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        row.addWidget(self.out_dir)
        row.addWidget(browse)
        v.addWidget(QLabel("Output folder"))
        v.addLayout(row)
        self.zip_name = QLineEdit("gtfs_feed.zip")
        v.addWidget(QLabel("Zip file name"))
        v.addWidget(self.zip_name)
        btns = QHBoxLayout()
        b1 = QPushButton("Validate")
        b1.clicked.connect(lambda: self._run(False))
        b2 = QPushButton("Build and export")
        b2.clicked.connect(lambda: self._run(True))
        btns.addWidget(b1)
        btns.addWidget(b2)
        v.addLayout(btns)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        v.addWidget(self.log)
        self.tabs.addTab(w, "4. Export")

    # ------------------------------------------------------------- helpers
    def _link(self, layer_cb, field_cbs):
        def update(*_args):
            lyr = layer_cb.currentLayer()
            for cb, guesses in field_cbs:
                cb.setLayer(lyr)
                if lyr is not None:
                    names = {x.name().lower(): x.name() for x in lyr.fields()}
                    for g in guesses:
                        if g in names:
                            cb.setField(names[g])
                            break
        layer_cb.layerChanged.connect(update)
        update()

    @staticmethod
    def _searchable(cb):
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        comp = cb.completer()
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

    @staticmethod
    def _system_timezone():
        try:
            tz = bytes(QTimeZone.systemTimeZoneId()).decode()
            if tz in TIMEZONES:
                return tz
        except Exception:
            pass
        return "UTC"

    def _lang_code(self):
        idx = self.agency_lang.findText(self.agency_lang.currentText())
        return self.agency_lang.itemData(idx) if idx >= 0 else ""

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def _log(self, level, msg):
        self.log.appendPlainText("[%s] %s" % (level, msg))

    def _create_templates(self):
        stops = QgsVectorLayer("Point?crs=EPSG:4326&field=stop_id:string&field=stop_name:string",
                               "GTFS Stops", "memory")
        routes = QgsVectorLayer(
            "LineString?crs=EPSG:4326&field=route_id:string&field=short_name:string"
            "&field=long_name:string&field=headway_min:double&field=first_dep:string"
            "&field=last_dep:string", "GTFS Routes", "memory")
        QgsProject.instance().addMapLayer(stops)
        QgsProject.instance().addMapLayer(routes)
        self.stops_cb.setLayer(stops)
        self.routes_cb.setLayer(routes)
        self.iface.setActiveLayer(stops)
        stops.startEditing()
        self.iface.messageBar().pushMessage(
            "GTFS Builder",
            "Temporary layers added. Digitize stops and routes, then export them to GeoPackage "
            "to keep them.", level=_info_level(), duration=10)

    def _cfg(self):
        def fld(cb):
            return cb.currentField() or None
        return {
            "agency_name": self.agency_name.text().strip(),
            "agency_url": self.agency_url.text().strip(),
            "agency_timezone": self.agency_tz.currentText().strip(),
            "agency_lang": self._lang_code(),
            "route_type": self.route_type.currentData(),
            "days": [cb.isChecked() for cb in self.day_boxes],
            "start_date": self.start_date.date().toString("yyyyMMdd"),
            "end_date": self.end_date.date().toString("yyyyMMdd"),
            "stop_name_field": fld(self.stop_name_f), "stop_id_field": fld(self.stop_id_f),
            "route_id_field": fld(self.route_id_f), "route_short_field": fld(self.route_short_f),
            "route_long_field": fld(self.route_long_f), "route_headway_field": fld(self.route_head_f),
            "route_first_field": fld(self.route_first_f), "route_last_field": fld(self.route_last_f),
            "buffer_m": self.buffer_m.value(),
            "headway_min": self.headway.value(),
            "first_dep": self.first_dep.time().toString("HH:mm"),
            "last_dep": self.last_dep.time().toString("HH:mm"),
            "speed_kmh": self.speed.value(),
            "dwell_sec": self.dwell.value(),
            "both_directions": self.both_dirs.isChecked(),
        }

    def _run(self, export):
        stops, routes = self.stops_cb.currentLayer(), self.routes_cb.currentLayer()
        if stops is None or routes is None:
            QMessageBox.warning(self, "GTFS Builder", "Choose a stops layer and a routes layer first.")
            return
        cfg = self._cfg()
        self.log.clear()
        try:
            feed, blog = build_feed(stops, routes, cfg)
        except Exception as e:  # keep the dialog alive on bad data
            self._log("ERROR", "Build failed: %s" % e)
            return
        for lvl, msg in blog:
            self._log(lvl, msg)
        results = validate(feed, cfg)
        for lvl, msg in results:
            self._log(lvl, msg)
        if any(l == "ERROR" for l, _ in results):
            self._log("ERROR", "Fix the errors above, then try again.")
            return
        if export:
            try:
                path = export_feed(feed, self.out_dir.text().strip(), self.zip_name.text().strip() or "gtfs_feed.zip")
            except Exception as e:
                self._log("ERROR", "Export failed: %s" % e)
                return
            self._log("OK", "Exported: %s" % path)
            self.iface.messageBar().pushMessage("GTFS Builder", "Feed exported to %s" % path,
                                                level=_info_level(), duration=8)
