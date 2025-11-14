from flask import Flask, jsonify
from pathlib import Path
import json
import os
from datetime import datetime

app = Flask(__name__)

PRODUCTS_PATH = Path(os.path.normpath("database/products.json"))
RFID_PATH = Path(os.path.normpath("database/rfid.json"))

# device -> zone map (optional, kept for completeness)
DEVICE_ZONE_MAP = {
    "087C002B": "Zone A",
    "087C002D": "Zone B",
    "087C002E": "Zone C",
}

def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        app.logger.error("Failed to load %s: %s", path, e)
        return []

def normalize_epc(epc):
    if not epc:
        return None
    return str(epc).strip().upper()

def parse_time(ts):
    # Expect format "YYYY-MM-DD HH:MM:SS" per your sample.
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        # If parsing fails, return None (such reads will be considered older)
        return None

@app.route("/products/misplaced", methods=["GET"])
def products_with_misplaced_flag():
    products = load_json(PRODUCTS_PATH)
    rfid_reads = load_json(RFID_PATH)

    # Build latest-read-by-epc using nested loops: outer rfid_reads, inner products.
    # For each read, we check every product's EPC candidates to see if it matches.
    latest_read_for_epc = {}  # epc -> (datetime, read_dict)

    for read in rfid_reads:  # outer loop (rfid)
        read_epc_raw = read.get("EPC") or read.get("epc")
        read_epc = normalize_epc(read_epc_raw)
        if not read_epc:
            continue

        read_time = parse_time(read.get("Time") or read.get("time"))
        # If time parse failed, treat as very old (skip updating if existing newer)
        if read_time is None:
            # use minimal time so it's not considered latest if a valid time exists
            read_time = datetime.min

        # Inner loop: test each product for matching EPC field(s)
        for prod in products:
            # get product epc (try common keys)
            prod_epc_raw = prod.get("EPC") or prod.get("epc") or prod.get("RFID_EPC") or prod.get("rfid_epc")
            prod_epc = normalize_epc(prod_epc_raw)
            if not prod_epc:
                continue

            if prod_epc == read_epc:
                # matched product <-> read: update latest_read_for_epc if this read is newer
                prev = latest_read_for_epc.get(read_epc)
                if prev is None or read_time > prev[0]:
                    latest_read_for_epc[read_epc] = (read_time, read)
                # continue inner loop to allow multiple products with same EPC (rare)
    
    # Now produce updated products list with Misplaced flag
    updated_products = []
    for prod in products:
        prod_copy = dict(prod)  # shallow copy so we don't mutate original structure
        prod_epc = normalize_epc(prod.get("EPC") or prod.get("epc"))
        expected_device = prod.get("RFID") or prod.get("rfid")  # expected reader/device

        if prod_epc and prod_epc in latest_read_for_epc:
            latest_time, latest_read = latest_read_for_epc[prod_epc]
            detected_device = latest_read.get("Dev") or latest_read.get("dev")
            # strict equality compare devices as strings
            misplaced = (str(expected_device) != str(detected_device))
            # add optional extra info
            prod_copy["LastSeen"] = latest_read.get("Time")
            prod_copy["DetectedDevice"] = detected_device
            prod_copy["Misplaced"] = bool(misplaced)
        else:
            # No read found for this product's EPC (or product has no EPC). Per policy set false.
            prod_copy["LastSeen"] = None
            prod_copy["DetectedDevice"] = None
            prod_copy["Misplaced"] = False

        updated_products.append(prod_copy)

    return jsonify(updated_products)

if __name__ == "__main__":
    app.logger.info("Products path: %s", PRODUCTS_PATH.resolve())
    app.logger.info("RFID path: %s", RFID_PATH.resolve())
    app.run(debug=True, host="0.0.0.0", port=5000)
