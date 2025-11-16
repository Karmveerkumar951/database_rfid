import os
import json
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_PATH = os.path.join(BASE, "database", "products.json")
RFID_PATH = os.path.join(BASE, "database", "rfid.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.route("/check_all", methods=["GET"])
def check_all():
    # Load both files
    products = load_json(PRODUCTS_PATH)
    rfid = load_json(RFID_PATH)

    # Make fast EPC -> product lookup
    product_map = {p["EPC"]: p for p in products}

    results = []

    for item in rfid:
        epc = item.get("EPC")
        dev_detected = item.get("Dev")  # EXACT key from rfid.json

        product = product_map.get(epc)

        if product is None:
            results.append({
                "EPC": epc,
                "DEV_detected": dev_detected,
                "status": "UNKNOWN",
                "reason": "Tag not found in products.json"
            })
            continue

        expected_dev = product["DEV"]

        if expected_dev == dev_detected:
            results.append({
                "EPC": epc,
                "product": product,
                "DEV_detected": dev_detected,
                "status": "OK",
                "reason": "Product is in correct zone"
            })
        else:
            results.append({
                "EPC": epc,
                "product": product,
                "DEV_detected": dev_detected,
                "status": "MISPLACED",
                "reason": f"Expected {expected_dev}, but found {dev_detected}"
            })

    return jsonify(results), 200


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "RFID product locator API running",
        "endpoints": ["/check_all"]
    })


if __name__ == "__main__":
    print("Using products:", PRODUCTS_PATH)
    print("Using rfid:", RFID_PATH)
    app.run(host="0.0.0.0", port=5000, debug=True)
