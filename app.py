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


def load_json(path):
    """Load JSON from disk. Return [] on error and log the problem."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        app.logger.warning("File not found: %s", path)
        return []
    except json.JSONDecodeError as e:
        app.logger.error("JSON decode error in %s: %s", path, e)
        return []
    except Exception as e:
        app.logger.exception("Unexpected error loading JSON %s: %s", path, e)
        return []


@app.route("/check_all", methods=["GET"])
def check_all():
    """
    Existing behavior:
    - Load products.json and rfid.json
    - For each tag in rfid.json, look up product by EPC and return a flat object
      including a boolean ZONE_STATUS (True if tag is where it should be).
    """
    products = load_json(PRODUCTS_PATH)
    rfid = load_json(RFID_PATH)

    # Fast lookup: EPC -> product
    product_map = {p.get("EPC"): p for p in products if p.get("EPC")}

    results = []

    for item in rfid:
        epc = item.get("EPC")
        dev_detected = item.get("Dev")  # EXACT key from rfid.json

        product = product_map.get(epc)

        if product is None:
            # Tag not found in products.json — return a flat object with unknowns and ZONE_STATUS False
            flat = {
                "DEV_DETECTED": dev_detected,
                "EPC": epc,
                "DEV": None,
                "IMAGE": None,
                "NAME": None,
                "SKU": None,
                "STATUS": "unknown",
                "ZONE_STATUS": False
            }
            flat.update({k.lower(): v for k, v in flat.items()})
            results.append(flat)
            continue

        expected_dev = product.get("DEV")
        zone_status = (expected_dev == dev_detected)

        # Build flat object: copy relevant product fields (use .get to avoid KeyError)
        flat = {
            "DEV_DETECTED": dev_detected,
            "EPC": epc,
            "DEV": product.get("DEV"),
            "IMAGE": product.get("IMAGE"),
            "NAME": product.get("NAME"),
            "SKU": product.get("SKU"),
            "STATUS": product.get("STATUS"),
            "ZONE_STATUS": zone_status
        }

        # Add lowercase variants for convenience/backwards compatibility
        flat.update({k.lower(): v for k, v in flat.items()})

        results.append(flat)

    return jsonify(results), 200


@app.route("/staff", methods=["GET"])
def get_staff():
    """
    Returns staff data read from database/staff.json.
    This is the single canonical staff endpoint (no /staff.json fallback).
    """
    staff = load_json(STAFF_PATH)
    # If staff is an object with a `staff` key, return that list
    if isinstance(staff, dict) and isinstance(staff.get("staff"), list):
        staff_list = staff["staff"]
    elif isinstance(staff, list):
        staff_list = staff
    else:
        staff_list = []

    return jsonify(staff_list), 200


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "RFID product locator API running",
        "endpoints": ["/check_all", "/staff"]
    })


if __name__ == "__main__":
    print("Using database directory:", DATABASE_DIR)
    print("Using products:", PRODUCTS_PATH)
    print("Using rfid:", RFID_PATH)
    print("Using staff:", STAFF_PATH)
    app.run(host="0.0.0.0", port=5000, debug=True)
