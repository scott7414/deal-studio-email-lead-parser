# =============================================
# Lead Parser API — Unified Output (Flask app)
# =============================================

from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re
from typing import Dict, Tuple

# ==============================
# ✅ Canonical output structure
# ==============================

BASE_OUTPUT: Dict = {
    "source": "",
    "contact": {
        "first_name": "",
        "last_name": "",
        "email": "",
        "phone": "",
        "best_time_to_contact": ""
    },
    "address": {
        "line1": "",
        "city": "",
        "state": "",
        "zip": "",
        "country": ""
    },
    "listing": {
        "headline": "",
        "ref_id": "",
        "listing_id": "",
        "listing_url": ""
    },
    "details": {
        "purchase_timeline": "",
        "investment_amount": "",
        "services_interested_in": "",
        "heard_about": ""
    },
    "comments": ""
}

def deep_merge(base: Dict, patch: Dict) -> Dict:
    out = {**base}
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = "" if v is None else v
    return out

# ==============================
# ✅ Utilities
# ==============================

def as_text(raw: str) -> str:
    """Return visible text. If HTML is present, strip tags and unescape entities."""
    if raw is None:
        return ""
    text = str(raw)
    if "<" in text and ">" in text:
        try:
            soup = BeautifulSoup(text, "html.parser")
            text = soup.get_text("\n")
        except Exception:
            pass
    # Normalize newlines, entities, NBSPs
    text = text.replace("\r", "")
    text = html.unescape(text)
    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    return text

def normalize_spaces(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    return s.strip()

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"[^\d+]", "", phone)
    m = re.match(r"^\+?1?(\d{10})$", digits)
    if m:
        d = m.group(1)
        return f"({d[0:3]}) {d[3:6]}-{d[6:]}"
    return phone.strip()

def kv_get_block(text: str, label: str) -> str:
    """
    Extract a value for a given label in flexible formats:
      - "Label: value"
      - "Label:\nvalue"
    Tolerates leading spaces and unicode colon "：". Case-insensitive.
    Returns the first non-empty match.
    """
    if not text or not label:
        return ""
    # Normalize unicode colon to ASCII
    norm = text.replace("：", ":")
    # Split lines for next-line capture
    lines = norm.split("\n")
    pat = re.compile(rf"^\s*{re.escape(label)}\s*:\s*(.*)$", re.IGNORECASE)
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        same = m.group(1).strip()
        if same:
            return same
        # Look to next non-empty line if same-line value is empty
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines):
            return lines[j].strip()
    return ""

def split_name(name: str) -> Tuple[str, str]:
    name = name.strip()
    if not name:
        return ("", "")
    if " " in name:
        first, last = name.split(" ", 1)
        return (first.strip(), last.strip())
    return (name, "")

# ==============================
# ✅ Comments cleaning
# ==============================

CONFIDENTIAL_PATTERNS = [
    r"(?is)\b(confidential(ity)? notice|this e-?mail.*confidential|intended only for the named recipient|do not disseminate|if you have received this.*in error).*",
    r"(?is)\b(terms of use and disclaimers apply).*",
    r"(?is)\b(be aware! online banking fraud).*",
]

DASH_CUTOFF = r"(?m)^\s*[-_]{2,}\s*$"

def extract_between_markers(text: str, start_label: str, end_regex: str = DASH_CUTOFF) -> str:
    if not text:
        return ""
    # Find the label anywhere in the text
    m = re.search(rf"(?is){re.escape(start_label)}\s*:\s*(.*)$", text)
    if not m:
        return ""
    start_idx = m.end(0)
    after = text[start_idx:]
    m2 = re.search(end_regex, after)
    if m2:
        after = after[:m2.start()]
    return after.strip()

def strip_confidential_and_excess(text: str) -> str:
    if not text:
        return ""
    text = re.split(DASH_CUTOFF, text)[0]
    for pat in CONFIDENTIAL_PATTERNS:
        text = re.sub(pat, "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()

def clean_comments(raw: str) -> str:
    txt = as_text(raw)
    txt = strip_confidential_and_excess(txt)
    return txt

# ==============================
# ✅ Source detection
# ==============================

def detect_source(text: str) -> str:
    t = text.lower()
    if "businessbrokernet listing number" in t or "businessbroker.net" in t:
        return "businessbroker"
    if "bizbuysell" in t or ("contact name:" in t and "purchase within:" in t):
        return "bizbuysell"
    if "businessesforsale.com" in t or "businesses for sale" in t:
        return "businessesforsale"
    if "murphy business" in t or "murphybusiness" in t or "murphybusiness.com" in t:
        return "murphy"
    return "unknown"

# ==============================
# ✅ BusinessBroker (HTML/Text)
# ==============================

def parse_businessbroker(text: str) -> Dict:
    listing_header = kv_get_block(text, "Listing Header")
    listing_id = kv_get_block(text, "BusinessBroker.net Listing Number")
    ref_id = kv_get_block(text, "Your Internal Listing Number")
    first = kv_get_block(text, "First Name")
    last = kv_get_block(text, "Last Name")
    email = kv_get_block(text, "Email")
    phone = normalize_phone(kv_get_block(text, "Phone"))
    address1 = kv_get_block(text, "Address")
    city = kv_get_block(text, "City")
    state = kv_get_block(text, "State")
    zipc = kv_get_block(text, "Zip")
    country = kv_get_block(text, "Country")
    best_time = kv_get_block(text, "Best Time to Contact")

    raw_comments = extract_between_markers(text, "Comments")
    comments = clean_comments(raw_comments)

    out = deep_merge(BASE_OUTPUT, {
        "source": "businessbroker",
        "contact": {
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone,
            "best_time_to_contact": best_time
        },
        "address": {
            "line1": address1,
            "city": city,
            "state": state,
            "zip": zipc,
            "country": country
        },
        "listing": {
            "headline": listing_header,
            "ref_id": ref_id,
            "listing_id": listing_id
        },
        "comments": comments
    })
    return out

# ==============================
# ✅ BizBuySell (HTML/Text)
# ==============================

def parse_bizbuysell(text: str) -> Dict:
    name = kv_get_block(text, "Contact Name")
    first, last = split_name(name)
    email = kv_get_block(text, "Email")
    phone = normalize_phone(kv_get_block(text, "Phone"))
    contact_zip = kv_get_block(text, "Contact Zip")
    invest = kv_get_block(text, "Investment Amount")
    purchase_timeline = kv_get_block(text, "Purchase Within")
    listing_id = kv_get_block(text, "Listing ID") or kv_get_block(text, "Listing Number")
    listing_url = kv_get_block(text, "Listing URL") or kv_get_block(text, "URL")
    headline = kv_get_block(text, "Listing Title") or kv_get_block(text, "Headline")
    ref_id = kv_get_block(text, "Reference ID") or kv_get_block(text, "Ref ID")

    raw_comments = extract_between_markers(text, "Comments")
    comments = clean_comments(raw_comments)

    out = deep_merge(BASE_OUTPUT, {
        "source": "bizbuysell",
        "contact": {
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone
        },
        "address": {
            "zip": contact_zip
        },
        "listing": {
            "headline": headline,
            "ref_id": ref_id,
            "listing_id": listing_id,
            "listing_url": listing_url
        },
        "details": {
            "investment_amount": invest,
            "purchase_timeline": purchase_timeline
        },
        "comments": comments
    })
    return out

# ==============================
# ✅ BusinessesForSale (HTML/Text)
# ==============================

def parse_businessesforsale(text: str) -> Dict:
    first = kv_get_block(text, "First Name")
    last = kv_get_block(text, "Last Name")
    if not (first or last):
        name = kv_get_block(text, "Name")
        first, last = split_name(name)

    email = kv_get_block(text, "Email")
    phone = normalize_phone(kv_get_block(text, "Phone"))
    address1 = kv_get_block(text, "Address")
    city = kv_get_block(text, "City")
    state = kv_get_block(text, "State/Region") or kv_get_block(text, "State")
    zipc = kv_get_block(text, "Zip/Postal") or kv_get_block(text, "Zip")
    country = kv_get_block(text, "Country")

    listing_id = kv_get_block(text, "Listing ID") or kv_get_block(text, "Ref")
    listing_url = kv_get_block(text, "Listing URL") or kv_get_block(text, "URL")
    headline = kv_get_block(text, "Headline") or kv_get_block(text, "Title")

    raw_comments = (
        extract_between_markers(text, "Comments")
        or extract_between_markers(text, "Message")
    )
    comments = clean_comments(raw_comments)

    out = deep_merge(BASE_OUTPUT, {
        "source": "businessesforsale",
        "contact": {
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone
        },
        "address": {
            "line1": address1,
            "city": city,
            "state": state,
            "zip": zipc,
            "country": country
        },
        "listing": {
            "headline": headline,
            "listing_id": listing_id,
            "listing_url": listing_url
        },
        "comments": comments
    })
    return out

# ==============================
# ✅ Murphy Business (HTML/Text)
# ==============================

def parse_murphy(text: str) -> Dict:
    first = kv_get_block(text, "First Name") or kv_get_block(text, "Firstname")
    last = kv_get_block(text, "Last Name") or kv_get_block(text, "Lastname")
    email = kv_get_block(text, "Email")
    phone = normalize_phone(kv_get_block(text, "Phone"))
    address1 = kv_get_block(text, "Address")
    city = kv_get_block(text, "City")
    state = kv_get_block(text, "State")
    zipc = kv_get_block(text, "Zip") or kv_get_block(text, "Postal Code")
    country = kv_get_block(text, "Country")

    listing_id = kv_get_block(text, "Listing ID") or kv_get_block(text, "Internal ID")
    ref_id = kv_get_block(text, "Reference ID") or kv_get_block(text, "Ref ID")
    headline = kv_get_block(text, "Listing Title") or kv_get_block(text, "Headline")
    listing_url = kv_get_block(text, "Listing URL") or kv_get_block(text, "URL")

    raw_comments = (
        extract_between_markers(text, "Comments")
        or extract_between_markers(text, "Message")
    )
    comments = clean_comments(raw_comments)

    out = deep_merge(BASE_OUTPUT, {
        "source": "murphy",
        "contact": {
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone
        },
        "address": {
            "line1": address1,
            "city": city,
            "state": state,
            "zip": zipc,
            "country": country
        },
        "listing": {
            "headline": headline,
            "ref_id": ref_id,
            "listing_id": listing_id,
            "listing_url": listing_url
        },
        "comments": comments
    })
    return out

# ==============================
# ✅ Unknown fallback
# ==============================

def parse_unknown(text: str) -> Dict:
    name = kv_get_block(text, "Name") or kv_get_block(text, "Contact Name")
    first, last = split_name(name)
    email = kv_get_block(text, "Email")
    phone = normalize_phone(kv_get_block(text, "Phone"))
    address1 = kv_get_block(text, "Address")
    city = kv_get_block(text, "City")
    state = kv_get_block(text, "State")
    zipc = kv_get_block(text, "Zip") or kv_get_block(text, "Postal") or kv_get_block(text, "Contact Zip")
    country = kv_get_block(text, "Country")

    listing_id = kv_get_block(text, "Listing ID") or kv_get_block(text, "Listing Number")
    ref_id = kv_get_block(text, "Reference ID") or kv_get_block(text, "Ref ID")
    headline = kv_get_block(text, "Listing Title") or kv_get_block(text, "Headline") or kv_get_block(text, "Listing Header")
    listing_url = kv_get_block(text, "Listing URL") or kv_get_block(text, "URL")

    raw_comments = (
        extract_between_markers(text, "Comments")
        or extract_between_markers(text, "Message")
    )
    comments = clean_comments(raw_comments)

    out = deep_merge(BASE_OUTPUT, {
        "source": "unknown",
        "contact": {
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone
        },
        "address": {
            "line1": address1,
            "city": city,
            "state": state,
            "zip": zipc,
            "country": country
        },
        "listing": {
            "headline": headline,
            "ref_id": ref_id,
            "listing_id": listing_id,
            "listing_url": listing_url
        },
        "comments": comments
    })
    return out

# ==============================
# ✅ Router
# ==============================

def parse_lead_email(raw_body: str) -> Dict:
    text = as_text(raw_body)
    text = text.replace("\r", "")
    text = re.sub(r"\u00a0", " ", text)
    source = detect_source(text)

    if source == "businessbroker":
        out = parse_businessbroker(text)
    elif source == "bizbuysell":
        out = parse_bizbuysell(text)
    elif source == "businessesforsale":
        out = parse_businessesforsale(text)
    elif source == "murphy":
        out = parse_murphy(text)
    else:
        out = parse_unknown(text)

    def scrub_strings(d):
        for k, v in list(d.items()):
            if isinstance(v, dict):
                scrub_strings(v)
            else:
                d[k] = "" if v is None else normalize_spaces(str(v))
    scrub_strings(out)

    return out

# ==============================
# ✅ Flask routes
# ==============================

app = Flask(__name__)

@app.route("/api/parse", methods=["POST"])
def parse_email():
    data = request.get_json(force=True, silent=True) or {}
    raw_body = data.get("body", "")
    parsed = parse_lead_email(raw_body)
    return jsonify(parsed)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
