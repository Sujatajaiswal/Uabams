import sys

import requests
from PyQt5.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


DEFAULT_API_URL = "http://127.0.0.1:8000"


class ApiClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def get(self, path, params=None):
        response = requests.get(f"{self.base_url}{path}", params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def post(self, path, payload):
        response = requests.post(f"{self.base_url}{path}", json=payload, timeout=10)
        response.raise_for_status()
        return response.json()


class UabamsDesktop(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UABAMS Cloud Desktop")
        self.resize(1180, 760)
        self.client = ApiClient(DEFAULT_API_URL)

        root = QWidget()
        main_layout = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("UABAMS Cloud Desktop")
        title.setObjectName("Title")
        self.api_url = QLineEdit(DEFAULT_API_URL)
        connect_button = QPushButton("Connect")
        connect_button.clicked.connect(self.connect_api)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("API URL"))
        header.addWidget(self.api_url)
        header.addWidget(connect_button)
        main_layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_wheel_tab(), "Wheel Calibration")
        self.tabs.addTab(self.build_threshold_tab(), "Threshold")
        self.tabs.addTab(self.build_gateway_tab(), "Gateway Data")
        self.tabs.addTab(self.build_alerts_tab(), "Alerts")
        self.tabs.addTab(self.build_cloud_tab(), "Cloud Status")
        main_layout.addWidget(self.tabs)

        self.status = QLabel("Ready")
        self.status.setObjectName("Status")
        main_layout.addWidget(self.status)

        self.setCentralWidget(root)
        self.apply_style()
        self.show_status("Start FastAPI, then click Connect")

    def connect_api(self):
        self.client = ApiClient(self.api_url.text() or DEFAULT_API_URL)
        self.refresh_all()
        self.show_status("Connected to API")

    def build_wheel_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form_box = QGroupBox("Save Wheel Wear Calibration")
        form = QFormLayout(form_box)
        self.wheel_train = QLineEdit("TRAIN001")
        self.wheel_axle = QLineEdit("AXLE-1")
        self.wheel_position = QLineEdit("LEFT")
        self.new_diameter = self.double_input(920, 0, 2000)
        self.current_diameter = self.double_input(890, 0, 2000)
        self.encoder_pulses = self.int_input(1024, 1, 100000)
        save_button = QPushButton("Save Calibration")
        save_button.clicked.connect(self.save_wheel_calibration)

        form.addRow("Train No", self.wheel_train)
        form.addRow("Axle No", self.wheel_axle)
        form.addRow("Wheel Position", self.wheel_position)
        form.addRow("New Diameter (mm)", self.new_diameter)
        form.addRow("Current Diameter (mm)", self.current_diameter)
        form.addRow("Encoder Pulses/Rev", self.encoder_pulses)
        form.addRow(save_button)
        layout.addWidget(form_box)

        self.wheel_table = self.table([
            "Train", "Axle", "Wheel", "New Dia", "Current Dia",
            "Wear", "Correction", "Distance/Pulse"
        ])
        layout.addWidget(self.wheel_table)

        refresh = QPushButton("Refresh Wheel Calibration")
        refresh.clicked.connect(self.load_wheel_calibration)
        layout.addWidget(refresh)
        return tab

    def build_threshold_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form_box = QGroupBox("Set Acceleration Threshold")
        form = QFormLayout(form_box)
        self.threshold_route = QLineEdit("DEFAULT")
        self.vertical_threshold = self.double_input(50, 0, 100)
        self.lateral_threshold = self.double_input(80, 0, 100)
        save_button = QPushButton("Save Threshold")
        save_button.clicked.connect(self.save_threshold)
        self.active_threshold = QLabel("Active threshold will appear here")

        form.addRow("Route Name", self.threshold_route)
        form.addRow("Vertical Threshold (g)", self.vertical_threshold)
        form.addRow("Lateral Threshold (g)", self.lateral_threshold)
        form.addRow(save_button)
        layout.addWidget(form_box)
        layout.addWidget(self.active_threshold)

        refresh = QPushButton("Refresh Threshold")
        refresh.clicked.connect(self.load_threshold)
        layout.addWidget(refresh)
        layout.addStretch()
        return tab

    def build_gateway_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form_box = QGroupBox("Send Gateway Data")
        form = QFormLayout(form_box)
        self.record_index = self.int_input(757, 0, 999999999)
        self.gateway_train = QLineEdit("TRAIN001")
        self.gateway_route = QLineEdit("DEFAULT")
        self.km_marker = self.int_input(42, 0, 99999)
        self.meter = self.double_input(450.25, 0, 999.75)
        self.vertical_g = self.double_input(75, -100, 100)
        self.lateral_g = self.double_input(20, -100, 100)
        self.speed_kmph = self.double_input(90, 0, 300)
        self.latitude = self.double_input(12.97, -90, 90, decimals=6)
        self.longitude = self.double_input(77.59, -180, 180, decimals=6)
        self.status_code = self.int_input(1, 0, 999)
        send_button = QPushButton("Send Gateway Data")
        send_button.clicked.connect(self.send_gateway_data)

        form.addRow("Record Index", self.record_index)
        form.addRow("Train No", self.gateway_train)
        form.addRow("Route Name", self.gateway_route)
        form.addRow("KM Marker", self.km_marker)
        form.addRow("Meter", self.meter)
        form.addRow("Vertical g", self.vertical_g)
        form.addRow("Lateral g", self.lateral_g)
        form.addRow("Speed kmph", self.speed_kmph)
        form.addRow("Latitude", self.latitude)
        form.addRow("Longitude", self.longitude)
        form.addRow("Status Code", self.status_code)
        form.addRow(send_button)
        layout.addWidget(form_box)

        self.gateway_table = self.table([
            "Index", "Train", "Route", "KM", "Meter", "Vertical", "Lateral",
            "Speed", "Corrected Speed", "Correction", "Status", "Location", "Created At"
        ])
        layout.addWidget(self.gateway_table)

        refresh = QPushButton("Refresh Gateway Data")
        refresh.clicked.connect(self.load_gateway_data)
        layout.addWidget(refresh)
        return tab

    def build_alerts_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.alert_table = self.table([
            "Index", "Train", "Route", "Type", "Measured", "Threshold",
            "Speed", "KM", "Meter", "Status", "Location", "Created At"
        ])
        layout.addWidget(self.alert_table)

        refresh = QPushButton("Refresh Alerts")
        refresh.clicked.connect(self.load_alerts)
        layout.addWidget(refresh)
        return tab

    def build_cloud_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.cloud_table = self.table(["Item", "Value"])
        layout.addWidget(self.cloud_table)

        self.railman_preview = QPlainTextEdit()
        self.railman_preview.setReadOnly(True)
        self.railman_preview.setPlaceholderText("RailMAN export preview will appear here.")
        layout.addWidget(self.railman_preview)

        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh Cloud Status")
        refresh.clicked.connect(self.load_cloud_status)
        preview = QPushButton("Preview RailMAN Export")
        preview.clicked.connect(self.load_railman_export)
        buttons.addWidget(refresh)
        buttons.addWidget(preview)
        layout.addLayout(buttons)
        return tab

    def save_wheel_calibration(self):
        payload = {
            "train_no": self.wheel_train.text(),
            "axle_no": self.wheel_axle.text(),
            "wheel_position": self.wheel_position.text(),
            "new_wheel_diameter_mm": self.new_diameter.value(),
            "current_wheel_diameter_mm": self.current_diameter.value(),
            "encoder_pulses_per_rev": self.encoder_pulses.value(),
        }
        result = self.call(lambda: self.client.post("/wheel-calibration", payload))
        if result:
            self.show_status(result.get("message", "Calibration saved"))
            self.load_wheel_calibration()

    def save_threshold(self):
        payload = {
            "route_name": self.threshold_route.text() or "DEFAULT",
            "vertical_threshold": self.vertical_threshold.value(),
            "lateral_threshold": self.lateral_threshold.value(),
        }
        result = self.call(lambda: self.client.post("/threshold", payload))
        if result:
            self.show_status(result.get("message", "Threshold saved"))
            self.load_threshold()

    def send_gateway_data(self):
        payload = {
            "record_index": self.record_index.value(),
            "train_no": self.gateway_train.text(),
            "route_name": self.gateway_route.text() or "DEFAULT",
            "km_marker": self.km_marker.value(),
            "meter": self.meter.value(),
            "vertical_g": self.vertical_g.value(),
            "lateral_g": self.lateral_g.value(),
            "speed_kmph": self.speed_kmph.value(),
            "latitude": self.latitude.value(),
            "longitude": self.longitude.value(),
            "status_code": self.status_code.value(),
            "sample_distance_m": 0.25,
        }
        result = self.call(lambda: self.client.post("/api/data", payload))
        if result:
            alerts = ", ".join(result.get("generated_alerts", [])) or "No alerts"
            self.show_status(f"{result.get('message')} | {alerts}")
            self.load_gateway_data()
            self.load_alerts()

    def load_wheel_calibration(self):
        rows = self.call(lambda: self.client.get("/wheel-calibration"))
        if rows is None:
            return
        self.fill_table(
            self.wheel_table,
            rows,
            [
                "train_no", "axle_no", "wheel_position", "new_wheel_diameter_mm",
                "current_wheel_diameter_mm", "wheel_wear_mm", "correction_factor",
                "distance_per_pulse_mm",
            ],
        )

    def load_threshold(self):
        route_name = self.threshold_route.text() or "DEFAULT"
        row = self.call(lambda: self.client.get("/threshold", {"route_name": route_name}))
        if not row:
            return
        if "vertical_threshold" in row:
            self.active_threshold.setText(
                f"Active Threshold ({row.get('route_name', route_name)}): "
                f"Vertical {self.format_value(row['vertical_threshold'])}g | "
                f"Lateral {self.format_value(row['lateral_threshold'])}g"
            )
        else:
            self.active_threshold.setText(row.get("message", "No threshold configured"))

    def load_gateway_data(self):
        rows = self.call(lambda: self.client.get("/api/data"))
        if rows is None:
            return
        self.fill_table(
            self.gateway_table,
            rows,
            [
                "record_index", "train_no", "route_name", "km_marker", "meter",
                "vertical_g", "lateral_g", "speed_kmph",
                "corrected_speed_kmph", "wheel_correction_factor", "status_code",
                ("location", lambda row: f"{row.get('latitude')}, {row.get('longitude')}"),
                "created_at",
            ],
        )

    def load_alerts(self):
        rows = self.call(lambda: self.client.get("/alerts"))
        if rows is None:
            return
        self.fill_table(
            self.alert_table,
            rows,
            [
                "record_index", "train_no", "route_name", "alert_type",
                "measured_value", "threshold_value", "speed_kmph",
                "km_marker", "meter", "status_code",
                ("location", lambda row: f"{row.get('latitude')}, {row.get('longitude')}"),
                "created_at",
            ],
        )

    def load_cloud_status(self):
        status = self.call(lambda: self.client.get("/cloud/status"))
        if not status:
            return
        rows = [
            {"item": "API Status", "value": status.get("api_status")},
            {"item": "Database Status", "value": status.get("database_status")},
            {"item": "Cloud Database", "value": status.get("cloud_database")},
            {"item": "Database Host", "value": status.get("database_host")},
            {"item": "Schema Ready", "value": status.get("schema_ready")},
            {"item": "Available Tables", "value": ", ".join(status.get("available_tables", []))},
            {"item": "Gateway Endpoint", "value": status.get("gateway_ingest_endpoint")},
            {"item": "RailMAN Export", "value": status.get("railman_export_endpoint")},
            {"item": "Database Time", "value": status.get("database_time")},
        ]
        self.fill_table(self.cloud_table, rows, ["item", "value"])
        self.show_status("Cloud status refreshed")

    def load_railman_export(self):
        export = self.call(lambda: self.client.get("/railman/export", {"limit": 5}))
        if not export:
            return
        import json

        self.railman_preview.setPlainText(json.dumps(export, indent=2))
        self.show_status("RailMAN export preview loaded")

    def refresh_all(self):
        self.load_threshold()
        self.load_wheel_calibration()
        self.load_gateway_data()
        self.load_alerts()
        self.load_cloud_status()

    def call(self, fn):
        try:
            return fn()
        except requests.RequestException as exc:
            detail = str(exc)
            response = getattr(exc, "response", None)
            if response is not None:
                try:
                    detail_json = response.json()
                    detail = detail_json.get("detail", detail_json)
                except ValueError:
                    detail = response.text or detail
            QMessageBox.warning(self, "API Error", str(detail))
            self.show_status("API request failed")
            return None

    def fill_table(self, table, rows, fields):
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, field in enumerate(fields):
                if isinstance(field, tuple):
                    value = field[1](row)
                else:
                    value = row.get(field, "")
                table.setItem(row_index, col_index, QTableWidgetItem(self.format_value(value)))
        table.resizeColumnsToContents()

    def table(self, headers):
        widget = QTableWidget(0, len(headers))
        widget.setHorizontalHeaderLabels(headers)
        widget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        widget.setAlternatingRowColors(True)
        widget.setSelectionBehavior(QTableWidget.SelectRows)
        widget.setEditTriggers(QTableWidget.NoEditTriggers)
        return widget

    def double_input(self, value, minimum, maximum, decimals=2):
        widget = QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        widget.setSingleStep(0.1)
        return widget

    def int_input(self, value, minimum, maximum):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def show_status(self, message):
        self.status.setText(message)

    def format_value(self, value):
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return str(value)

    def apply_style(self):
        self.setStyleSheet("""
            QWidget {
                background: #f4f6f8;
                color: #17202a;
                font-family: Arial;
                font-size: 14px;
            }
            QLabel#Title {
                color: #17202a;
                font-size: 26px;
                font-weight: 700;
            }
            QLabel#Status {
                color: #16636b;
                font-weight: 700;
                padding: 6px;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d7dee4;
                border-radius: 8px;
                font-weight: 700;
                margin-top: 12px;
                padding: 16px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QLineEdit, QDoubleSpinBox, QSpinBox {
                min-height: 32px;
                border: 1px solid #cbd4dc;
                border-radius: 5px;
                background: #ffffff;
                padding: 4px 8px;
            }
            QPushButton {
                min-height: 34px;
                border: 0;
                border-radius: 6px;
                background: #16636b;
                color: #ffffff;
                font-weight: 700;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: #0f4d54;
            }
            QTabWidget::pane {
                border: 1px solid #d7dee4;
                background: #ffffff;
            }
            QTabBar::tab {
                background: #e8eef2;
                padding: 9px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #16636b;
                color: #ffffff;
            }
            QTableWidget {
                background: #ffffff;
                alternate-background-color: #f8fafb;
                gridline-color: #e1e7ec;
                selection-background-color: #dceff1;
            }
            QHeaderView::section {
                background: #eef3f6;
                color: #40505d;
                font-weight: 700;
                border: 0;
                padding: 8px;
            }
        """)


def main():
    app = QApplication(sys.argv)
    window = UabamsDesktop()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
