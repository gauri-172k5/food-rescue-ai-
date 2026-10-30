"""
FoodRescue AI - Surplus Food Connector
Backend: Python + Flask. Calls the TinyFish web agent to discover
potential donation partners on live public websites.
The API key lives ONLY here (server side), never in the browser.
"""
import json
import os
import re

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app)

TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY", "").strip()
DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1" or not TINYFISH_API_KEY
TINYFISH_RUN_URL = "https://agent.tinyfish.ai/v1/automation/run"

REQUIRED_FIELDS = ["name", "address", "phone", "email", "website",
                   "accepted_items", "instructions", "source_url"]


# ---------- 1. Build the task for TinyFish ----------
def build_goal(d):
    return f"""
You are helping a food donor find organisations that may accept surplus food.

Donor details:
- Location: {d['location']}
- Food type: {d['food_type']}
- Quantity: {d['quantity']}
- Available for pickup: {d['availability']}

Task:
1. Search for food banks, community kitchens, shelters and charities near {d['location']}
   that accept donated food.
2. Open each organisation's PUBLIC website and read its donation / contact page.
3. Return up to 5 organisations as JSON ONLY, in exactly this format:
{{"organisations": [{{
  "name": "", "address": "", "phone": "", "email": "", "website": "",
  "accepted_items": "", "food_safety_notes": "", "instructions": "",
  "source_url": "URL of the page where you found this info"
}}]}}
Rules: use only information visible on the websites. If a field is not found,
use an empty string. Never invent phone numbers, emails or addresses.
""".strip()


# ---------- 2. Call TinyFish ----------
def call_tinyfish(goal):
    resp = requests.post(
        TINYFISH_RUN_URL,
        headers={"X-API-Key": TINYFISH_API_KEY, "Content-Type": "application/json"},
        json={"url": "https://www.google.com", "goal": goal},
        timeout=300,  # web agents can take a while
    )
    resp.raise_for_status()
    return resp.json()


# ---------- 3. Clean / structure the response ----------
def extract_orgs(run):
    result = run.get("result")
    # Result may be a dict, a JSON string, or wrapped as {"result": ...}
    if isinstance(result, dict) and "result" in result and "organisations" not in result:
        result = result["result"]
    if isinstance(result, str):
        match = re.search(r"\{.*\}|\[.*\]", result, re.S)
        try:
            result = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            result = {}
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return result.get("organisations") or result.get("organizations") or []
    return []


def structure(orgs):
    cleaned = []
    for o in orgs:
        if not isinstance(o, dict) or not o.get("name"):
            continue
        item = {k: str(o.get(k, "") or "").strip() for k in REQUIRED_FIELDS}
        item["food_safety_notes"] = str(o.get("food_safety_notes", "") or "").strip()
        item["missing_fields"] = [k for k in REQUIRED_FIELDS if not item[k]]
        item["verified_source"] = bool(item["source_url"])
        cleaned.append(item)
    return cleaned


def demo_results():
    return [
        {"name": "Community Food Bank (DEMO)", "address": "12 Main Road", "phone": "000-000-0001",
         "email": "info@example.org", "website": "https://example.org",
         "accepted_items": "Packaged food, bakery items", "food_safety_notes": "Must be within date",
         "instructions": "Call before dropping off", "source_url": "https://example.org/donate",
         "missing_fields": [], "verified_source": True},
        {"name": "Neighbourhood Kitchen (DEMO)", "address": "45 Lake Street", "phone": "",
         "email": "", "website": "https://example.com",
         "accepted_items": "Cooked meals (same day)", "food_safety_notes": "",
         "instructions": "Collection by arrangement", "source_url": "https://example.com/give",
         "missing_fields": ["phone", "email"], "verified_source": True},
    ]


# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("index.html", demo=DEMO_MODE)


@app.route("/api/search", methods=["POST"])
def search():
    d = request.get_json(silent=True) or {}
    for field in ["location", "food_type", "quantity", "availability"]:
        if not str(d.get(field, "")).strip():
            return jsonify({"error": f"Please fill in: {field.replace('_', ' ')}"}), 400

    if DEMO_MODE:
        return jsonify({"demo": True, "results": demo_results()})

    try:
        run = call_tinyfish(build_goal(d))
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 500
        msg = "Invalid or missing TinyFish API key." if code == 401 else f"TinyFish error ({code})."
        return jsonify({"error": msg}), 502
    except requests.RequestException:
        return jsonify({"error": "Could not reach TinyFish. Try again."}), 502

    if run.get("status") == "FAILED":
        return jsonify({"error": "The web agent could not finish the search."}), 502

    return jsonify({"demo": False, "results": structure(extract_orgs(run))})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
