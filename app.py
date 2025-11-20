# api.py
import os
import json
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE, "database")

PRODUCTS_PATH = os.path.join(DATABASE_DIR, "products.json")
RFID_PATH = os.path.join(DATABASE_DIR, "rfid.json")
STAFF_PATH = os.path.join(DATABASE_DIR, "staff.json")


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        app.logger.error(f"Error loading {path}: {e}")
        return []


def parse_time(tstr):
    """
    Try parsing a few common timestamp formats. Return a datetime or None.
    """
    if not tstr:
        return None
    if isinstance(tstr, (int, float)):
        try:
            return datetime.fromtimestamp(float(tstr))
        except Exception:
            return None
    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(tstr, fmt)
        except Exception:
            continue
    # last-resort: try isoformat
    try:
        return datetime.fromisoformat(tstr)
    except Exception:
        return None


@app.route("/products", methods=["GET"])
def get_products():
    """
    Return canonical products.json list with optional LAST_SEEN and LAST_DEV added
    when RFID reads exist for that EPC. Preserves all products (no dedupe).
    """
    products = load_json(PRODUCTS_PATH)
    rfid_reads = load_json(RFID_PATH)

    # Build latest read per EPC
    latest_by_epc = {}
    for r in rfid_reads:
        epc = str(r.get("EPC") or r.get("epc") or "").strip()
        if not epc:
            continue
        parsed = parse_time(r.get("Time") or r.get("LastSeen") or r.get("LAST_SEEN") or r.get("Timestamp") or None)
        cur = latest_by_epc.get(epc)
        if not cur:
            latest_by_epc[epc] = {**r, "_parsed_time": parsed}
        else:
            cur_t = cur.get("_parsed_time")
            if parsed and (not cur_t or parsed > cur_t):
                latest_by_epc[epc] = {**r, "_parsed_time": parsed}

    enriched = []
    for p in products:
        entry = dict(p)  # shallow copy
        epc = str(p.get("EPC") or p.get("epc") or "").strip()
        lr = latest_by_epc.get(epc)
        if lr:
            entry["LAST_SEEN"] = lr.get("Time") or lr.get("LastSeen") or lr.get("LAST_SEEN")
            entry["LAST_DEV"] = lr.get("Dev") or lr.get("DEV") or lr.get("dev") or lr.get("Device")
        else:
            entry["LAST_SEEN"] = None
            entry["LAST_DEV"] = None
        enriched.append(entry)

    return jsonify(enriched), 200


@app.route("/staff", methods=["GET"])
def get_staff():
    staff = load_json(STAFF_PATH)
    if isinstance(staff, dict) and isinstance(staff.get("staff"), list):
        return jsonify(staff["staff"]), 200
    if isinstance(staff, list):
        return jsonify(staff), 200
    return jsonify([]), 200


@app.route("/check_all", methods=["GET"])
def check_all():
    """
    Returns a deduped list of RFID reads (one per EPC, latest read wins).
    If a product matches that EPC, include product details. Compute ZONE_STATUS
    comparing expected DEV vs detected DEV. Return LAST_SEEN/time too.
    """
    products = load_json(PRODUCTS_PATH)
    rfid_reads = load_json(RFID_PATH)

    # Build product lookup by EPC (note: multiple products could share same EPC in raw data)
    product_map = {}
    for p in products:
        epc = str(p.get("EPC") or p.get("epc") or "").strip()
        if not epc:
            continue
        product_map.setdefault(epc, []).append(p)

    # Build latest read per EPC
    latest_by_epc = {}
    for r in rfid_reads:
        epc = str(r.get("EPC") or r.get("epc") or "").strip()
        if not epc:
            continue
        parsed = parse_time(r.get("Time") or r.get("LastSeen") or r.get("LAST_SEEN") or r.get("Timestamp") or None)
        cur = latest_by_epc.get(epc)
        if not cur:
            latest_by_epc[epc] = {**r, "_parsed_time": parsed}
        else:
            cur_t = cur.get("_parsed_time")
            if parsed and (not cur_t or parsed > cur_t):
                latest_by_epc[epc] = {**r, "_parsed_time": parsed}

    results = []
    for epc, read in latest_by_epc.items():
        dev_detected = read.get("Dev") or read.get("DEV") or read.get("dev") or read.get("Device")
        last_seen = read.get("Time") or read.get("LastSeen") or read.get("LAST_SEEN") or read.get("Timestamp")
        product_candidates = product_map.get(epc, [])
        # If multiple product entries exist for same EPC in products.json, pick latest by product-level timestamp if present,
        # otherwise pick first — the main dedupe is from RFID reads (latest read wins)
        product = product_candidates[0] if product_candidates else None

        if not product:
            results.append({
                "DEV_DETECTED": dev_detected,
                "EPC": epc,
                "DEV": None,
                "IMAGE": None,
                "NAME": None,
                "SKU": None,
                "PRODUCT_STATUS": None,
                "STATUS": "unknown",
                "ZONE_STATUS": False,
                "LAST_SEEN": last_seen
            })
            continue

        expected_dev = (
            product.get("DEV")
            or product.get("Dev")
            or product.get("dev")
            or product.get("defaultZone")
            or product.get("ZoneName")
            or product.get("Zone")
        )

        exp_norm = str(expected_dev).strip().lower() if expected_dev else None
        det_norm = str(dev_detected).strip().lower() if dev_detected else None
        zone_status = (exp_norm == det_norm) if (exp_norm and det_norm) else False

        results.append({
            "DEV_DETECTED": dev_detected,
            "EPC": epc,
            "DEV": expected_dev,
            "IMAGE": product.get("IMAGE") or product.get("Image") or None,
            "NAME": product.get("NAME") or product.get("Name") or product.get("name"),
            "SKU": product.get("SKU") or product.get("Id") or product.get("id"),
            "PRODUCT_STATUS": product.get("STATUS") or product.get("Status") or product.get("status"),
            "STATUS": "In Zone" if zone_status else "Misplaced",
            "ZONE_STATUS": zone_status,
            "LAST_SEEN": last_seen
        })

    return jsonify(results), 200


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "RFID API running",
        "endpoints": ["/products", "/staff", "/check_all"]
    }), 200


if __name__ == "__main__":
    print("Using database:", DATABASE_DIR)
    app.run(host="0.0.0.0", port=5000, debug=True)
