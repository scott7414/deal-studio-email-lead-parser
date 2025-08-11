# =============================================
# Lead Parser API — Unified Output (Flask app)
# =============================================
# Accepts EITHER:
#   - raw email body in the request payload, OR
#   - JSON: { "body": "<email body>" }
#
# Returns a consistent nested schema:
# {
#   "source": "bizbuysell|businessesforsale|murphybusiness|businessbroker|unknown",
#   "contact": {...},
#   "address": {...},
#   "listing": {...},
#   "details": {...},
#   "comments": "…"
# }
#
# Sections marked with green checkboxes for quick scanning:
#   ✅ Shared helpers (phone, comment cleanup, not-disclosed cleaner)
#   ✅ BizBuySell (HTML)
#   ✅ BizBuySell (TEXT)
#   ✅ BusinessesForSale (TEXT)
#   ✅ Murphy Business (HTML)
#   ✅ Murphy Business (TEXT)
#   ✅ BusinessBroker.net (HTML)
#   ✅ BusinessBroker.net (TEXT)
#   ✅ Router + unified mapping
#   ✅ Flask routes
#
# ---------------------------------------------

from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re
import traceback

app = Flask(__name__)

# ==============================
# ✅ Shared helpers
# ==============================

def remove_not_disclosed_fields(data):
    """Turn values like 'Not disclosed' into '' (string)."""
    return {
        k: ('' if isinstance(v, str) and 'not disclosed' in v.lower().strip() else v)
        for k, v in data.items()
    }

def normalize_phone_us_e164(phone: str) -> str:
    """
    Normalize US/Canada numbers to E.164 (+1XXXXXXXXXX).
    Returns '' if not a valid 10/11-digit NANP number.
    """
    if not phone:
        return ''

    # Drop simple extensions at the end (ext 123, x123, extension 123)
    phone_wo_ext = re.sub(r'(?:ext|x|extension)[\s.:#-]*\d+\s*$', '', phone, flags=re.I)

    # Keep digits only
    digits = re.sub(r'\D', '', phone_wo_ext)

    # Normalize leading IDD variants to 10 digits
    if len(digits) == 13 and digits.startswith('001'):   # 001 + 10
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith('01'):  # 01 + 10
        digits = digits[2:]

    # Reduce to national (10) if starts with leading 1 and length 11
    if len(digits) == 11 and digits.startswith('1'):
        national = digits[1:]
    elif len(digits) == 10:
        national = digits
    else:
        m = re.search(r'(\d{10})$', digits)
        if not m:
            return ''
        national = m.group(1)

    return '+1' + national

def clean_comments_block(raw_text: str) -> str:
    """Keep only user message and strip disclaimers/dashed lines/excess whitespace."""
    if not raw_text:
        return ''
    # Stop at a dashed/underscore rule
    text = re.split(r'(?m)^\s*[-_]{3,}\s*$', raw_text)[0]
    # Remove common legal/confidentiality blurbs
    patterns = [
        r'(?is)\b(confidential(ity)? notice|this e-?mail.*confidential|intended only for the named recipient|do not disseminate|if you have received this.*in error).*',
        r'(?is)\b(terms of use and disclaimers apply).*',
        r'(?is)\b(be aware! online banking fraud).*',
    ]
    for p in patterns:
        text = re.sub(p, '', text)
    # Tidy whitespace
    text = text.replace('\r', '')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()

# ==============================
# ✅ BizBuySell (HTML)
# ==============================
def extract_bizbuysell_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    # Headline
    headline = ''
    for b in soup.find_all('b'):
        text = b.get_text(strip=True)
        if text.lower() != "from:" and len(text) > 10:
            headline = text
            break

    # Contact name
    name_tag = soup.find('b', string=re.compile('Contact Name'))
    name = name_tag.find_next('span').get_text(strip=True) if name_tag else ''
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # Email
    email_tag = soup.find('b', string=re.compile('Contact Email'))
    email = email_tag.find_next('span').get_text(strip=True) if email_tag else ''

    # Phone (E.164)
    phone_tag = soup.find('b', string=re.compile('Contact Phone'))
    phone_raw = phone_tag.find_next('span').get_text(strip=True) if phone_tag else ''
    phone = normalize_phone_us_e164(phone_raw)

    # Ref ID
    ref_id = ''
    ref_id_match = soup.find(string=re.compile('Ref ID'))
    if ref_id_match:
        m = re.search(r'Ref ID:\s*([A-Za-z0-9\-\_]+)', ref_id_match)
        if m:
            ref_id = m.group(1).strip()
        else:
            nxt = ref_id_match.find_next(string=True)
            if nxt:
                m2 = re.search(r'([A-Za-z0-9\-\_]+)', nxt)
                if m2:
                    ref_id = m2.group(1).strip()

    # Listing ID
    listing_id = ''
    for span in soup.find_all('span'):
        if 'Listing ID:' in span.get_text():
            a = span.find_next('a')
            if a:
                listing_id = a.get_text(strip=True)
                break

    # Optional fields
    def extract_optional(label):
        try:
            tag = soup.find('b', string=re.compile(label))
            if tag:
                span = tag.find_next('span')
                if span:
                    return span.get_text(strip=True)
            return ''
        except:
            return ''

    contact_zip = extract_optional('Contact Zip')
    investment_amount = extract_optional('Able to Invest')
    purchase_timeline = extract_optional('Purchase Within')
    comments = extract_optional('Comments')
    comments = clean_comments_block(comments)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": contact_zip,
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        "investment_amount": investment_amount,
        "purchase_timeline": purchase_timeline,
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ BizBuySell (TEXT)
# ==============================
def extract_bizbuysell_text(text_body):
    lines = text_body.replace('\r', '').split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    full_text = "\n".join(lines)

    def get(label):
        m = re.search(rf"{label}:\s*(.+)", full_text)
        return m.group(1).strip() if m else ''

    name = get("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # Purchase Within until Comments
    purchase_timeline = ''
    pt_match = re.search(r'Purchase Within:\s*(.*?)\s*Comments:', full_text, re.DOTALL)
    if pt_match:
        purchase_timeline = pt_match.group(1).strip()

    # Comments until typical footer phrasing
    comments = ''
    cmt_match = re.search(r'Comments:\s*((?:.|\n)*?)(?:\n(?:You can reply directly|We take our lead quality|Thank you,|$))', full_text)
    if cmt_match:
        comments = cmt_match.group(1).strip()
    comments = clean_comments_block(comments)

    # Phone (E.164)
    phone = normalize_phone_us_e164(get("Contact Phone"))

    # Headline
    headline = ''
    h_match = re.search(r"regarding your listing:\s*(.*?)\s*Listing ID", full_text, re.DOTALL)
    if h_match:
        headline = h_match.group(1).strip()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get("Contact Email"),
        "phone": phone,
        "ref_id": get("Ref ID").split('\n')[0].strip() if get("Ref ID") else '',
        "listing_id": get("Listing ID"),
        "headline": headline,
        "contact_zip": get("Contact Zip"),
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        "investment_amount": get("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ BusinessesForSale (TEXT)
# ==============================
def extract_businessesforsale_text(text_body):
    lines = text_body.replace('\r', '').split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    full_text = "\n".join(lines)

    def get_field(label):
        m = re.search(rf"{label}:\s*(.+)", full_text)
        return m.group(1).strip() if m else ''

    # ref + headline + URL in a block
    ref_id, headline, listing_url = '', '', ''
    block = re.search(r"Your listing ref:(\d+)\s+(.+)\n(https?://[^\s]+)", full_text)
    if block:
        ref_id, headline, listing_url = block.groups()
        ref_id, headline, listing_url = ref_id.strip(), headline.strip(), listing_url.strip()

    # name
    name = get_field("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # comments between markers
    comments = ''
    cmt = re.search(r"has received the following message:\s*\n\n(.+?)\n\nName:", full_text, re.DOTALL)
    if cmt:
        comments = cmt.group(1).strip()
    comments = clean_comments_block(comments)

    # Phone (E.164)
    phone = normalize_phone_us_e164(get_field("Tel"))

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get_field("Email"),
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": "",
        "headline": headline,
        "contact_zip": "",
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": listing_url,
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ Murphy Business (HTML)
# ==============================
def extract_murphy_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text = soup.get_text(separator="\n")

    # Headline (Subject) not provided reliably
    headline = ''

    def get_after(label):
        pattern = rf"{label}\s*:\s*([^\n\r]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    name = get_after("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email = get_after("Email")
    contact_zip = get_after("ZIP/Postal Code")
    phone = normalize_phone_us_e164(get_after("Phone"))
    services = get_after("Services Interested In")
    heard = get_after("How did you hear about us\??")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": "",
        "listing_id": "",
        "headline": headline,
        "contact_zip": contact_zip,
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": services,
        "heard_about": heard
    }

# ==============================
# ✅ Murphy Business (TEXT)
# ==============================
def extract_murphy_text(text_body):
    text = text_body.replace('\r', '')

    headline = ''

    def get_after(label):
        pattern = rf"{label}\s*:\s*([^\n\r]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    name = get_after("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email = get_after("Email")
    contact_zip = get_after("ZIP/Postal Code")
    phone = normalize_phone_us_e164(get_after("Phone"))
    services = get_after("Services Interested In")
    heard = get_after("How did you hear about us\??")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": "",
        "listing_id": "",
        "headline": headline,
        "contact_zip": contact_zip,
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": services,
        "heard_about": heard
    }

# ==============================
# ✅ BusinessBroker.net (HTML)
# ==============================
def extract_businessbroker_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text = soup.get_text(separator="\n")

    def get_after(label):
        pattern = rf"{re.escape(label)}\s*:\s*([^\n\r]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    def get_after_multi(labels):
        for lab in labels:
            v = get_after(lab)
            if v:
                return v
        return ''

    headline    = get_after("Listing Header")
    listing_id  = get_after("BusinessBroker.net Listing Number")
    ref_id      = get_after("Your Internal Listing Number")
    first_name  = get_after("First Name")
    last_name   = get_after("Last Name")
    email       = get_after("Email")
    phone       = normalize_phone_us_e164(get_after("Phone"))
    contact_zip = get_after_multi(["Zip", "ZIP", "Zip/Postal Code"])
    city = get_after_multi([\"City\"]) or ''
    state = get_after_multi([\"State\"]) or ''
    country = get_after_multi([\"Country\"]) or ''
    address = get_after_multi([\"Address\", \"Address 1\", \"Address Line 1\"]) or ''

    # Comments block: after "Comments:" up to dashed line or end
    comments = ''
    cmt = re.search(r"Comments\s*:\s*(.*?)(?:\n[-_]{3,}|\Z)", text, re.IGNORECASE | re.DOTALL)
    if cmt:
        comments = cmt.group(1).strip()
    comments = clean_comments_block(comments)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": contact_zip,
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ BusinessBroker.net (TEXT)
# ==============================
def extract_businessbroker_text(text_body):
    text = text_body.replace('\r', '')

    def get_after(label):
        pattern = rf"{re.escape(label)}\s*:\s*([^\n\r]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    def get_after_multi(labels):
        for lab in labels:
            v = get_after(lab)
            if v:
                return v
        return ''

    headline    = get_after("Listing Header")
    listing_id  = get_after("BusinessBroker.net Listing Number")
    ref_id      = get_after("Your Internal Listing Number")
    first_name  = get_after("First Name")
    last_name   = get_after("Last Name")
    email       = get_after("Email")
    phone       = normalize_phone_us_e164(get_after("Phone"))
    contact_zip = get_after_multi(["Zip", "ZIP", "Zip/Postal Code"])
    city = get_after_multi([\"City\"]) or ''
    state = get_after_multi([\"State\"]) or ''
    country = get_after_multi([\"Country\"]) or ''
    address = get_after_multi([\"Address\", \"Address 1\", \"Address Line 1\"]) or ''

    # Comments block
    comments = ''
    cmt = re.search(r"Comments\s*:\s*(.*?)(?:\n[-_]{3,}|\Z)", text, re.IGNORECASE | re.DOTALL)
    if cmt:
        comments = cmt.group(1).strip()
    comments = clean_comments_block(comments)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": contact_zip,
        \"address\": address,
        \"city\": city,
        \"state\": state,
        \"country\": country,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ Mapper to unified nested schema
# ==============================
def to_nested(source: str, flat: dict) -> dict:
    flat = remove_not_disclosed_fields(flat or {})
    # Build nested structure
    return {
        "source": source,
        "contact": {
            "first_name": flat.get("first_name", ""),
            "last_name": flat.get("last_name", ""),
            "email": flat.get("email", ""),
            "phone": flat.get("phone", ""),
            "best_time_to_contact": flat.get("best_time_to_contact", "")
        },
        "address": {
            "line1": flat.get("address", "") or flat.get("address1", ""),
            "city": flat.get("city", ""),
            "state": flat.get("state", ""),
            "zip": flat.get("contact_zip", "") or flat.get("zip", ""),
            "country": flat.get("country", "")
        },
        "listing": {
            "headline": flat.get("headline", ""),
            "ref_id": flat.get("ref_id", ""),
            "listing_id": flat.get("listing_id", ""),
            "listing_url": flat.get("listing_url", "")
        },
        "details": {
            "purchase_timeline": flat.get("purchase_timeline", ""),
            "investment_amount": flat.get("investment_amount", ""),
            "services_interested_in": flat.get("services_interested_in", ""),
            "heard_about": flat.get("heard_about", "")
        },
        "comments": flat.get("comments", "")
    }

# ==============================
# ✅ Router + unified mapping
# ==============================
@app.route('/api/parse', methods=['POST'])
def parse_email():
    try:
        # Support BOTH raw body and JSON {"body": "..."} to avoid empty inputs.
        raw = request.get_data(as_text=True) or ''
        body = ''
        # If content-type is JSON or body parses as JSON, prefer that "body" field if present
        try:
            data = request.get_json(force=False, silent=True)
            if isinstance(data, dict) and data.get('body'):
                body = data.get('body') or ''
            else:
                body = raw
        except Exception:
            body = raw

        if not body:
            return jsonify({"error": "No email content provided."}), 400

        lowered = body.lower()
        is_html = ("<html" in lowered) or ("<body" in lowered) or ("<div" in lowered)

        # Detect + parse with PROVEN extractors
        if "bizbuysell" in lowered:
            try:
                flat = extract_bizbuysell_html(body) if is_html else extract_bizbuysell_text(body)
            except Exception as e:
                # Fallback: try text parser if HTML failed
                try:
                    flat = extract_bizbuysell_text(BeautifulSoup(body, "html.parser").get_text("
"))
                except Exception as e2:
                    return jsonify({"error": "BizBuySell parse failed", "e_html": str(e), "e_text": str(e2)}), 500
            return jsonify(to_nested("bizbuysell", flat))

        if "businessesforsale.com" in lowered or "businesses for sale" in lowered:
            flat = extract_businessesforsale_text(body)
            return jsonify(to_nested("businessesforsale", flat))

        if "murphybusiness.com" in lowered or "murphy business" in lowered:
            flat = extract_murphy_html(body) if is_html else extract_murphy_text(body)
            return jsonify(to_nested("murphybusiness", flat))

        if "businessbroker.net" in lowered:
            flat = extract_businessbroker_html(body) if is_html else extract_businessbroker_text(body)
            return jsonify(to_nested("businessbroker", flat))

        # Unknown -> empty nested structure
        empty_flat = {
            "first_name": "",
            "last_name": "",
            "email": "",
            "phone": "",
            "ref_id": "",
            "listing_id": "",
            "headline": "",
            "contact_zip": "",
            "investment_amount": "",
            "purchase_timeline": "",
            "comments": "",
            "listing_url": "",
            "services_interested_in": "",
            "heard_about": ""
        }
        return jsonify(to_nested("unknown", empty_flat))

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

# ==============================
# ✅ Flask health
# ==============================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


@app.route('/api/parse_debug', methods=['POST'])
def parse_debug():
    raw = request.get_data(as_text=True) or ''
    body = ''
    try:
        data = request.get_json(force=False, silent=True)
        if isinstance(data, dict) and data.get('body'):
            body = data.get('body') or ''
        else:
            body = raw
    except Exception:
        body = raw

    is_html = ("<html" in body.lower())
    norm_text = ''
    try:
        if is_html:
            norm_text = BeautifulSoup(body, "html.parser").get_text("\n")
        else:
            norm_text = body
    except Exception as e:
        norm_text = f"[norm error] {e}"

    # Show quick probes
    probes = {
        "contains_bizbuysell": "bizbuysell" in body.lower(),
        "contains_businessbroker": "businessbroker.net" in body.lower(),
        "contains_bfs": "businessesforsale.com" in body.lower(),
        "contains_murphy": "murphybusiness" in body.lower() or "murphy business" in body.lower(),
        "sample_lines": "\n".join(norm_text.splitlines()[:50])
    }
    return jsonify(probes)
