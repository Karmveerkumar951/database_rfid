import os
import json
from datetime import datetime
from flask import Flask, jsonify, make_response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE, "database")

PRODUCTS_PATH = os.path.join(DATABASE_DIR, "products.json")
RFID_PATH = os.path.join(DATABASE_DIR, "rfid.json")
STAFF_PATH = os.path.join(DATABASE_DIR, "staff.json")

# Map DEV codes to single characters
DEV_TO_CHAR = {
    "087C002B": "A",
    "087C002D": "B",
    "087C002E": "C",
    # also accept lowercase if any
    "087c002b": "A",
    "087c002d": "B",
    "087c002e": "C",
}


def dev_code_to_char(code):
    if code is None:
        return ""
    s = str(code).strip()
    if len(s) == 1 and s.isalpha():
        return s.upper()
    return DEV_TO_CHAR.get(s, "")


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as jde:
        app.logger.error(f"JSON decode error reading {path}: {jde}")
        # Return [] so endpoint keeps working during partial writes
        return []
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


def make_nocache_response(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/products", methods=["GET"])
def get_products():
    """
    Return canonical products.json list with optional LAST_SEEN and LAST_DEV added
    when RFID reads exist for that EPC.
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
            raw_dev = lr.get("Dev") or lr.get("DEV") or lr.get("dev") or lr.get("Device") or ""
            entry["_RAW_LAST_DEV"] = raw_dev
            entry["LAST_DEV"] = dev_code_to_char(raw_dev) or None
        else:
            entry["LAST_SEEN"] = None
            entry["LAST_DEV"] = None
            entry["_RAW_LAST_DEV"] = None
        enriched.append(entry)

    return make_nocache_response(enriched)


@app.route("/staff", methods=["GET"])
def get_staff():
    staff = load_json(STAFF_PATH)
    if isinstance(staff, dict) and isinstance(staff.get("staff"), list):
        return make_nocache_response(staff["staff"])
    if isinstance(staff, list):
        return make_nocache_response(staff)
    return make_nocache_response([])


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
        raw_dev_detected = read.get("Dev") or read.get("DEV") or read.get("dev") or read.get("Device") or ""
        dev_detected_char = dev_code_to_char(raw_dev_detected) or None
        last_seen = read.get("Time") or read.get("LastSeen") or read.get("LAST_SEEN") or read.get("Timestamp")
        product_candidates = product_map.get(epc, [])
        product = product_candidates[0] if product_candidates else None

        if not product:
            results.append({
                "DEV_DETECTED": dev_detected_char,
                "_RAW_DEV_DETECTED": raw_dev_detected,
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

        # expected DEV from product: product.DEV (or Dev) — map to char
        raw_expected_dev = product.get("DEV") or product.get("Dev") or product.get("dev") or product.get("defaultZone") or product.get("ZoneName") or product.get("Zone") or ""
        expected_char = dev_code_to_char(raw_expected_dev) or None

        # zone status compare using normalized char values (case-insensitive by char)
        zone_status = False
        if expected_char and dev_detected_char:
            zone_status = (expected_char == dev_detected_char)

        results.append({
            "DEV_DETECTED": dev_detected_char,
            "_RAW_DEV_DETECTED": raw_dev_detected,
            "EPC": epc,
            "DEV": expected_char,
            "_RAW_DEV": raw_expected_dev,
            "IMAGE": product.get("IMAGE") or product.get("Image") or None,
            "NAME": product.get("NAME") or product.get("Name") or product.get("name"),
            "SKU": product.get("SKU") or product.get("Id") or product.get("id"),
            "PRODUCT_STATUS": product.get("STATUS") or product.get("Status") or product.get("status"),
            "STATUS": "In Zone" if zone_status else "Misplaced",
            "ZONE_STATUS": zone_status,
            "LAST_SEEN": last_seen
        })

    return make_nocache_response(results)


@app.route("/", methods=["GET"])
def home():
    return make_nocache_response({
        "message": "RFID API running",
        "endpoints": ["/products", "/staff", "/check_all"]
    })


if __name__ == "__main__":
    print("Using database:", DATABASE_DIR)
    app.run(host="0.0.0.0", port=5000, debug=True)
