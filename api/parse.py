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

def parse_address_loose(addr: str, default_country: str = "") -> dict:
    """
    Heuristic parser for common formats (US, UK, Canada) from a single line.
    Returns {address1, city, state, zip, country}.
    Safe to call on footer-like lines; if nothing matches, returns mostly empty.
    """
    if not addr:
        return {"address1": "", "city": "", "state": "", "zip": "", "country": default_country or ""}

    s = re.sub(r'\s+', ' ', addr.strip())
    s = s.strip(' .')  # trim trailing periods/spaces

    # Pull out an explicit country at the end if present
    country = default_country or ""
    country_map = {
        r'\b(united\s+kingdom|uk)\b': 'United Kingdom',
        r'\b(united\s+states|usa|us)\b': 'United States',
        r'\b(canada)\b': 'Canada',
        r'\b(england|scotland|wales|northern\s+ireland)\b': 'United Kingdom',  # treated as UK
    }
    tail = s.lower()
    for pat, name in country_map.items():
        m = re.search(pat + r'\.?$', tail)  # only at end
        if m:
            country = name
            s = s[:m.start()].strip(' ,.')
            break

    # Regexes
    us_zip_re = re.compile(r'\b\d{5}(?:-\d{4})?\b')
    us_state_re = re.compile(r'\b(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VA|VT|WA|WI|WV|WY)\b', re.I)

    ca_postal_re = re.compile(r'\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d\b', re.I)

    # UK postcode (two parts to preserve the space)
    uk_postal_re = re.compile(r'\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b', re.I)

    parts = [p.strip(' .,') for p in re.split(r'[;,]', s) if p.strip(' .,')]
    # Try UK
    m_uk = uk_postal_re.search(s)
    if m_uk:
        zip_code = (m_uk.group(1).upper() + " " + m_uk.group(2).upper()).strip()
        # City: token immediately before the postcode (by comma split)
        city = ""
        before = s[:m_uk.start()].strip(' ,.')
        before_parts = [p.strip() for p in re.split(r'[;,]', before) if p.strip()]
        if before_parts:
            city = before_parts[-1]
        # Address1: everything before city
        address1 = ", ".join(before_parts[:-1]) if len(before_parts) > 1 else ""
        # State is not generally used for UK (optionally use England/Scotland… if you want)
        state = ""
        return {
            "address1": address1,
            "city": city,
            "state": state,
            "zip": zip_code,
            "country": country or "United Kingdom"
        }

    # Try US
    m_us_zip = us_zip_re.search(s)
    if m_us_zip:
        zip_code = m_us_zip.group(0)
        before = s[:m_us_zip.start()].strip(' ,.')
        after = s[m_us_zip.end():].strip(' ,.')

        # Try to find state (2-letter) immediately before ZIP in the "before" chunk
        state = ""
        city = ""
        bparts = [p.strip() for p in re.split(r'[;,]', before) if p.strip()]
        if bparts:
            last = bparts[-1]
            m_state = us_state_re.search(last)
            if m_state:
                state = m_state.group(1).upper()
                # city = text before state in that part (or previous part)
                city = last[:m_state.start()].strip(' ,') or (bparts[-2] if len(bparts) >= 2 else "")
                # address1 = everything before the city block
                address1 = ", ".join(bparts[:-1]) if len(bparts) > 1 else ""
            else:
                # No explicit state: assume last part is city, rest is address1
                city = last
                address1 = ", ".join(bparts[:-1]) if len(bparts) > 1 else ""
        else:
            address1 = ""
        return {
            "address1": address1,
            "city": city,
            "state": state,
            "zip": zip_code,
            "country": country or "United States"
        }

    # Try Canada
    m_ca = ca_postal_re.search(s)
    if m_ca:
        zip_code = m_ca.group(0).upper()
        before = s[:m_ca.start()].strip(' ,.')
        bparts = [p.strip() for p in re.split(r'[;,]', before) if p.strip()]
        city = bparts[-1] if bparts else ""
        address1 = ", ".join(bparts[:-1]) if len(bparts) > 1 else ""
        state = ""  # (Province isn’t parsed here—can be added similarly to US states if needed)
        return {
            "address1": address1,
            "city": city,
            "state": state,
            "zip": zip_code,
            "country": country or "Canada"
        }

    # Fallback: return as address1
    return {"address1": s, "city": "", "state": "", "zip": "", "country": country}


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
      - Footer after 'Comments:' is trimmed so it doesn't leak into comments.
    """
    txt = text_body.replace('\r', '')

    # --- Headline (unchanged) ---
    headline = ''
    h_match = re.search(r"regarding your listing:\s*(.*?)\s*Listing ID", txt, re.DOTALL | re.IGNORECASE)
    if h_match:
        headline = h_match.group(1).strip()

    # --- Labels & bounded extraction ---
    labels = [
        "Contact Name", "Contact Email", "Contact Phone", "Contact Zip",
        "Able to Invest", "Purchase Within", "Comments", "Listing ID", "Ref ID"
    ]

    def label_to_re(l):
        # Tolerate newlines/extra spaces inside labels, e.g. "Contact\nPhone:"
        return r"\b" + r"\s*".join(map(re.escape, l.split())) + r"\s*:"

    label_union = "|".join(f"({label_to_re(l)})" for l in labels)
    label_re = re.compile(label_union, flags=re.IGNORECASE)

    def _norm(s): return re.sub(r"\s+", "", s).lower()
    canon_map = {_norm(l): l for l in labels}

    matches = []
    for m in label_re.finditer(txt):
        matched = m.group(0)
        label_no_colon = re.sub(r":\s*$", "", matched)
        label_norm = _norm(re.sub(r"\s+", " ", label_no_colon))
        canon = canon_map.get(label_norm)
        if canon:
            matches.append((canon, m.start(), m.end()))

    fields = {}
    for i, (label, start, end) in enumerate(matches):
        nxt_start = matches[i + 1][1] if i + 1 < len(matches) else len(txt)
        val = txt[end:nxt_start].strip()
        # Ref ID sometimes includes a stray header; strip it
        if label == "Ref ID":
            val = re.sub(r'Inquirer.?s Information', '', val, flags=re.IGNORECASE).strip()
        fields[label] = val

    # --- Normalize/clean fields ---
    name = fields.get("Contact Name", "").strip()
    first_name, last_name = (name.split(' ', 1) if ' ' in name else (name, ''))

    # CHANGED: extract only the first real email token from the segment
    email_raw = fields.get("Contact Email", "").strip()
    m_email = re.search(r'(?<!/)[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', email_raw)
    email = m_email.group(0) if m_email else (email_raw.split()[0] if email_raw else "")

    # CHANGED: extract only the first phone token from the segment, then normalize
    phone_block = fields.get("Contact Phone", "")
    m_phone = re.search(r'(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}', phone_block)
    phone = normalize_phone_us_e164(m_phone.group(0) if m_phone else phone_block)

    # Listing ID → first number if extra text exists
    listing_id_raw = fields.get("Listing ID", "").strip()
    m_id = re.search(r'\d+', listing_id_raw)
    listing_id = m_id.group(0) if m_id else listing_id_raw

    ref_id = fields.get("Ref ID", "").strip()
    contact_zip = fields.get("Contact Zip", "").strip()
    investment_amount = fields.get("Able to Invest", "").strip()
    purchase_timeline = fields.get("Purchase Within", "").strip()

    # --- Comments: strip BizBuySell footer + bracketed URLs, then run generic cleaner ---
    def _trim_bizbuysell_footer(s: str) -> str:
        if not s:
            return ""
        # Remove bracketed URLs like [https://...]
        s = re.sub(r'\[https?://[^\]]+\]', '', s)
        # Cut off known footer markers
        footer_markers = [
            r'You can reply directly to this email',
            r'We take our lead quality',
            r'Thank you,\s*BizBuySell',
            r'Unsubscribe',
            r'Email Preferences',
            r'Terms of Use',
            r'Privacy Notice',
            r'Contact Us',
            r'This system email was sent to you by BizBuySell'
        ]
        pat = re.compile(r'(?is)\b(?:' + '|'.join(footer_markers) + r')\b')
        m = pat.search(s)
        if m:
            s = s[:m.start()]
        return s.strip()

    comments_raw = fields.get("Comments", "").strip()
    comments = clean_comments_block(_trim_bizbuysell_footer(comments_raw))

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,          # now guaranteed to be just the address
        "phone": phone,          # handles (832)\n453-6114
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

    # ---- Robust ref/headline/url block (hyphen-aware, case-insensitive) ----
    block = re.search(
        r"(?is)your\s+listing\s+ref\s*:\s*([A-Za-z0-9\-]+)\s+(.+?)\s*\n(https?://\S+)",
        full_text
    )
    ref_id, headline, listing_url = '', '', ''
    if block:
        ref_id, headline, listing_url = block.groups()
        ref_id = ref_id.strip()
        headline = headline.strip()
        listing_url = listing_url.strip()
    else:
        # Fallback: capture ref id, headline remainder, and first URL after it
        m_ref = re.search(r"(?is)your\s+listing\s+ref\s*:\s*([A-Za-z0-9\-]+)", full_text)
        if m_ref:
            ref_id = m_ref.group(1).strip()
            start = m_ref.end()
            m_head = re.search(r"\s+([^\n]+)", full_text[start:])
            if m_head:
                headline = m_head.group(1).strip()
            m_url = re.search(r"https?://\S+", full_text[start:])
            if m_url:
                listing_url = m_url.group(0).strip()

    # Simple field getter (line-scoped)
    def get_field(label):
        m = re.search(rf"{re.escape(label)}:\s*(.+)", full_text)
        return m.group(1).strip() if m else ''

    name = get_field("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # Phone / Email
    phone = normalize_phone_us_e164(get_field("Tel"))
    email = get_field("Email")

    # ---- Address parsing (publisher footer or buyer if ever present) ----
    # If you don't want publisher addresses, remove this block.
    address = city = state = country = ""
    contact_zip = ""   # we will prefer parsed zip if found
    m_addr = re.search(r"(?im)^\s*Address:\s*(.+)$", full_text)
    if m_addr:
        addr_raw = m_addr.group(1).strip(' .')
        parsed = parse_address_loose(addr_raw)
        address     = parsed["address1"]
        city        = parsed["city"]
        state       = parsed["state"]
        contact_zip = parsed["zip"] or ""
        country     = parsed["country"]

    # Comments (tolerant to spacing)
    comments = ''
    cmt = re.search(r"(?is)has received the following message:\s*(.+?)\s*Name\s*:", full_text)
    if cmt:
        comments = cmt.group(1).strip()
    comments = clean_comments_block(comments)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,                 # e.g., "101-24414"
        "listing_id": "",
        "headline": headline,
        "address": address,               # ← now populated (if Address: is present)
        "city": city,
        "state": state,
        "country": country,
        "contact_zip": contact_zip,       # ← from parsed address if found
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
        "Listing Description": "listing_description",
        "Domain": "domain",
        "Originating Website": "originating_website",
        "Current Site Page URL": "current_site_page_url",
    }

    out = {k: "" for k in set(label_map.values())}

    # --- Standard FCBB format (with <strong> labels in table rows) ---
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

    # --- Fallback for stripped-down <p> block format ---
    if not any(v for k, v in out.items() if k in ("first_name","last_name","listing_id","email","phone")):
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]

        # Name
        if ps:
            parts = ps[0].split(" ", 1)
            out["first_name"] = parts[0]
            out["last_name"] = parts[1] if len(parts) > 1 else ""

        # Listing line (ID + headline)
        if len(ps) > 1:
            listing_line = ps[1]
            m = re.match(r"(\d{3}-\d+)\s+(.*)", listing_line)
            if m:
                out["listing_id"] = m.group(1)
                out["listing_description"] = m.group(2)

        # Email
        mailto = soup.find("a", href=lambda h: h and h.lower().startswith("mailto:"))
        if mailto:
            out["email"] = mailto.get_text(strip=True)

        # Phone
        tel = soup.find("a", href=lambda h: h and h.lower().startswith("tel:"))
        if tel and tel.get("href"):
            out["phone"] = normalize_phone_us_e164(tel.get("href").split(":")[-1])

    # --- Normalize ---
    out["phone"] = normalize_phone_us_e164(out.get("phone", ""))
    if out.get("domain"):
        out["domain"] = derive_domain(out["domain"])
    else:
        out["domain"] = derive_domain(out.get("originating_website")) or derive_domain(out.get("current_site_page_url"))

    headline = out.get("listing_description", "")

    return {
        "first_name": out.get("first_name", ""),
        "last_name": out.get("last_name", ""),
        "email": out.get("email", ""),
        "phone": out.get("phone", ""),
        "ref_id": "",
        "listing_id": out.get("listing_id", ""),
        "headline": headline,
        "listing_description": headline,
        "address": out.get("address", ""),
        "city": out.get("city", ""),
        "state": out.get("state", ""),
        "contact_zip": out.get("contact_zip", ""),
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
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
