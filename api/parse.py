# =============================================
# Lead Parser API — Revert-Safe (Stable, no 500s)
# =============================================

from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re
from urllib.parse import urlparse

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

def first_http_url(value: str) -> str:
    """Grab the first visible http(s) URL and ignore bracketed tracking tails."""
    if not value:
        return ""
    m = re.search(r'https?://[^\s\]]+', value)
    return (m.group(0).rstrip(']') if m else value.strip())

def derive_domain(s: str) -> str:
    """Return bare domain (no scheme/www)."""
    s = (s or "").strip()
    if not s:
        return ""
    if not s.startswith("http"):
        s = "http://" + s
    host = urlparse(s).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host

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
    """
    Robust BizBuySell TEXT parser:
      - Values are captured until the next label (handles multiple labels on one line).
      - Flexible label matching tolerates newlines inside labels (e.g., "Contact\nPhone").
      - Keeps existing headline extraction logic.
    """
    txt = text_body.replace('\r', '')

    # --- Headline (same as before) ---
    headline = ''
    h_match = re.search(r"regarding your listing:\s*(.*?)\s*Listing ID", txt, re.DOTALL | re.IGNORECASE)
    if h_match:
        headline = h_match.group(1).strip()

    # --- Flexible, label-bounded extraction ---
    labels = [
        "Contact Name", "Contact Email", "Contact Phone", "Contact Zip",
        "Able to Invest", "Purchase Within", "Comments", "Listing ID", "Ref ID"
    ]

    # Build a regex that tolerates arbitrary whitespace (incl. newlines) inside labels.
    def label_to_re(l):
        # "Contact Phone" -> r"\bContact\s*Phone\s*:"
        return r"\b" + r"\s*".join(map(re.escape, l.split())) + r"\s*:"

    label_union = "|".join(f"({label_to_re(l)})" for l in labels)
    label_re = re.compile(label_union, flags=re.IGNORECASE)

    # Find all label occurrences with positions, and map back to canonical names
    def normalize(s): return re.sub(r"\s+", "", s).lower()
    canon_map = {normalize(l): l for l in labels}

    matches = []
    for m in label_re.finditer(txt):
        matched = m.group(0)                 # e.g. "Contact\nPhone:"
        label_no_colon = re.sub(r":\s*$", "", matched)
        label_norm = normalize(re.sub(r"\s+", " ", label_no_colon))
        canon = canon_map.get(label_norm, None)
        if canon:
            matches.append((canon, m.start(), m.end()))

    fields = {}
    for i, (label, start, end) in enumerate(matches):
        nxt_start = matches[i + 1][1] if i + 1 < len(matches) else len(txt)
        val = txt[end:nxt_start].strip()
        # Ref ID sometimes includes a harmless header; strip it
        if label == "Ref ID":
            val = re.sub(r'Inquirer.?s Information', '', val, flags=re.IGNORECASE).strip()
        fields[label] = val

    # --- Normalize/clean fields ---
    name = fields.get("Contact Name", "").strip()
    first_name, last_name = (name.split(' ', 1) if ' ' in name else (name, ''))

    email = fields.get("Contact Email", "").strip()

    phone_raw = fields.get("Contact Phone", "").strip()
    phone = normalize_phone_us_e164(phone_raw)

    # Listing ID tends to be numeric; grab the first number if extras appear
    listing_id_raw = fields.get("Listing ID", "").strip()
    m_id = re.search(r'\d+', listing_id_raw)
    listing_id = m_id.group(0) if m_id else listing_id_raw

    ref_id = fields.get("Ref ID", "").strip()
    contact_zip = fields.get("Contact Zip", "").strip()
    investment_amount = fields.get("Able to Invest", "").strip()
    purchase_timeline = fields.get("Purchase Within", "").strip()

    comments = fields.get("Comments", "").strip()
    comments = clean_comments_block(comments)

    return {
        "first_name": first_name,
        "last_name": last_name,          # <-- now just "Vincent", not appended email
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
# ✅ FCBB (HTML) — First Choice Business Brokers (robust)
# ==============================
def extract_fcbb_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    label_map = {
        "First Name": "first_name",
        "Last Name": "last_name",
        "Email Address": "email",
        "Phone Number": "phone",
        "Address": "address",
        "City": "city",
        "State": "state",
        "Postal Code": "contact_zip",
        "Listing Number": "listing_id",
        "Listing Description": "listing_description",   # ← capture explicit field
        "Domain": "domain",
        "Originating Website": "originating_website",
        "Current Site Page URL": "current_site_page_url",
    }

    out = {k: "" for k in set(label_map.values())}

    for strong in soup.find_all("strong"):
        label_raw = strong.get_text(" ", strip=True).rstrip(":").strip()
        key = label_map.get(label_raw)
        if not key:
            continue

        td_label = strong.find_parent("td")
        tr = td_label.find_parent("tr") if td_label else None
        value = ""
        if tr:
            tds = tr.find_all("td")
            if len(tds) >= 2:
                cell = tds[-1]
                cell_text = cell.get_text(" ", strip=True)
                if key in ("originating_website", "current_site_page_url"):
                    url = first_http_url(cell_text)
                    if not url:
                        a = cell.find("a", href=True)
                        if a:
                            url = first_http_url(a.get_text(strip=True)) or a["href"]
                    value = url
                elif key == "email":
                    a = cell.find("a", href=True)
                    if a and a["href"].lower().startswith("mailto:"):
                        value = a.get_text(strip=True) or a["href"].split(":", 1)[-1]
                    else:
                        value = cell_text
                elif key == "phone":
                    a = cell.find("a", href=True)
                    if a and a["href"].lower().startswith("tel:"):
                        value = a.get_text(strip=True) or a["href"].split(":", 1)[-1]
                    else:
                        value = cell_text
                else:
                    value = cell_text

        if key == "city":
            value = value.rstrip(", ")
        out[key] = (value or "").strip()

    if not out.get("email"):
        a_mail = soup.find("a", href=lambda h: h and h.lower().startswith("mailto:"))
        if a_mail:
            out["email"] = a_mail.get_text(strip=True) or a_mail["href"].split(":", 1)[-1]
    if not out.get("phone"):
        a_tel = soup.find("a", href=lambda h: h and h.lower().startswith("tel:"))
        if a_tel:
            out["phone"] = a_tel.get_text(strip=True) or a_tel["href"].split(":", 1)[-1]

    out["phone"] = normalize_phone_us_e164(out.get("phone", ""))

    domain_val = (out.get("domain") or "").strip()
    if domain_val:
        out["domain"] = derive_domain(domain_val)
    else:
        out["domain"] = derive_domain(out.get("originating_website")) or derive_domain(out.get("current_site_page_url"))

    # headline = listing_description (when present)
    headline = out.get("listing_description", "")

    return {
        "first_name": out.get("first_name", ""),
        "last_name": out.get("last_name", ""),
        "email": out.get("email", ""),
        "phone": out.get("phone", ""),
        "ref_id": "",
        "listing_id": out.get("listing_id", ""),
        "headline": headline,                        # keep for compatibility
        "listing_description": headline,             # new explicit field
        "address": out.get("address", ""),
        "city": out.get("city", ""),
        "state": out.get("state", ""),
        "contact_zip": out.get("contact_zip", ""),
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",  # FCBB stays empty
        "originating_website": out.get("originating_website", ""),
        "current_site_page_url": out.get("current_site_page_url", ""),
        "domain": out.get("domain", ""),
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ FCBB (TEXT) — First Choice Business Brokers (robust)
# ==============================
def extract_fcbb_text(text_body):
    txt = re.sub(r'\s+', ' ', text_body.replace("\r", ""))

    labels = [
        "Domain", "Listing Number", "Listing Description",
        "First Name", "Last Name", "Email Address", "Phone Number",
        "Address", "City", "Postal Code", "Originating Website", "Current Site Page URL"
    ]
    label_group = "|".join(map(re.escape, labels))
    pattern = rf"(?P<label>{label_group}):\s*(?P<value>.*?)(?=(?:{label_group}):|$)"

    found = {}
    for m in re.finditer(pattern, txt, flags=re.S):
        lab = m.group("label")
        val = m.group("value").strip()
        found[lab] = val

    first_name = found.get("First Name", "")
    last_name  = found.get("Last Name", "")
    email      = found.get("Email Address", "")
    phone      = normalize_phone_us_e164(found.get("Phone Number", ""))
    address    = found.get("Address", "")
    city       = (found.get("City", "") or "").rstrip(", ")
    zip_code   = found.get("Postal Code", "")

    listing_id = (found.get("Listing Number", "") or "").strip()
    listing_id = re.split(r"\s+Listing Description\s*:", listing_id, 1)[0].strip()

    headline   = found.get("Listing Description", "").strip()
    originating_website   = first_http_url(found.get("Originating Website", ""))
    current_site_page_url = first_http_url(found.get("Current Site Page URL", ""))
    domain_label = found.get("Domain", "")
    domain = derive_domain(domain_label) or derive_domain(originating_website) or derive_domain(current_site_page_url)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": "",
        "listing_id": listing_id,
        "headline": headline,                       # keep for compatibility
        "listing_description": headline,            # new explicit field
        "address": address,
        "city": city,
        "state": "",
        "contact_zip": zip_code,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",  # FCBB stays empty
        "originating_website": originating_website,
        "current_site_page_url": current_site_page_url,
        "domain": domain,
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ Mapper to unified nested schema
# ==============================
def to_nested(source: str, flat: dict, error_debug: str = "") -> dict:
    flat = remove_not_disclosed_fields(flat or {})

    # For FCBB, DO NOT backfill listing_url from labeled fields
    if source == "fcbb":
        listing_url = flat.get("listing_url", "")
    else:
        listing_url = flat.get("listing_url", "") or flat.get("originating_website", "") or flat.get("current_site_page_url", "")

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
            "listing_url": listing_url,
            # ✅ Preserve FCBB-specific labels (and harmless for others if present)
            "originating_website": flat.get("originating_website", ""),
            "current_site_page_url": flat.get("current_site_page_url", ""),
            "domain": flat.get("domain", "")
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
        # FCBB detection
        if "fcbb.com" in lowered or "oms.fcbb.com" in lowered or "first choice business brokers" in lowered:
            try:
                # Use the text parser for text emails; HTML parser for HTML
                flat = extract_fcbb_html(body) if is_html else extract_fcbb_text(body)
                return jsonify(to_nested("fcbb", flat))
            except Exception as e:
                # Last-chance: strip tags to text and try the text parser
                try:
                    text_only = BeautifulSoup(body, "html.parser").get_text("\n")
                    flat = extract_fcbb_text(text_only)
                    return jsonify(to_nested("fcbb", flat, f"fallback_text_ok: {e}"))
                except Exception as e2:
                    return jsonify(to_nested("fcbb", {}, f"parse_failed: {e}; fallback_failed: {e2}"))

        if "bizbuysell" in lowered:
            try:
                flat = extract_bizbuysell_html(body) if is_html else extract_bizbuysell_text(body)
                return jsonify(to_nested("bizbuysell", flat))
            except Exception as e:
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
        return jsonify(to_nested("unknown", {}, f"router_error: {outer}"))

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
