from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


OUT = Path("UABAMS_Manager_Meeting_Document_No_Railway.docx")
PUBLIC_CLOUD_URL = "https://uabams-cloud-api.onrender.com"


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(cell, text, bold=False):
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(9)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def style_table(table):
    table.style = "Table Grid"
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                for run in paragraph.runs:
                    run.font.name = "Calibri"
                    run.font.size = Pt(9)
    for cell in table.rows[0].cells:
        set_cell_shading(cell, "E8EEF5")
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True


def add_title(doc):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("UABAMS Cloud Module Work Summary")
    run.bold = True
    run.font.size = Pt(24)
    run.font.color.rgb = RGBColor(11, 37, 69)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Meeting Presentation Document")
    run.font.size = Pt(13)
    run.font.color.rgb = RGBColor(85, 85, 85)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Project: Unattended Axle Box Level Acceleration Measurement System (UABAMS)")
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(85, 85, 85)


def add_heading(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        run.font.color.rgb = RGBColor(46, 116, 181) if level <= 2 else RGBColor(31, 77, 120)


def add_bullets(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(item)


def add_numbered(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Number")
        p.add_run(item)


def add_note_box(doc, title, text):
    table = doc.add_table(rows=1, cols=1)
    table.autofit = True
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F4F6F9")
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(title)
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor(31, 58, 95)
    p = cell.add_paragraph(text)
    p.paragraph_format.space_after = Pt(0)
    for run in p.runs:
        run.font.size = Pt(9)


def add_screenshot_slot(doc, caption):
    table = doc.add_table(rows=1, cols=1)
    table.autofit = True
    cell = table.cell(0, 0)
    set_cell_shading(cell, "F7F9FB")
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(0)
    run = p.add_run(f"Insert Screenshot Here: {caption}")
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(85, 85, 85)
    for _ in range(5):
        p = cell.add_paragraph()
        p.paragraph_format.space_after = Pt(0)


def build_doc():
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10.5)
    styles["Normal"].paragraph_format.space_after = Pt(6)
    styles["Normal"].paragraph_format.line_spacing = 1.1

    add_title(doc)
    add_note_box(
        doc,
        "One-line summary",
        "I completed the assigned cloud module work for UABAMS: axle/wheel calibration, 0-100g threshold management, gateway data receiving, Render PostgreSQL cloud storage, and CSV report download through a public Render dashboard.",
    )

    add_heading(doc, "1. Assigned Work And Status", 1)
    status_table = doc.add_table(rows=1, cols=3)
    for i, h in enumerate(["Assigned Task", "What I Implemented", "Status"]):
        set_cell_text(status_table.rows[0].cells[i], h, True)
    status_rows = [
        ("Axle/Wheel calibration", "Calibration API/UI stores train, axle, wheel position, new/current diameter, encoder pulses, wheel wear, correction factor, and distance per pulse.", "Completed"),
        ("Threshold setting 0-100g", "Threshold API/UI supports route-wise vertical and lateral threshold values from 0g to 100g, such as 50g and 80g.", "Completed"),
        ("Receive gateway data", "Gateway API/UI receives train number, route, KM, meter, vertical/lateral acceleration, speed, GPS, status, and record index.", "Completed"),
        ("Store data in cloud", "All records are stored in Render PostgreSQL and can be viewed/downloaded from the deployed public dashboard.", "Completed"),
    ]
    for row in status_rows:
        cells = status_table.add_row().cells
        for i, value in enumerate(row):
            set_cell_text(cells[i], value)
    style_table(status_table)

    add_heading(doc, "2. Technology Stack", 1)
    tech_table = doc.add_table(rows=1, cols=3)
    for i, h in enumerate(["Layer", "Technology", "Purpose"]):
        set_cell_text(tech_table.rows[0].cells[i], h, True)
    tech_rows = [
        ("Cloud Backend", "Python + FastAPI", "Receives calibration, threshold, and gateway data through APIs."),
        ("Cloud Hosting", "Render Web Service", "Hosts the public cloud dashboard and backend APIs."),
        ("Cloud Database", "Render PostgreSQL", "Stores calibration, threshold, gateway, and alert records."),
        ("Database Access", "SQLAlchemy + psycopg2", "Connects FastAPI to PostgreSQL."),
        ("Validation", "Pydantic", "Validates acceleration ranges and threshold limits."),
        ("Desktop UI", "PyQt5", "Operator interface for local/desktop workflow."),
        ("Reports", "CSV Export", "Downloads cloud database records as CSV files."),
        ("API Testing", "Swagger/OpenAPI", "Tests and documents backend endpoints."),
    ]
    for row in tech_rows:
        cells = tech_table.add_row().cells
        for i, value in enumerate(row):
            set_cell_text(cells[i], value)
    style_table(tech_table)

    add_heading(doc, "3. Cloud Architecture", 1)
    add_numbered(
        doc,
        [
            "The public Render Web Service runs the FastAPI cloud backend.",
            "The gateway/API forms send data to the FastAPI endpoint.",
            "FastAPI validates the input and performs required calculations.",
            "FastAPI stores the processed records in Render PostgreSQL.",
            "The public dashboard reads stored records from PostgreSQL and displays them in tables.",
            "CSV download endpoints export the same stored data for reporting/demo purpose.",
        ],
    )
    add_note_box(
        doc,
        "Architecture flow",
        "Gateway/Data Entry -> FastAPI on Render -> Render PostgreSQL -> Public Dashboard -> CSV Downloads",
    )

    add_heading(doc, "4. Public URLs To Show", 1)
    url_table = doc.add_table(rows=1, cols=2)
    set_cell_text(url_table.rows[0].cells[0], "Page / Endpoint", True)
    set_cell_text(url_table.rows[0].cells[1], "Public URL", True)
    url_rows = [
        ("Cloud Dashboard", f"{PUBLIC_CLOUD_URL}/cloud-dashboard"),
        ("CSV Reports", f"{PUBLIC_CLOUD_URL}/csv-page"),
        ("Operator Dashboard", f"{PUBLIC_CLOUD_URL}/dashboard"),
        ("API Docs", f"{PUBLIC_CLOUD_URL}/docs"),
        ("Gateway CSV", f"{PUBLIC_CLOUD_URL}/csv/download/gateway-data"),
        ("Alerts CSV", f"{PUBLIC_CLOUD_URL}/csv/download/alerts"),
    ]
    for row in url_rows:
        cells = url_table.add_row().cells
        set_cell_text(cells[0], row[0])
        set_cell_text(cells[1], row[1])
    style_table(url_table)

    add_heading(doc, "5. Page-Wise Explanation", 1)
    pages = [
        ("Public Cloud Dashboard", "Shows latest gateway records and generated alerts from the cloud database. This page proves that the backend is deployed publicly on Render and reading cloud-stored data."),
        ("CSV Reports", "Shows report categories and allows preview/download of wheel calibration, threshold, gateway data, and alert records in CSV format."),
        ("Wheel Calibration", "Stores train, axle, wheel position, diameter, encoder pulse information, wheel wear, correction factor, and distance per pulse."),
        ("Threshold Management", "Allows vertical and lateral threshold values between 0g and 100g. Example values are 50g and 80g."),
        ("Gateway Data", "Receives gateway-like records with train, route, KM, meter, acceleration, speed, GPS, and status fields and stores them in cloud PostgreSQL."),
        ("Alerts", "Displays alerts generated when corrected speed is above 80 kmph and acceleration crosses the configured threshold."),
    ]
    for title, text in pages:
        add_heading(doc, title, 2)
        doc.add_paragraph(text)
        add_screenshot_slot(doc, title)

    add_heading(doc, "6. Calculations Implemented", 1)
    calc_table = doc.add_table(rows=1, cols=3)
    for i, h in enumerate(["Calculation", "Formula / Rule", "Example"]):
        set_cell_text(calc_table.rows[0].cells[i], h, True)
    calculations = [
        ("Wheel wear", "new_diameter - current_diameter", "920 - 890 = 30 mm"),
        ("Wheel circumference", "pi * current_diameter", "3.14159 * 890 = 2796.01 mm"),
        ("Distance per pulse", "circumference / encoder_pulses", "2796.01 / 1024 = 2.73 mm"),
        ("Correction factor", "current_diameter / new_diameter", "890 / 920 = 0.9674"),
        ("Corrected speed", "gateway_speed * correction_factor", "90 * 0.9674 = 87.06 kmph"),
        ("Alert rule", "corrected_speed > 80 and measured_g > threshold_g", "87.06 > 80 and 75g > 50g"),
    ]
    for row in calculations:
        cells = calc_table.add_row().cells
        for i, value in enumerate(row):
            set_cell_text(cells[i], value)
    style_table(calc_table)

    add_heading(doc, "7. Database Tables", 1)
    db_table = doc.add_table(rows=1, cols=2)
    set_cell_text(db_table.rows[0].cells[0], "Table", True)
    set_cell_text(db_table.rows[0].cells[1], "Purpose", True)
    db_rows = [
        ("wheel_calibration", "Stores axle/wheel calibration, wear, correction factor, and distance per pulse."),
        ("thresholds", "Stores vertical/lateral threshold values from 0g to 100g."),
        ("acceleration_data", "Stores received gateway data and corrected speed."),
        ("alerts", "Stores generated alerts when readings cross configured limits."),
    ]
    for row in db_rows:
        cells = db_table.add_row().cells
        set_cell_text(cells[0], row[0])
        set_cell_text(cells[1], row[1])
    style_table(db_table)

    add_heading(doc, "8. API Endpoints", 1)
    api_table = doc.add_table(rows=1, cols=3)
    for i, h in enumerate(["Endpoint", "Method", "Purpose"]):
        set_cell_text(api_table.rows[0].cells[i], h, True)
    api_rows = [
        ("/wheel-calibration", "POST/GET", "Save and view axle/wheel calibration records."),
        ("/threshold", "POST/GET", "Save and view 0-100g threshold values."),
        ("/api/data", "POST/GET", "Receive and view gateway records stored in cloud."),
        ("/alerts", "GET", "View generated alerts."),
        ("/csv-page", "GET", "Preview and download CSV reports."),
        ("/csv/download/{report}", "GET", "Download CSV files for calibration, thresholds, gateway data, and alerts."),
        ("/docs", "GET", "Swagger API documentation."),
    ]
    for row in api_rows:
        cells = api_table.add_row().cells
        for i, value in enumerate(row):
            set_cell_text(cells[i], value)
    style_table(api_table)

    add_heading(doc, "9. Demo Workflow", 1)
    add_numbered(
        doc,
        [
            f"Open the public cloud dashboard: {PUBLIC_CLOUD_URL}/cloud-dashboard.",
            "Show latest gateway data and alerts displayed from the cloud database.",
            "Open CSV Reports page.",
            "Preview Thresholds or Gateway Data to show database records in the browser.",
            "Click Download CSV to show that cloud-stored records can be exported.",
            "Open Operator Dashboard and show Wheel Calibration, Threshold, Gateway Data, and Alerts pages if needed.",
            "Open API Docs to show available backend APIs.",
        ],
    )

    add_heading(doc, "10. Manager Explanation Script", 1)
    add_bullets(
        doc,
        [
            "My assigned work was the cloud module for UABAMS.",
            "I implemented axle/wheel calibration and stored calibration records in the cloud database.",
            "I implemented threshold management where vertical and lateral thresholds can be set from 0g to 100g.",
            "I implemented gateway data receiving through FastAPI and store the received records in Render PostgreSQL.",
            "I deployed the FastAPI backend on Render, so the dashboard is public and can be opened from any browser.",
            "I added CSV report preview/download so calibration, threshold, gateway, and alert records can be exported from cloud storage.",
            "I also added alert generation based on corrected speed above 80 kmph and acceleration crossing configured thresholds.",
        ],
    )

    add_heading(doc, "11. Future Enhancements", 1)
    add_bullets(
        doc,
        [
            "Add authentication for operator login and protected write APIs.",
            "Add PDF report export in addition to CSV reports.",
            "Add charts for speed, vertical acceleration, lateral acceleration, and alert trends.",
            "Add notification support for alerts if required.",
            "Improve dashboard filters by train number, route, date, and alert type.",
        ],
    )

    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("UABAMS Cloud Module Work Summary").font.size = Pt(9)

    doc.save(OUT)


if __name__ == "__main__":
    build_doc()
