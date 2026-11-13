"""Evidence-based PDF, CSV and JSON report generation for saved ARCHEX experiments."""
import csv
import io
import json
import re
import uuid
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart

from app.services.research import loads, load_result, flatten_metrics

REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"
ALLOWED_SECTIONS = {"executive_summary", "background", "methodology", "configuration", "results", "discussion", "conclusion"}


def _scalar_metrics(result: Any) -> dict[str, int | float | bool | str | None]:
    if not isinstance(result, dict):
        return {}
    flat = flatten_metrics(result)
    return {str(k): v for k, v in flat.items()
            if isinstance(v, (int, float, bool, str)) or v is None}


def build_payload(experiment, executions, title: str, sections: list[str], detail_level: str) -> dict:
    result = load_result(experiment.result_json) if experiment.result_json else None
    metrics = _scalar_metrics(result)
    return {
        "project": "ARCHEX — AI Microarchitecture Security & Research Command Centre",
        "report_title": title,
        "experiment": {
            "id": experiment.id, "name": experiment.name, "description": experiment.description,
            "category": experiment.category, "simulation": experiment.simulation,
            "status": experiment.status, "version": experiment.version,
            "created_at": experiment.created_at, "updated_at": experiment.updated_at,
            "configuration": loads(experiment.config_json), "notes": experiment.notes,
            "tags": loads(experiment.tags_json, []), "result": result,
        },
        "executions": [{"id": e.id, "created_at": e.created_at, "status": e.status,
                        "duration_ms": e.duration_ms, "software_version": e.software_version,
                        "replay_of": e.replay_of, "error": e.error,
                        "configuration": loads(e.config_json),
                        "result": load_result(e.result_json) if e.result_json else None} for e in executions],
        "metrics": metrics, "sections": sections, "detail_level": detail_level,
        "data_provenance": "Generated from persisted ARCHEX experiment and execution records. Simulation outputs are software-generated and are not physical hardware measurements.",
    }


def make_csv(payload: dict) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["record_type", "experiment_id", "experiment_name", "simulation", "metric", "value", "unit_or_context"])
    exp = payload["experiment"]
    for key, value in payload["metrics"].items():
        writer.writerow(["experiment_metric", exp["id"], exp["name"], exp["simulation"], key,
                         json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value,
                         "simulation output; not physical hardware measurement"])
    for execution in payload["executions"]:
        writer.writerow(["execution", exp["id"], exp["name"], exp["simulation"], "duration_ms",
                         execution["duration_ms"], f"status={execution['status']}; execution_id={execution['id']}"])
    if not payload["metrics"] and not payload["executions"]:
        writer.writerow(["metadata", exp["id"], exp["name"], exp["simulation"], "status", exp["status"], "No completed result metrics are available"])
    return out.getvalue().encode("utf-8-sig")


def make_pdf(payload: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=19*mm, bottomMargin=18*mm, title=payload["report_title"],
                            author="ARCHEX Research Platform")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ArcTitle", parent=styles["Title"], textColor=colors.HexColor("#8B5CF6"), alignment=TA_CENTER, fontSize=24, leading=29, spaceAfter=8))
    styles.add(ParagraphStyle(name="ArcSub", parent=styles["Normal"], textColor=colors.HexColor("#475569"), alignment=TA_CENTER, fontSize=9, leading=13))
    styles.add(ParagraphStyle(name="ArcH", parent=styles["Heading2"], textColor=colors.HexColor("#312E81"), spaceBefore=12, spaceAfter=7))
    styles.add(ParagraphStyle(name="ArcSmall", parent=styles["BodyText"], fontSize=8, leading=11))
    story = [Spacer(1, 28*mm), Paragraph("ARCHEX", styles["ArcTitle"]),
             Paragraph("Decode the Architecture. Detect the Anomaly. Engineer the Defence.", styles["ArcSub"]),
             Spacer(1, 17*mm), Paragraph(payload["report_title"], styles["Heading1"]),
             Paragraph(payload["experiment"]["name"], styles["Heading2"]), Spacer(1, 6*mm)]
    exp = payload["experiment"]
    cover = [["Report ID", payload.get("report_id", "Generated")], ["Experiment ID", exp["id"]],
             ["Simulation", exp["simulation"]], ["Status", exp["status"]],
             ["Generated", payload.get("generated_at", "")], ["Experiment version", str(exp["version"])]]
    table = Table(cover, colWidths=[42*mm, 112*mm])
    table.setStyle(TableStyle([("BACKGROUND", (0,0),(0,-1), colors.HexColor("#EEF2FF")),
                               ("TEXTCOLOR", (0,0),(-1,-1), colors.HexColor("#172033")),
                               ("GRID", (0,0),(-1,-1), .35, colors.HexColor("#CBD5E1")),
                               ("FONTNAME", (0,0),(0,-1), "Helvetica-Bold"), ("FONTSIZE", (0,0),(-1,-1), 8),
                               ("PADDING", (0,0),(-1,-1), 7)]))
    story += [table, Spacer(1, 10*mm), Paragraph(payload["data_provenance"], styles["ArcSmall"]), PageBreak()]

    def section(key: str, heading: str, content):
        if key in payload["sections"]:
            story.append(Paragraph(heading, styles["ArcH"]))
            story.extend(content)

    section("executive_summary", "1. Executive Summary", [
        Paragraph(f"This report documents the <b>{exp['simulation']}</b> experiment <b>{exp['name']}</b>. "
                  f"The saved experiment status is <b>{exp['status']}</b>. "
                  f"{len(payload['metrics'])} scalar result fields and {len(payload['executions'])} execution records were available at generation time.", styles["BodyText"]),
        Spacer(1, 4*mm)])
    section("background", "2. Research Background", [Paragraph(exp.get("description") or "No research background was supplied in the experiment record.", styles["BodyText"])])
    section("methodology", "3. Methodology and Data Provenance", [
        Paragraph("The report reads the persisted experiment definition and execution snapshots. It does not rerun the simulation. "
                  "Values represent ARCHEX software simulation outputs, not measurements collected from physical processor hardware.", styles["BodyText"]),
        Paragraph(f"Engine: {exp['simulation']} · Category: {exp['category']} · Detail level: {payload['detail_level']}", styles["ArcSmall"])])
    config_text = (json.dumps(exp["configuration"], ensure_ascii=False, indent=2)
                   if payload["detail_level"] == "technical" else
                   json.dumps({"top_level_keys": list(exp["configuration"].keys()) if isinstance(exp["configuration"], dict) else [],
                               "configuration_available": bool(exp["configuration"])}, ensure_ascii=False, indent=2))
    section("configuration", "4. Experiment Configuration", [
        Paragraph("Configuration snapshot" if payload["detail_level"] == "technical" else "Configuration overview", styles["Heading3"]),
        Paragraph("<font name='Courier'>" + config_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>").replace(" ", "&nbsp;") + "</font>", styles["ArcSmall"]),
        Paragraph("Tags: " + (", ".join(exp.get("tags", [])) or "None"), styles["ArcSmall"])])
    metric_rows = [["Metric", "Value"]] + [[str(k), str(v)] for k, v in list(payload["metrics"].items())[:100]]
    if len(metric_rows) > 1:
        metric_table = Table(metric_rows, colWidths=[100*mm, 54*mm], repeatRows=1)
        metric_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#312E81")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F8FAFC")]),
            ("FONTSIZE",(0,0),(-1,-1),7),("PADDING",(0,0),(-1,-1),5)]))
        result_content = [metric_table]
        numeric = [(k, v) for k, v in payload["metrics"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)][:8]
        if numeric:
            drawing = Drawing(155*mm, 62*mm)
            chart = VerticalBarChart(); chart.x=8; chart.y=8; chart.height=48*mm; chart.width=140*mm
            chart.data = [[float(v) for _,v in numeric]]; chart.categoryAxis.categoryNames = [k[:18] for k,_ in numeric]
            chart.categoryAxis.labels.fontSize = 6; chart.valueAxis.labels.fontSize = 7
            chart.bars[0].fillColor = colors.HexColor("#8B5CF6"); chart.valueAxis.valueMin = min(0, min(float(v) for _,v in numeric))
            drawing.add(chart); result_content += [Spacer(1,4*mm), drawing]
    else:
        result_content = [Paragraph("No scalar result metrics were present in the saved result snapshot. The report intentionally does not substitute estimated values.", styles["BodyText"])]
    if payload["executions"]:
        rows = [["Execution", "Status", "Duration (ms)", "Software"]] + [[e["id"][:8],e["status"],str(e["duration_ms"] if e["duration_ms"] is not None else "—"),e["software_version"]] for e in payload["executions"]]
        et = Table(rows, colWidths=[35*mm,30*mm,42*mm,47*mm], repeatRows=1)
        et.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0F766E")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
                                ("GRID",(0,0),(-1,-1),.3,colors.HexColor("#CBD5E1")),("FONTSIZE",(0,0),(-1,-1),7),("PADDING",(0,0),(-1,-1),5)]))
        result_content += [Spacer(1,5*mm), Paragraph("Execution history", styles["Heading3"]), et]
    section("results", "5. Results and Execution Evidence", result_content)
    section("discussion", "6. Discussion and Limitations", [
        Paragraph("Interpretation is limited to the saved configuration and outputs shown in this report. "
                  "A missing metric indicates that the selected experiment did not persist that value; it must not be interpreted as zero. "
                  "Cross-engine comparisons are not included because metric definitions may differ.", styles["BodyText"]),
        Paragraph("Research notes: " + (exp.get("notes") or "No research notes were supplied."), styles["ArcSmall"])])
    section("conclusion", "7. Conclusion", [Paragraph("This document provides a traceable snapshot of the selected ARCHEX experiment. "
                  "Further conclusions should be based on the complete simulation methodology, repeated runs where appropriate, and independently validated evidence.", styles["BodyText"])])
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def _footer(canvas, doc):
    canvas.saveState(); canvas.setStrokeColor(colors.HexColor("#CBD5E1")); canvas.line(18*mm, 14*mm, 192*mm, 14*mm)
    canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(18*mm, 9*mm, "ARCHEX · Simulation research report")
    canvas.drawRightString(192*mm, 9*mm, f"Page {doc.page}"); canvas.restoreState()


def create_file(report_type: str, payload: dict) -> tuple[str, bytes]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_id = payload["report_id"]
    ext = {"pdf":"pdf", "csv":"csv", "json":"json"}[report_type]
    filename = f"{report_id}.{ext}"
    if report_type == "pdf":
        content = make_pdf(payload)
    elif report_type == "csv":
        content = make_csv(payload)
    else:
        content = (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    path = REPORT_DIR / filename
    temp = REPORT_DIR / f".{filename}.tmp"
    temp.write_bytes(content); temp.replace(path)
    return filename, content


def safe_report_path(filename: str) -> Path:
    if not re.fullmatch(r"[0-9a-f-]{36}\.(pdf|csv|json)", filename):
        raise ValueError("Invalid report file reference")
    path = (REPORT_DIR / filename).resolve()
    if path.parent != REPORT_DIR.resolve():
        raise ValueError("Invalid report file path")
    return path
