import sys

import requests
from PyQt5.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
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

    def put_file(self, path, file_path, params=None, headers=None):
        with open(file_path, "rb") as file_handle:
            response = requests.put(
                f"{self.base_url}{path}",
                params=params,
                data=file_handle,
                headers=headers or {},
                timeout=60,
            )
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
        self.tabs.addTab(self.build_archive_tab(), "Gateway Archive")
        self.tabs.addTab(self.build_parsed_records_tab(), "Parsed Records")
        self.tabs.addTab(self.build_alert_events_tab(), "Alert Events")
        self.tabs.addTab(self.build_cloud_tab(), "Cloud Summary")
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

    def build_archive_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form_box = QGroupBox("Upload Gateway Session ZIP")
        form = QFormLayout(form_box)
        self.archive_path = QLineEdit()
        self.archive_name = QLineEdit()
        self.archive_name.setPlaceholderText("GW_BOGIE_001__TRAIN_07__SESSION_20260609_083015.zip")
        browse_button = QPushButton("Browse ZIP")
        browse_button.clicked.connect(self.browse_archive)
        upload_button = QPushButton("Upload Archive")
        upload_button.clicked.connect(self.upload_archive)

        file_row = QHBoxLayout()
        file_row.addWidget(self.archive_path)
        file_row.addWidget(browse_button)
        form.addRow("Session ZIP", file_row)
        form.addRow("Archive Filename", self.archive_name)
        form.addRow(upload_button)
        layout.addWidget(form_box)

        self.archive_table = self.table([
            "Archive ID", "Gateway", "Train", "Session", "Archive Name",
            "Size", "Status", "Received At"
        ])
        layout.addWidget(self.archive_table)

        refresh = QPushButton("Refresh Session Archives")
        refresh.clicked.connect(self.load_archives)
        layout.addWidget(refresh)
        return tab

    def build_parsed_records_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.parsed_record_selector = QLineEdit("rms-records")
        self.parsed_record_selector.setPlaceholderText("archives, rms-records, peak-records, fault-records, raw-packet-records")
        refresh = QPushButton("Refresh Parsed Records")
        refresh.clicked.connect(self.load_parsed_records)
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("CSV Report"))
        selector_row.addWidget(self.parsed_record_selector)
        selector_row.addWidget(refresh)
        layout.addLayout(selector_row)

        self.parsed_table = self.table([
            "Column 1", "Column 2", "Column 3", "Column 4", "Column 5",
            "Column 6", "Column 7", "Column 8"
        ])
        layout.addWidget(self.parsed_table)
        return tab

    def build_alert_events_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.alert_event_table = self.table([
            "ID", "Gateway", "Train", "Session", "Window", "Speed",
            "Axes Count", "Received At"
        ])
        layout.addWidget(self.alert_event_table)

        refresh = QPushButton("Refresh Alert Events")
        refresh.clicked.connect(self.load_alert_events)
        layout.addWidget(refresh)
        return tab

    def build_cloud_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.cloud_table = self.table(["Item", "Value"])
        layout.addWidget(self.cloud_table)

        self.csv_preview = QPlainTextEdit()
        self.csv_preview.setReadOnly(True)
        self.csv_preview.setPlaceholderText("Cloud CSV report preview will appear here.")
        layout.addWidget(self.csv_preview)

        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh Cloud Summary")
        refresh.clicked.connect(self.load_cloud_status)
        preview = QPushButton("Preview Session Archives JSON")
        preview.clicked.connect(self.load_archive_preview)
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

    def browse_archive(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Gateway Session ZIP",
            "",
            "ZIP Archives (*.zip)",
        )
        if not file_path:
            return
        self.archive_path.setText(file_path)
        self.archive_name.setText(file_path.split("/")[-1].split("\\")[-1])

    def upload_archive(self):
        file_path = self.archive_path.text().strip()
        archive_name = self.archive_name.text().strip()
        if not file_path or not archive_name:
            QMessageBox.warning(self, "Archive Upload", "Please select a ZIP file and enter the archive filename.")
            return

        result = self.call(
            lambda: self.client.put_file(
                "/api/v1/archive",
                file_path,
                params={"filename": archive_name},
                headers={
                    "Content-Type": "application/zip",
                    "X-Archive-Name": archive_name,
                },
            )
        )
        if result:
            self.show_status(
                f"Archive uploaded: {result.get('archiveName', archive_name)} | "
                f"Validation {result.get('validationStatus', 'ok')}"
            )
            self.load_archives()
            self.load_parsed_records()

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

    def load_archives(self):
        rows = self.call(lambda: self.client.get("/api/v1/archives", {"limit": 50}))
        if rows is None:
            return
        self.fill_table(
            self.archive_table,
            rows,
            [
                "archive_id", "gateway_id", "train_id", "session_name",
                "archive_name", "archive_size_bytes", "validation_status",
                "upload_received_utc",
            ],
        )

    def load_parsed_records(self):
        report_name = self.parsed_record_selector.text().strip() or "rms-records"
        report = self.call(lambda: self.client.get(f"/csv/preview/{report_name}", {"limit": 25}))
        if not report:
            return
        rows = report.get("rows", [])
        self.fill_dynamic_table(self.parsed_table, rows)
        self.show_status(f"Loaded {len(rows)} rows from {report.get('title', report_name)}")

    def load_alert_events(self):
        report = self.call(lambda: self.client.get("/csv/preview/cloud-alert-events", {"limit": 50}))
        if not report:
            return
        rows = report.get("rows", [])
        self.fill_table(
            self.alert_event_table,
            rows,
            [
                "alert_event_id", "gateway_id", "train_id", "session_name",
                ("window", lambda row: f"{row.get('window_start_mm')} - {row.get('window_end_mm')}"),
                "speed_kmph", "triggered_axes_count", "received_utc",
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
            {"item": "Gateway Archive Endpoint", "value": "/api/v1/archive"},
            {"item": "CSV Reports Page", "value": "/csv-page"},
            {"item": "Database Time", "value": status.get("database_time")},
        ]
        self.fill_table(self.cloud_table, rows, ["item", "value"])
        self.show_status("Cloud summary refreshed")

    def load_archive_preview(self):
        preview = self.call(lambda: self.client.get("/csv/preview/archives", {"limit": 5}))
        if not preview:
            return
        import json

        self.csv_preview.setPlainText(json.dumps(preview, indent=2))
        self.show_status("Session archive preview loaded")

    def refresh_all(self):
        self.load_threshold()
        self.load_wheel_calibration()
        self.load_archives()
        self.load_parsed_records()
        self.load_alert_events()
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
        table.setColumnCount(len(fields))
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, field in enumerate(fields):
                if isinstance(field, tuple):
                    value = field[1](row)
                else:
                    value = row.get(field, "")
                table.setItem(row_index, col_index, QTableWidgetItem(self.format_value(value)))
        table.resizeColumnsToContents()

    def fill_dynamic_table(self, table, rows):
        if not rows:
            table.clear()
            table.setColumnCount(1)
            table.setHorizontalHeaderLabels(["Message"])
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("No records found yet. Upload a valid gateway session ZIP first."))
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            return

        columns = list(rows[0].keys())
        table.clear()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels([column.replace("_", " ").title() for column in columns])
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, column in enumerate(columns):
                table.setItem(row_index, col_index, QTableWidgetItem(self.format_value(row.get(column))))
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
