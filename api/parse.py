from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

# ✅ Helper: Convert HTML to clean text if needed
def html_to_normalized_text(raw: str) -> str:
    lowered = raw.lower()
    is_html = ("<html" in lowered) or ("<body" in lowered) or ("<div" in lowered) or ("<table" in lowered)
    if not is_html:
        return raw.replace('\r', '')

    soup = BeautifulSoup(html.unescape(raw), "html.parser")
    text = soup.get_text(separator="\n")
    text = text.replace('\r', '')
    text = re.sub(r'[ \t]+', ' ', text)      # collapse multiple spaces
    text = re.sub(r'\n{3,}', '\n\n', text)   # collapse big blank blocks
    return text.strip()

# ✅ Helper: Fallback for BizBuySell comments (HTML mode)
def _fallback_bizbuysell_comments_from_html(raw: str) -> str:
    """If text parse missed comments, grab from HTML <b>Comments</b> → next <span> (or sibling text)."""
    try:
        soup = BeautifulSoup(html.unescape(raw), "html.parser")
        b = soup.find('b', string=re.compile(r'^Comments$', re.IGNORECASE))
        if not b:
            return ''
        span = b.find_next('span')
        if span and span.get_text(strip=True):
            return span.get_text(strip=True)
        sib = b.next_sibling
        if isinstance(sib, str) and sib.strip():
            return sib.strip()
    except Exception:
        pass
    return ''

app = Flask(__name__)

# --- Helper to clean "Not disclosed" values (and variants) ---
def remove_not_disclosed_fields(data):
    return {
        k: ('' if isinstance(v, str) and 'not disclosed' in v.lower().strip() else v)
        for k, v in data.items()
    }

# --- Phone: normalize to E.164 (+1XXXXXXXXXX) for US/CA ---
def normalize_phone_us_e164(phone: str) -> str:
    """
    Normalize US/Canada numbers to E.164 (+1XXXXXXXXXX).
    Returns '' if not a valid 10/11-digit NANP number.
    """
    if not phone:
        return ''
    phone_wo_ext = re.sub(r'(?:ext|x|extension)[\s.:#-]*\d+\s*$', '', phone, flags=re.I)
    digits = re.sub(r'\D', '', phone_wo_ext)
    # common international prefixes for US numbers
    if len(digits) == 13 and digits.startswith('001'):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith('01'):
        digits = digits[2:]
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

# --- Clean BusinessBroker headline tails like "BusinessBroker.net"
def _clean_bb_headline(h: str) -> str:
    if not h:
        return ''
    h = re.split(r'\bBusinessBroker(?:\.net)?\b\.?', h, maxsplit=1, flags=re.I)[0]
    return h.strip()

# ============================================================
# BizBuySell (TEXT)  — used for both HTML (after normalize) and text
# ============================================================
def extract_bizbuysell_text(text_body: str):
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
    pt_match = re.search(r'Purchase Within:\s*(.*?)\s*Comments:', full_text, re.IGNORECASE | re.DOTALL)
    if pt_match:
        purchase_timeline = pt_match.group(1).strip()

    # Comments until footer-ish lines
    comments = ''
    cmt_match = re.search(
        r'Comments:\s*((?:.|\n)*?)(?:\n(?:You can reply directly|We take our lead quality|Thank you,|BizBuySell|Unsubscribe|Email Preferences|Terms of Use|Privacy Notice|Contact Us|$))',
        full_text,
        re.IGNORECASE
    )
    if cmt_match:
        comments = cmt_match.group(1).strip()

    # Phone (E.164)
    phone = normalize_phone_us_e164(get("Contact Phone"))

    # Headline (between "regarding your listing:" and the next known label)
    headline = ''
    h_match = re.search(r"regarding your listing:\s*([\s\S]*?)\s*(?:Listing ID|Ref ID)\s*:", full_text, re.IGNORECASE)
    if h_match:
        headline = h_match.group(1).strip().splitlines()[0].strip()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get("Contact Email"),
        "phone": phone,
        "ref_id": get("Ref ID").split('\n')[0].strip() if get("Ref ID") else '',
        "listing_id": get("Listing ID"),
        "headline": headline,
        "contact_zip": get("Contact Zip"),
        "investment_amount": get("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": "",
        "address": "",
        "city": "",
        "state": "",
        "best_time_to_contact": ""
    }

# ============================================================
# BusinessesForSale (TEXT)
# ============================================================
def extract_businessesforsale_text(text_body: str):
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
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": listing_url,
        "services_interested_in": "",
        "heard_about": "",
        "address": "",
        "city": "",
        "state": "",
        "best_time_to_contact": ""
    }

# ============================================================
# Murphy Business (TEXT) — used for both HTML (after normalize) and text
# ============================================================
def extract_murphy_text(text_body: str):
    text = text_body.replace('\r', '')
    headline = ''  # intentionally blank for Murphy

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
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": services,
        "heard_about": heard,
        "address": "",
        "city": "",
        "state": "",
        "best_time_to_contact": ""
    }

# ============================================================
# BusinessBroker.net (TEXT) — used for both HTML (after normalize) and text
# ============================================================
def extract_businessbroker_text(text_body: str):
    text = text_body.replace('\r', '')

    def get_after(label):
        # Stop at the next Label: even if there's NO space before it (e.g., "... Address:City: ...")
        # Also stop if a brand token like "BusinessBroker.net" appears as the next thing.
        pattern = rf"{re.escape(label)}\s*:\s*(.*?)(?=(?:\s*[A-Za-z][A-Za-z/ ]{{1,30}}:)|\n\s*BusinessBroker(?:\.net)?\b|\Z)"
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ''

    def get_after_multi(labels):
        for lab in labels:
            v = get_after(lab)
            if v:
                return v
        return ''

    headline    = get_after("Listing Header")
    headline    = _clean_bb_headline(headline)

    listing_id  = get_after("BusinessBroker.net Listing Number")
    ref_id      = get_after("Your Internal Listing Number")
    first_name  = get_after("First Name")
    last_name   = get_after("Last Name")
    email       = get_after("Email")
    phone       = normalize_phone_us_e164(get_after("Phone"))
    contact_zip = get_after_multi(["Zip", "ZIP", "Zip/Postal Code"])
    address     = get_after_multi(["Address", "Street Address", "Address Line 1"])
    city        = get_after("City")
    state       = get_after("State")
    best_time   = get_after_multi(["Best Time to Contact", "Best time to contact", "Best Time To Be Contacted"])

    # Comments up to dashed line or end (avoid footer noise)
    comments = ''
    cmt = re.search(r"Comments\s*:\s*(.*?)(?:\n[-_]{3,}|\Z)", text, re.IGNORECASE | re.DOTALL)
    if cmt:
        comments = cmt.group(1).strip()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": contact_zip,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": "",
        "address": address,
        "city": city,
        "state": state,
        "best_time_to_contact": best_time
    }

# ============================================================
# Router
# ============================================================
@app.route('/api/parse', methods=['POST'])
def parse_email():
    try:
        raw_body = request.get_data(as_text=True)
        if not raw_body:
            return jsonify({"error": "No email content provided."}), 400

        lowered = raw_body.lower()

        if "bizbuysell" in lowered:
            text_version = html_to_normalized_text(raw_body)  # ✅ Always normalize
            parsed = extract_bizbuysell_text(text_version)

            # ✅ Fallback: if comments are empty after text parse, try HTML direct parse
            if not parsed.get("comments"):
                html_comments = _fallback_bizbuysell_comments_from_html(raw_body)
                if html_comments:
                    parsed["comments"] = html_comments

            parsed = remove_not_disclosed_fields(parsed)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed})

        elif "businessesforsale.com" in lowered:
            text_version = html_to_normalized_text(raw_body)
            parsed = extract_businessesforsale_text(text_version)
            parsed = remove_not_disclosed_fields(parsed)
            return jsonify({"source": "businessesforsale", "parsed_data": parsed})

        elif "murphybusiness.com" in lowered:
            text_version = html_to_normalized_text(raw_body)
            parsed = extract_murphy_text(text_version)
            parsed = remove_not_disclosed_fields(parsed)
            return jsonify({"source": "murphybusiness", "parsed_data": parsed})

        elif "businessbroker.net" in lowered:
            text_version = html_to_normalized_text(raw_body)
            parsed = extract_businessbroker_text(text_version)
            parsed = remove_not_disclosed_fields(parsed)
            return jsonify({"source": "businessbroker", "parsed_data": parsed})

        return jsonify({"source": "unknown", "parsed_data": {}})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run()
