import os
import json
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE, "database")

PRODUCTS_PATH = os.path.join(DATABASE_DIR, "products.json")
RFID_PATH = os.path.join(DATABASE_DIR, "rfid.json")
STAFF_PATH = os.path.join(DATABASE_DIR, "staff.json")


# ---------------------------
# JSON LOADER (safe)
# ---------------------------
def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading {path}: {e}")
        return []


# ---------------------------
# PRODUCTS ENDPOINT
# ---------------------------
@app.route("/products", methods=["GET"])
def get_products():
    """
    Returns canonical products.json as-is.
    """
    products = load_json(PRODUCTS_PATH)
    if isinstance(products, list):
        return jsonify(products), 200
    return jsonify([]), 200


# ---------------------------
# STAFF ENDPOINT
# ---------------------------
@app.route("/staff", methods=["GET"])
def get_staff():
    """
    Returns clean staff list from staff.json
    """
    staff = load_json(STAFF_PATH)

    if isinstance(staff, dict) and isinstance(staff.get("staff"), list):
        return jsonify(staff["staff"]), 200

    if isinstance(staff, list):
        return jsonify(staff), 200

    return jsonify([]), 200


# ---------------------------
# CHECK_ALL — CLEAN + MODE 1
# ---------------------------
@app.route("/check_all", methods=["GET"])
def check_all():
    """
    MODE 1 — Last-read wins
    Produces clean flattened response:
    {
        "DEV_DETECTED": "...",
        "EPC": "...",
        "DEV": "...",
        "IMAGE": "...",
        "NAME": "...",
        "SKU": "...",
        "STATUS": "...",
        "ZONE_STATUS": true/false
    }
    """
    products = load_json(PRODUCTS_PATH)
    rfid_reads = load_json(RFID_PATH)

    # ------------------------------------
    # Build EPC → product lookup table
    # ------------------------------------
    product_map = {}
    for p in products:
        epc = p.get("EPC") or p.get("epc")
        if epc:
            product_map[str(epc).strip()] = p

    results = []

    # ------------------------------------
    # For every RFID read (last-read wins)
    # ------------------------------------
    for item in rfid_reads:
        raw_epc = item.get("EPC") or item.get("epc") or ""
        epc = str(raw_epc).strip()

        dev_detected = (
            item.get("Dev")
            or item.get("DEV")
            or item.get("dev")
            or item.get("Device")
        )

        product = product_map.get(epc)

        # ------------------------------------
        # Case 1: EPC not found in product list
        # ------------------------------------
        if not product:
            results.append({
                "DEV_DETECTED": dev_detected,
                "EPC": epc,
                "DEV": None,
                "IMAGE": None,
                "NAME": None,
                "SKU": None,
                "STATUS": "unknown",
                "ZONE_STATUS": False
            })
            continue

        # ------------------------------------
        # Case 2: Product found → Compare zones
        # ------------------------------------
        expected_dev = (
            product.get("DEV")
            or product.get("Dev")
            or product.get("dev")
            or product.get("defaultZone")
            or product.get("ZoneName")
        )

        # Normalize both
        exp_norm = str(expected_dev).strip().lower() if expected_dev else None
        det_norm = str(dev_detected).strip().lower() if dev_detected else None

        zone_status = (exp_norm == det_norm) if (exp_norm and det_norm) else False

        results.append({
            "DEV_DETECTED": dev_detected,
            "EPC": epc,
            "DEV": expected_dev,
            "IMAGE": product.get("IMAGE"),
            "NAME": product.get("NAME"),
            "SKU": product.get("SKU"),
            "STATUS": product.get("STATUS"),
            "ZONE_STATUS": zone_status
        })

    return jsonify(results), 200


# ---------------------------
# HOME ENDPOINT
# ---------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "RFID API running",
        "endpoints": [
            "/products",
            "/staff",
            "/check_all"
        ]
    }), 200


# ---------------------------
# RUN SERVER
# ---------------------------
if __name__ == "__main__":
    print("Using database:", DATABASE_DIR)
    app.run(host="0.0.0.0", port=5000, debug=True)
