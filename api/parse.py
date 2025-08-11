# =============================================
# Lead Parser API — Revert-Safe (No HTML->Text conversion; no 500s)
# =============================================

from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

# ==============================
# ✅ Shared helpers
# ==============================

def remove_not_disclosed_fields(data):
    return {
        k: ('' if isinstance(v, str) and 'not disclosed' in v.lower().strip() else v)
        for k, v in (data or {}).items()
    }

def normalize_phone_us_e164(phone: str) -> str:
    if not phone:
        return ''
    phone_wo_ext = re.sub(r'(?:ext|x|extension)[\s.:#-]*\d+\s*$', '', phone, flags=re.I)
    digits = re.sub(r'\D', '', phone_wo_ext)
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
        if not m: return ''
        national = m.group(1)
    return '+1' + national

def clean_comments_block(raw_text: str) -> str:
    if not raw_text:
        return ''
    text = re.split(r'(?m)^\s*[-_]{3,}\s*$', raw_text)[0]
    patterns = [
        r'(?is)\b(confidential(ity)? notice|this e-?mail.*confidential|intended only for the named recipient|do not disseminate|if you have received this.*in error).*',
        r'(?is)\b(terms of use and disclaimers apply).*',
        r'(?is)\b(be aware! online banking fraud).*',
    ]
    for p in patterns:
        text = re.sub(p, '', text)
    text = text.replace('\r', '')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()

# ==============================
# ✅ BizBuySell (HTML) — original pattern
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
        "investment_amount": investment_amount,
        "purchase_timeline": purchase_timeline,
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ BizBuySell (TEXT) — original pattern
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

    purchase_timeline = ''
    pt_match = re.search(r'Purchase Within:\s*(.*?)\s*Comments:', full_text, re.DOTALL)
    if pt_match:
        purchase_timeline = pt_match.group(1).strip()

    comments = ''
    cmt_match = re.search(r'Comments:\s*((?:.|\n)*?)(?:\n(?:You can reply directly|We take our lead quality|Thank you,|$))', full_text)
    if cmt_match:
        comments = cmt_match.group(1).strip()
    comments = clean_comments_block(comments)

    phone = normalize_phone_us_e164(get("Contact Phone"))

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
        "investment_amount": get("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ BusinessesForSale (TEXT) — original pattern
# ==============================
def extract_businessesforsale_text(text_body):
    lines = text_body.replace('\r', '').split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    full_text = "\n".join(lines)

    def get_field(label):
        m = re.search(rf"{label}:\s*(.+)", full_text)
        return m.group(1).strip() if m else ''

    ref_id, headline, listing_url = '', '', ''
    block = re.search(r"Your listing ref:(\d+)\s+(.+)\n(https?://[^\s]+)", full_text)
    if block:
        ref_id, headline, listing_url = block.groups()
        ref_id, headline, listing_url = ref_id.strip(), headline.strip(), listing_url.strip()

    name = get_field("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    comments = ''
    cmt = re.search(r"has received the following message:\s*\n\n(.+?)\n\nName:", full_text, re.DOTALL)
    if cmt:
        comments = cmt.group(1).strip()
    comments = clean_comments_block(comments)

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
        "heard_about": ""
    }

# ==============================
# ✅ Murphy Business (HTML) — original pattern
# ==============================
def extract_murphy_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text = soup.get_text(separator="\n")

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
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": services,
        "heard_about": heard
    }

# ==============================
# ✅ Murphy Business (TEXT) — original pattern
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
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": services,
        "heard_about": heard
    }

# ==============================
# ✅ BusinessBroker.net (HTML) — original pattern + address fields
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
    city        = get_after("City")
    state       = get_after("State")
    country     = get_after("Country")
    address     = get_after_multi(["Address", "Address 1", "Address Line 1"])

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
        "address": address,
        "city": city,
        "state": state,
        "country": country,
        "contact_zip": contact_zip,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ BusinessBroker.net (TEXT) — original pattern + address fields
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
    city        = get_after("City")
    state       = get_after("State")
    country     = get_after("Country")
    address     = get_after_multi(["Address", "Address 1", "Address Line 1"])

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
        "address": address,
        "city": city,
        "state": state,
        "country": country,
        "contact_zip": contact_zip,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }


# ==============================
# ✅ FCBB (HTML) — First Choice Business Brokers
# ==============================
def extract_fcbb_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    # Find the main info block (div with the <p> lines)
    info_div = None
    for div in soup.find_all('div'):
        txt = div.get_text(separator="\n", strip=True)
        if not txt:
            continue
        # Heuristic: block that contains tel: and mailto: in <a> tags, or looks like 4 short lines
        has_tel = div.find('a', href=lambda h: h and h.lower().startswith('tel:'))
        has_mail = div.find('a', href=lambda h: h and h.lower().startswith('mailto:'))
        if has_tel and has_mail:
            info_div = div
            break
        # fallback: a div with ~3-5 <p> lines
        ps = div.find_all('p')
        if 3 <= len(ps) <= 6:
            info_div = div
            # don't break; prefer the tel/mailto block if we find it later
    if not info_div:
        # As fallback, parse whole page text
        text = soup.get_text("\n")
        lines = [l.strip() for l in text.replace('\r','').split('\n') if l.strip()]
        # try a minimal pattern: name, "<ref> <headline>", phone, email
        name, ref_id, headline, phone, email = "", "", "", "", ""
        # phone
        for l in lines:
            if '(' in l and ')' in l and any(ch.isdigit() for ch in l):
                phone = l.strip()
                break
        # email
        for l in lines:
            if '@' in l and '.' in l and ' ' not in l:
                email = l.strip()
                break
        # ref/headline: first line with token-then-rest like "101-24127 Something..."
        for l in lines:
            m = re.match(r'^\s*([A-Za-z0-9\-]+)\s+(.*)$', l)
            if m and any(c.isalpha() for c in m.group(2)):
                ref_id = m.group(1).strip()
                headline = m.group(2).strip()
                break
        # name: first non-empty that isn't phone/email/ref/headline
        for l in lines:
            if l in (phone, email, f"{ref_id} {headline}"):
                continue
            if 1 <= len(l.split()) <= 3 and not re.search(r'\d', l):
                name = l.strip()
                break
    else:
        # Parse the <p> lines inside the info_div
        ps = info_div.find_all('p')
        p_texts = [p.get_text(strip=True) for p in ps if p.get_text(strip=True)]
        # Expect order: name, "<ref> <headline>", phone, email
        name = p_texts[0] if len(p_texts) >= 1 else ""
        line2 = p_texts[1] if len(p_texts) >= 2 else ""
        # phone
        a_tel = info_div.find('a', href=lambda h: h and h.lower().startswith('tel:'))
        phone = a_tel.get_text(strip=True) if a_tel else (p_texts[2] if len(p_texts) >= 3 else "")
        # email
        a_mail = info_div.find('a', href=lambda h: h and h.lower().startswith('mailto:'))
        email = a_mail.get_text(strip=True) if a_mail else (p_texts[3] if len(p_texts) >= 4 else "")
        # split ref/headline
        ref_id, headline = "", ""
        m = re.match(r'^\s*([A-Za-z0-9\-]+)\s+(.*)$', line2)
        if m:
            ref_id = m.group(1).strip()
            headline = m.group(2).strip()

    # Split name into first/last (if more than one word, use first token as first_name, rest as last_name)
    first_name, last_name = "", ""
    if name:
        parts = name.strip().split()
        if len(parts) >= 2:
            first_name, last_name = parts[0], " ".join(parts[1:])
        else:
            first_name = parts[0]

    # Normalize phone
    phone = normalize_phone_us_e164(phone)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email.strip(),
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": "",
        "headline": headline,
        "contact_zip": "",
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }
# ==============================
# ✅ Mapper to unified nested schema
# ==============================
def to_nested(source: str, flat: dict, error_debug: str = "") -> dict:
    flat = remove_not_disclosed_fields(flat or {})
    nested = {
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
    if error_debug:
        nested["error_debug"] = error_debug
    return nested

# ==============================
# ✅ Router (no 500s; safe fallbacks)
# ==============================
@app.route('/api/parse', methods=['POST'])
def parse_email():
    # Accept raw or JSON {"body": ...}
    raw = request.get_data(as_text=True) or ''
    body = raw
    try:
        data = request.get_json(force=False, silent=True)
        if isinstance(data, dict) and data.get('body'):
            body = data.get('body') or ''
    except Exception:
        pass

    if not body:
        return jsonify({"error": "No email content provided."}), 200

    lowered = body.lower()
    is_html = ("<html" in lowered) or ("<body" in lowered) or ("<div" in lowered)

    try:
        if "bizbuysell" in lowered:
            try:
                flat = extract_bizbuysell_html(body) if is_html else extract_bizbuysell_text(body)
                return jsonify(to_nested("bizbuysell", flat))
            except Exception as e:
                # Fall back to text using stripped HTML
                try:
                    text = BeautifulSoup(body, "html.parser").get_text("\n")
                    flat = extract_bizbuysell_text(text)
                    return jsonify(to_nested("bizbuysell", flat, f"fallback_text_ok: {e}"))
                except Exception as e2:
                    return jsonify(to_nested("bizbuysell", {}, f"parse_failed: {e}; fallback_failed: {e2}"))
        if "businessesforsale.com" in lowered or "businesses for sale" in lowered:
            try:
                flat = extract_businessesforsale_text(body if not is_html else BeautifulSoup(body, "html.parser").get_text("\n"))
                return jsonify(to_nested("businessesforsale", flat))
            except Exception as e:
                return jsonify(to_nested("businessesforsale", {}, f"parse_failed: {e}"))
        if "murphybusiness.com" in lowered or "murphy business" in lowered:
            try:
                flat = extract_murphy_html(body) if is_html else extract_murphy_text(body)
                return jsonify(to_nested("murphybusiness", flat))
            except Exception as e:
                try:
                    text = BeautifulSoup(body, "html.parser").get_text("\n")
                    flat = extract_murphy_text(text)
                    return jsonify(to_nested("murphybusiness", flat, f"fallback_text_ok: {e}"))
                except Exception as e2:
                    return jsonify(to_nested("murphybusiness", {}, f"parse_failed: {e}; fallback_failed: {e2}"))
        if "businessbroker.net" in lowered:
            try:
                flat = extract_businessbroker_html(body) if is_html else extract_businessbroker_text(body)
                return jsonify(to_nested("businessbroker", flat))
            except Exception as e:
                try:
                    text = BeautifulSoup(body, "html.parser").get_text("\n")
                    flat = extract_businessbroker_text(text)
                    return jsonify(to_nested("businessbroker", flat, f"fallback_text_ok: {e}"))
                except Exception as e2:
                    return jsonify(to_nested("businessbroker", {}, f"parse_failed: {e}; fallback_failed: {e2}"))
        # Unknown
        return jsonify(to_nested("unknown", {}))
    except Exception as outer:
        # Absolute last resort: never 500
        return jsonify(to_nested("unknown", {}, f"router_error: {outer}"))

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
