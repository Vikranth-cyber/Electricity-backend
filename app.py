# app.py  –  VoltMetrics Flask Backend
# ======================================
# Run from the backend/ directory:
#   python app.py
#
# Endpoints:
#   POST /api/ocr     – Accept an uploaded image or PDF; return extracted units & amount
#   POST /api/report  – Accept JSON with units, amount, state, appliances; return full report

import logging
import os
from flask import Flask, request, jsonify
from flask_cors import CORS

from utils.ocr import extract_text
from utils.extractor import extract_bill_data
from utils.calculator import calculate_breakdown, build_summary
from utils.ranking import get_top_appliances
from utils.suggestions import generate_suggestions
from utils.tariff import SUPPORTED_STATES

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Allow all origins in development.  Restrict to your frontend URL in production:
#   CORS(app, origins=["http://localhost:5173"])
CORS(app)

# Max upload size: 16 MB
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


# ---------------------------------------------------------------------------
# Helper: build a standard error response
# ---------------------------------------------------------------------------

def _error(message: str, status: int = 400):
    return jsonify({"error": message}), status


# ---------------------------------------------------------------------------
# POST /api/ocr
# ---------------------------------------------------------------------------

@app.route("/api/ocr", methods=["POST"])
def ocr_endpoint():
    """
    Accept a multipart/form-data upload with a single file field named 'file'.
    Runs OCR on the uploaded electricity bill (image or PDF) and returns
    the extracted units and amount.

    Request:
        Content-Type: multipart/form-data
        file: <image file or PDF>

    Response 200:
        {
            "units":  <float | null>,
            "amount": <float | null>,
            "raw_text_preview": <str>   // first 300 chars, for debugging
        }

    Response 400:
        { "error": "<description>" }
    """
    if "file" not in request.files:
        return _error("No file part in the request. Use field name 'file'.")

    uploaded_file = request.files["file"]

    if uploaded_file.filename == "":
        return _error("No file selected.")

    filename = uploaded_file.filename
    logger.info("OCR request received: %s", filename)

    try:
        file_bytes = uploaded_file.read()
    except Exception as exc:
        logger.error("Failed to read uploaded file: %s", exc)
        return _error("Failed to read uploaded file.")

    try:
        text = extract_text(file_bytes, filename)
    except ValueError as exc:
        return _error(str(exc))
    except RuntimeError as exc:
        logger.error("OCR error: %s", exc)
        return _error(f"OCR processing failed: {exc}", status=500)

    data = extract_bill_data(text)

    logger.info(
        "OCR complete – units: %s, amount: %s",
        data.get("units"),
        data.get("amount"),
    )

    return jsonify({
        "units":            data["units"],
        "amount":           data["amount"],
        "raw_text_preview": text[:300],
    })


# ---------------------------------------------------------------------------
# POST /api/report
# ---------------------------------------------------------------------------

@app.route("/api/report", methods=["POST"])
def report_endpoint():
    """
    Accept JSON describing the bill and appliances; return a full analysis report.

    Request JSON:
        {
            "units":    <number>,           // total kWh from bill
            "amount":   <number>,           // total bill amount (₹)
            "state":    <string>,           // one of the supported states
            "appliances": [
                {
                    "name":         <string>,
                    "quantity":     <int>,
                    "hours_per_day": <float | null>  // null = continuous (24 h)
                },
                ...
            ]
        }

    Response 200:
        {
            "summary": {
                "total_units":       float,
                "total_amount":      float,
                "state":             str,
                "rate_per_unit":     float,
                "appliances_count":  int,
                "recalculated_cost": float
            },
            "breakdown": [
                {
                    "name":             str,
                    "wattage":          int,
                    "quantity":         int,
                    "hours_per_day":    float,
                    "estimated_units":  float,
                    "units":            float,
                    "cost":             float,
                    "percentage":       float
                },
                ...
            ],
            "top3": [
                {
                    "rank":        int,
                    "name":        str,
                    "units":       float,
                    "cost":        float,
                    "percentage":  float,
                    ...
                },
                ...
            ],
            "suggestions": [ "<tip string>", ... ],
            "normalization_warning": <str | null>,
            "estimated_total_kwh":   float
        }

    Response 400/422:
        { "error": "<description>" }
    """
    body = request.get_json(silent=True)

    if not body:
        return _error("Request body must be valid JSON.")

    # -- Validate required fields --------------------------------------------
    try:
        total_units  = float(body["units"])
        total_amount = float(body["amount"])
    except (KeyError, TypeError, ValueError):
        return _error("'units' and 'amount' must be present and numeric.")

    if total_units <= 0:
        return _error("'units' must be greater than 0.")
    if total_amount <= 0:
        return _error("'amount' must be greater than 0.")

    state = body.get("state", "").strip()
    if not state:
        return _error("'state' is required.")
    if state not in SUPPORTED_STATES:
        return _error(
            f"State '{state}' is not supported. "
            f"Supported: {', '.join(SUPPORTED_STATES)}"
        )

    appliances = body.get("appliances", [])
    if not isinstance(appliances, list) or len(appliances) == 0:
        return _error("'appliances' must be a non-empty list.")

    # Sanitise each appliance entry
    clean_appliances = []
    for i, item in enumerate(appliances):
        if not isinstance(item, dict):
            return _error(f"appliances[{i}] must be an object.")
        name = str(item.get("name", "")).strip()
        if not name:
            return _error(f"appliances[{i}] is missing 'name'.")

        try:
            quantity = max(1, int(item.get("quantity") or 1))
        except (TypeError, ValueError):
            return _error(f"appliances[{i}].quantity must be a positive integer.")

        hours_raw = item.get("hours_per_day")
        if hours_raw is not None:
            try:
                hours = float(hours_raw)
                if not (0.0 <= hours <= 24.0):
                    return _error(f"appliances[{i}].hours_per_day must be between 0 and 24.")
            except (TypeError, ValueError):
                return _error(f"appliances[{i}].hours_per_day must be a number or null.")
        else:
            hours = None

        clean_appliances.append({
            "name":         name,
            "quantity":     quantity,
            "hours_per_day": hours,
        })

    logger.info(
        "Report request – state: %s, units: %.2f, amount: %.2f, appliances: %d",
        state, total_units, total_amount, len(clean_appliances),
    )

    # -- Core calculations ---------------------------------------------------
    try:
        calc_result = calculate_breakdown(total_units, total_amount, clean_appliances, state)

        breakdown_list        = calc_result["breakdown"]
        normalization_warning = calc_result["normalization_warning"]
        estimated_total_kwh   = calc_result["estimated_total_kwh"]

        summary     = build_summary(total_units, total_amount, state, breakdown_list)
        top3        = get_top_appliances(breakdown_list, n=3)
        suggestions = generate_suggestions(breakdown_list, total_units)
    except ValueError as exc:
        return _error(str(exc), status=422)
    except Exception as exc:
        logger.exception("Unexpected error during report calculation: %s", exc)
        return _error("An internal error occurred. Please try again.", status=500)

    return jsonify({
        "summary":               summary,
        "breakdown":             breakdown_list,
        "top3":                  top3,
        "suggestions":           suggestions,
        "normalization_warning": normalization_warning,
        "estimated_total_kwh":   estimated_total_kwh,
    })


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    """Simple liveness check used by the frontend on startup."""
    return jsonify({"status": "ok", "supported_states": SUPPORTED_STATES})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    logger.info("Starting VoltMetrics backend on port %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)