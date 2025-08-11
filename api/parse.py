# =============================================
# Lead Parser API — Unified Output (Flask app)
# =============================================
# - Returns a consistent nested JSON schema for all lead sources
# - Cleans "Comments" to remove disclaimers, dashed separators, and excess whitespace
# - Handles both HTML and plaintext bodies
#
# Sections are marked with green checkboxes for quick scanning:
#   ✅ Source detection & utilities
#   ✅ BusinessBroker (HTML/Text)
#   ✅ BizBuySell (HTML/Text)
#   ✅ BusinessesForSale (HTML/Text)
#   ✅ Murphy Business (HTML/Text)
#   ✅ Unknown fallback
#   ✅ Flask routes
#
# Run:
#   pip install flask bs4
#   python app.py
#
# POST Example:
#   curl -X POST http://localhost:5000/api/parse -H "Content-Type: application/json" \
#     -d '{"body": "<html>...lead email body...</html>"}'
#
# Response: unified schema with source, contact, address, listing, details, comments


from flask import Flask, request, jsonify
import re
from typing import Dict, Tuple

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None


# ==============================
# ✅ Canonical output structure
# ==============================

BASE_OUTPUT: Dict = {
    "source": "",  # bizbuysell | businessesforsale | murphy | businessbroker | unknown
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
        "ref_id": "",      # broker's internal reference id
        "listing_id": "",  # platform listing id
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
    """Return visible text. If HTML and bs4 is available, strip tags."""
    if raw is None:
        return ""
    text = str(raw)
    if "<" in text and ">" in text and BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(text, "html.parser")
            text = soup.get_text("\n")
        except Exception:
            pass
    return text.replace("\r", "")


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
    Generic 'Label: value' extractor across lines.
    Returns first match, stripped. Case-insensitive.
    """
    m = re.search(rf"(?im)^{re.escape(label)}\s*:\s*(.+)$", text)
    return m.group(1).strip() if m else ""


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

DASH_CUTOFF = r"(?m)^\s*[-_]{2,}\s*$"  # a line of dashes/underscores indicating footer separation


def extract_between_markers(text: str, start_label: str, end_regex: str = DASH_CUTOFF) -> str:
    """
    Extract text following 'start_label' up to a line that matches 'end_regex'.
    If no end_regex match, return to end of text.
    """
    if not text:
        return ""
    # Find 'start_label' anywhere, get the rest of the line and following lines
    m = re.search(rf"(?is){re.escape(start_label)}\s*:?\s*(.*)$", text)
    if not m:
        return ""
    start_idx = m.end(0)
    after = text[start_idx:]
    # Cut off at dashed line
    m2 = re.search(end_regex, after)
    if m2:
        after = after[:m2.start()]
    return after.strip()


def strip_confidential_and_excess(text: str) -> str:
    """Remove legal footers and collapse whitespace."""
    if not text:
        return ""
    # Remove everything after a dashed line first
    text = re.split(DASH_CUTOFF, text)[0]
    # Remove known confidentiality blocks
    for pat in CONFIDENTIAL_PATTERNS:
        text = re.sub(pat, "", text)
    # Collapse excessive blank lines/whitespace
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def clean_comments(raw: str) -> str:
    """High-level comments cleanup applied to any source."""
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
    """
    Expected keys appear as:
    Listing Header:
    BusinessBroker.net Listing Number:
    Your Internal Listing Number:
    First Name:
    Last Name:
    Email:
    Phone:
    Address:
    City:
    State:
    Zip:
    Country:
    Best Time to Contact:
    Comments:
    (then dashed line and disclaimers)
    """
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

    # Comments: everything after 'Comments:' up to dashed line
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
    """
    Typical BizBuySell fields:
    Contact Name: Jane Doe
    Email: jane@example.com
    Phone: (555) 123-4567
    Contact Zip: 90210
    Investment Amount: $100,000
    Purchase Within: 3 months
    Listing ID / Listing Number (optional)
    Listing URL (optional)
    Listing Title / Headline (optional)
    Reference ID / Ref ID (optional)
    Comments: ... (free text)
    """
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
    """
    Common fields:
    Name / First Name / Last Name
    Email
    Phone
    Address / City / State/Region / Zip/Postal / Country
    Listing ID / Ref
    Listing URL
    Headline / Title
    Comments / Message
    """
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
    """
    Murphy Business emails vary; capture typical fields.
    """
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
    """
    Main entry point. Pass raw email body (HTML or plaintext).
    Returns a consistent nested schema for all sources.
    """
    text = as_text(raw_body)
    text = text.replace("\r", "")
    text = re.sub(r"\u00a0", " ", text)  # non-breaking space
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

    # Final normalization: ensure all strings, tidy whitespace
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
