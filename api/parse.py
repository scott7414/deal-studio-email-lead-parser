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
# ✅ DealStream (HTML)
# ==============================
def extract_dealstream_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text = soup.get_text("\n")

    # Lead name — buyer/inquirer appears after "here is their information" section
    lead_name = ""
    m_info = re.search(r"here is their information", text, re.I)
    if m_info:
        # search after that section for a line preceding "Broker"
        after = text[m_info.end():]
        m_name = re.search(r"\n\s*([A-Z][A-Za-z' .-]+)\s*\n\s*Broker", after, re.I)
        if m_name:
            lead_name = m_name.group(1).strip()

    if not lead_name:
        # fallback: first capitalized line before "Broker"
        m_name = re.search(r"\n\s*([A-Z][A-Za-z' .-]+)\s*\n\s*Broker", text, re.I)
        if m_name:
            lead_name = m_name.group(1).strip()

    # Split only on the first space
    parts = lead_name.split(None, 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""

    # Email (strip out any trailing <mailto:...>)
    m_email = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    email = m_email.group(0).strip() if m_email else ""

    # Phone
    m_phone = re.search(r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}", text)
    phone = normalize_phone_us_e164(m_phone.group(0)) if m_phone else ""

    # Ref ID
    m_ref = re.search(r"Reference Number:\s*([0-9]+)", text, re.I)
    ref_id = m_ref.group(1).strip() if m_ref else ""

    return {
        "source": "dealstream",
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "headline": "",
        "listing_url": ""
    }


# ==============================
# ✅ DealStream (TEXT)
# ==============================
def extract_dealstream_text(text_body):
    txt = text_body.replace("\r", "")

    # Lead name — buyer/inquirer appears after "here is their information" section
    lead_name = ""
    m_info = re.search(r"here is their information", txt, re.I)
    if m_info:
        after = txt[m_info.end():]
        m_name = re.search(r"\n\s*([A-Z][A-Za-z' .-]+)\s*\n\s*Broker", after, re.I)
        if m_name:
            lead_name = m_name.group(1).strip()

    if not lead_name:
        # fallback: first capitalized line before "Broker"
        m_name = re.search(r"\n\s*([A-Z][A-Za-z' .-]+)\s*\n\s*Broker", txt, re.I)
        if m_name:
            lead_name = m_name.group(1).strip()

    # Clean any role suffixes just in case
    lead_name = re.sub(r"\b(Broker|Agent|Owner).*$", "", lead_name, flags=re.I).strip()

    # Split only on the first space
    parts = lead_name.split(None, 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""

    # Email (strip out any trailing <mailto:...>)
    m_email = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", txt)
    email = m_email.group(0).strip() if m_email else ""

    # Phone
    m_phone = re.search(r"(\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}", txt)
    phone = normalize_phone_us_e164(m_phone.group(0)) if m_phone else ""

    # Ref ID
    m_ref = re.search(r"Reference Number:\s*([0-9]+)", txt, re.I)
    ref_id = m_ref.group(1).strip() if m_ref else ""

    return {
        "source": "dealstream",
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "headline": "",
        "listing_url": ""
    }


# ==============================
# ✅ BizBuySell (HTML) — original pattern
# ==============================

def extract_bizbuysell_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text_content = soup.get_text(" ", strip=True)

    # --- Headline (first bold line that isn’t a field label)
    headline = ""
    for b in soup.find_all("b"):
        t = b.get_text(strip=True)
        if t and not re.search(r"^contact\s+", t, re.I):
            if len(t) > 8:
                headline = t
                break

    def get_field(label):
        # Find both <b> or <span> tags that contain the label
        stag = soup.find(lambda tag: tag.name in ["b", "span"] and label.lower() in tag.get_text(strip=True).lower())
        if stag:
            if label.lower() == "listing id":
                link = stag.find_next("a")
                if link:
                    return link.get_text(strip=True)

            if label.lower() == "ref id":
                sib = stag.next_sibling
                if sib:
                    return str(sib).strip().lstrip(":").strip()

            nxt = stag.find_next("span")
            if nxt:
                return nxt.get_text(strip=True)

            td = stag.find_parent("td")
            if td:
                raw = td.get_text(" ", strip=True)
                return re.sub(rf"{label}\s*:", "", raw, flags=re.I).strip()

        # Final fallback (regex on full text, stop at next label)
        m = re.search(rf"{label}\s*:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text_content, re.I)
        return m.group(1).strip() if m else ""

    # --- Contact fields ---
    name = get_field("Contact Name")
    first_name, last_name = name.split(" ", 1) if " " in name else (name, "")

    email = get_field("Contact Email")
    m_email = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email)
    email = m_email.group(0) if m_email else email

    phone = normalize_phone_us_e164(get_field("Contact Phone"))

    # IDs
    listing_id = get_field("Listing ID")
    ref_id = get_field("Ref ID")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": get_field("Contact Zip"),
        "investment_amount": get_field("Able to Invest"),
        "purchase_timeline": get_field("Purchase Within"),
        "comments": clean_comments_block(get_field("Comments")),
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

    headline = ""

    def get_after(label):
        """Match label followed by colon and capture its value (until newline or <br>)."""
        pattern = rf"{re.escape(label)}\s*:\s*([^\n\r<]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    # --- Base fields ---
    name = get_after("Name")
    first_name, last_name = name.split(" ", 1) if " " in name else (name, "")

    email = get_after("Email")
    contact_zip = get_after("ZIP/Postal Code")
    phone = normalize_phone_us_e164(get_after("Phone"))
    services = get_after("Services Interested In")
    heard = get_after("How did you hear about us?")
    if not heard:  # in some variants the question mark is omitted
        heard = get_after("How did you hear about us")

    # --- Listing / Ref ID ---
    # Some versions include "Listing Number:" or "Listing ID:"
    ref_id = get_after("Listing Number") or get_after("Listing ID")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,                    # now populated if listing number exists
        "listing_id": "",
        "headline": headline,
        "contact_zip": contact_zip,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": services,  # captured correctly
        "heard_about": heard                 # captured correctly
    }

# ==============================
# ✅ Murphy Business (TEXT) — original pattern
# ==============================
def extract_murphy_text(text_body):
    text = text_body.replace('\r', '')

    headline = ''

    def get_after(label):
        """Generic label finder that captures text until newline."""
        pattern = rf"{re.escape(label)}\s*:\s*([^\n\r]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    # --- Base fields ---
    name = get_after("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email = get_after("Email")
    contact_zip = get_after("ZIP/Postal Code")
    phone = normalize_phone_us_e164(get_after("Phone"))
    services = get_after("Services Interested In")
    heard = get_after("How did you hear about us?")
    if not heard:
        heard = get_after("How did you hear about us")  # fallback without question mark

    # --- Listing / Ref ID ---
    ref_id = get_after("Listing Number") or get_after("Listing ID")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,                    # ✅ populated when listing number exists
        "listing_id": "",
        "headline": headline,
        "contact_zip": contact_zip,
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "services_interested_in": services,  # ✅ preserved
        "heard_about": heard                 # ✅ preserved
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
        "Listing Number": "ref_id",   # ⚡ switched to ref_id
        "Listing Description": "listing_description",
        "Domain": "domain",
        "Originating Website": "originating_website",
        "Current Site Page URL": "current_site_page_url",
    }

    out = {k: "" for k in set(label_map.values())}

    # --- Standard format (label-based) ---
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
    if not any(v for k, v in out.items() if k in ("first_name","last_name","ref_id","email","phone")):
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]

        if ps:
            parts = ps[0].split(" ", 1)
            out["first_name"] = parts[0]
            out["last_name"] = parts[1] if len(parts) > 1 else ""

        if len(ps) > 1:
            listing_line = ps[1]
            m = re.match(r"(\d{3}-\d+)\s+(.*)", listing_line)
            if m:
                out["ref_id"] = m.group(1)                # ⚡ now stored as ref_id
                out["listing_description"] = m.group(2)

        mailto = soup.find("a", href=lambda h: h and h.lower().startswith("mailto:"))
        if mailto:
            out["email"] = mailto.get_text(strip=True)

        tel = soup.find("a", href=lambda h: h and h.lower().startswith("tel:"))
        if tel and tel.get("href"):
            out["phone"] = normalize_phone_us_e164(tel.get("href").split(":")[-1])

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
        "ref_id": out.get("ref_id", ""),        # ⚡ now populated
        "listing_id": "",                       # left empty
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
    txt = text_body.replace("\r", "")

    # ----------------------------
    # Try standard label-based FCBB format first
    # ----------------------------
    labels = [
        "Domain", "Listing Number", "Listing Description",
        "First Name", "Last Name", "Email Address", "Phone Number",
        "Address", "City", "Postal Code", "Originating Website", "Current Site Page URL"
    ]
    label_group = "|".join(map(re.escape, labels))
    pattern = rf"(?P<label>{label_group}):\s*(?P<value>.*?)(?=(?:{label_group}):|$)"

    found = {}
    for m in re.finditer(pattern, re.sub(r"\s+", " ", txt), flags=re.S):
        lab = m.group("label")
        val = m.group("value").strip()
        found[lab] = val

    if found:  # ✅ Structured label-based parse
        first_name = found.get("First Name", "")
        last_name  = found.get("Last Name", "")
        email      = found.get("Email Address", "")
        phone      = normalize_phone_us_e164(found.get("Phone Number", ""))
        address    = found.get("Address", "")
        city       = (found.get("City", "") or "").rstrip(", ")
        zip_code   = found.get("Postal Code", "")

        ref_id = (found.get("Listing Number", "") or "").strip()
        ref_id = re.split(r"\s+Listing Description\s*:", ref_id, 1)[0].strip()

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
            "ref_id": ref_id,
            "listing_id": "",
            "headline": headline,
            "listing_description": headline,
            "address": address,
            "city": city,
            "state": "",
            "contact_zip": zip_code,
            "investment_amount": "",
            "purchase_timeline": "",
            "comments": "",
            "listing_url": "",
            "originating_website": originating_website,
            "current_site_page_url": current_site_page_url,
            "domain": domain,
            "services_interested_in": "",
            "heard_about": ""
        }

    # ----------------------------
    # Fallback: freeform "alternate" FCBB text
    # ----------------------------
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]

    # 🚫 Filter out noise (image links, tracking pixels, disclaimers)
    noise_patterns = [
        r"^\[https?://",       # square-bracketed URLs
        r"^First Choice Business Brokers", 
        r"© 20\d{2} First Choice",
        r"^Alert -",            # NDA alerts
    ]
    clean_lines = []
    for ln in lines:
        if any(re.match(pat, ln, re.I) for pat in noise_patterns):
            continue
        clean_lines.append(ln)

    out = {"first_name": "", "last_name": "", "email": "", "phone": "", "ref_id": "", "headline": ""}

    if clean_lines:
        # Name
        name = clean_lines[0]
        parts = name.split(" ", 1)
        out["first_name"] = parts[0]
        out["last_name"] = parts[1] if len(parts) > 1 else ""

    # ID + headline
    for ln in clean_lines[1:]:
        m = re.match(r"(\d{3}-\d+)\s+(.*)", ln)
        if m:
            out["ref_id"] = m.group(1)
            out["headline"] = m.group(2)
            break

    # Phone
    for ln in clean_lines:
        if re.search(r"\d{3}[-)\s]\d{3}", ln):  # crude phone pattern
            out["phone"] = normalize_phone_us_e164(ln)
            break

    # Email
    for ln in clean_lines:
        m_email = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", ln)
        if m_email:
            out["email"] = m_email.group(0)
            break

    return {
        "first_name": out["first_name"],
        "last_name": out["last_name"],
        "email": out["email"],
        "phone": out["phone"],
        "ref_id": out["ref_id"],
        "listing_id": "",
        "headline": out["headline"],
        "listing_description": out["headline"],
        "address": "",
        "city": "",
        "state": "",
        "contact_zip": "",
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": "",
        "listing_url": "",
        "originating_website": "",
        "current_site_page_url": "",
        "domain": "fcbb.com",   # default fallback
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ Restaurants-For-Sale (HTML)
# ==============================
def extract_restaurantsforsale_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text = soup.get_text("\n", strip=True)

    # --- Name ---
    m_name = re.search(r"Name\s*\n([^\n]+)", text, re.I)
    full_name = (m_name.group(1).strip() if m_name else "")
    if " " in full_name:
        first_name, last_name = full_name.split(" ", 1)
    else:
        first_name, last_name = full_name, ""

    # --- Email ---
    m_email = re.search(r"Email\s*\n([^\n]+)", text, re.I)
    email = m_email.group(1).strip() if m_email else ""

    # --- Phone ---
    m_phone = re.search(r"Phone Number\s*\n([^\n]+)", text, re.I)
    raw_phone = m_phone.group(1).strip() if m_phone else ""
    phone = normalize_phone_us_e164(raw_phone)

    # --- Message & Ref ID ---
    m_msg = re.search(r"Message\s*\n(.+)$", text, re.I | re.S)
    msg = m_msg.group(1).strip() if m_msg else ""

    # ref_id = text after "regarding"
    m_ref = re.search(r"regarding\s+([A-Za-z0-9\-]+)", msg, re.I)
    ref_id = m_ref.group(1).strip() if m_ref else ""

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": "",
        "headline": "",
        "address": "",
        "city": "",
        "state": "",
        "country": "",
        "contact_zip": "",
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": msg,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }


# ==============================
# ✅ Restaurants-For-Sale (TEXT)
# ==============================
def extract_restaurantsforsale_text(text_body):
    txt = text_body.replace("\r", "").strip()

    # --- Name ---
    m_name = re.search(r"Name\s*\n([^\n]+)", txt, re.I)
    full_name = (m_name.group(1).strip() if m_name else "")
    if " " in full_name:
        first_name, last_name = full_name.split(" ", 1)
    else:
        first_name, last_name = full_name, ""

    # --- Email ---
    m_email = re.search(r"Email\s*\n([^\n]+)", txt, re.I)
    email = m_email.group(1).strip() if m_email else ""

    # --- Phone ---
    m_phone = re.search(r"Phone Number\s*\n([^\n]+)", txt, re.I)
    raw_phone = m_phone.group(1).strip() if m_phone else ""
    phone = normalize_phone_us_e164(raw_phone)

    # --- Message block ---
    m_msg = re.search(r"Message\s*\n(.+)$", txt, re.I | re.S)
    msg = m_msg.group(1).strip() if m_msg else ""

    # --- Ref ID (after "regarding") ---
    m_ref = re.search(r"regarding\s+([A-Za-z0-9\-]+)", msg, re.I)
    ref_id = m_ref.group(1).strip() if m_ref else ""

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": "",
        "headline": "",
        "address": "",
        "city": "",
        "state": "",
        "country": "",
        "contact_zip": "",
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": msg,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ==============================
# ✅ FranchiseResales.com (TEXT)
# ==============================
def extract_franchiseresales_text(text_body):
    txt = text_body.replace("\r", "").strip()

    # --- Listing title (headline) ---
    # First line after the reference sentence
    m_head = re.search(
        r"in reference to the following listing:\s*\n([^\n]+)",
        txt,
        re.I
    )
    headline = m_head.group(1).strip() if m_head else ""

    # --- URL ---
    m_url = re.search(r"URL:\s*(https?://\S+)", txt, re.I)
    listing_url = m_url.group(1).strip() if m_url else ""

    # --- Internal Listing ID ---
    m_ref = re.search(r"Internal Listing ID\s*([A-Za-z0-9\-]+)", txt, re.I)
    ref_id = m_ref.group(1).strip() if m_ref else ""

    # --- Contact fields ---
    def get_after(label):
        m = re.search(rf"{re.escape(label)}:\s*([^\n]+)", txt, re.I)
        return m.group(1).strip() if m else ""

    full_name = get_after("Contact Name")
    if " " in full_name:
        first_name, last_name = full_name.split(" ", 1)
    else:
        first_name, last_name = full_name, ""

    phone = normalize_phone_us_e164(get_after("Contact Phone"))
    email = get_after("Contact E-mail")
    comments = get_after("Contact Message")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": "",
        "headline": headline,
        "address": "",
        "city": "",
        "state": "",
        "country": "",
        "contact_zip": "",
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": listing_url,
        "services_interested_in": "",
        "heard_about": ""
    }

# ====================================
# ✅ LoopNet (TEXT Email)
# ====================================
def extract_loopnet_text(text_body):
    txt = text_body.replace("\r", "").strip()

    # --- Extract the FROM line ---
    # Example:
    # From: Tyler Smith | +1 470-643-7013 | subtosharks@gmail.com | (Listing ID : 38357782)
    m_from = re.search(
        r"From:\s*(.+?)\|\s*(.+?)\|\s*([^\|]+?)\|\s*\(Listing ID\s*:\s*([0-9]+)\)",
        txt,
        re.I
    )

    full_name = phone_raw = email = ref_id = ""

    if m_from:
        full_name = m_from.group(1).strip()
        phone_raw = m_from.group(2).strip()
        email = m_from.group(3).strip()
        ref_id = m_from.group(4).strip()

    # --- Name Split ---
    if " " in full_name:
        first_name, last_name = full_name.split(" ", 1)
    else:
        first_name, last_name = full_name, ""

    # --- Phone ---
    phone = normalize_phone_us_e164(phone_raw)

    # No buyer message in LoopNet leads
    comments = ""

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": "",
        "headline": "",
        "address": "",
        "city": "",
        "state": "",
        "country": "",
        "contact_zip": "",
        "investment_amount": "",
        "purchase_timeline": "",
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }

# ====================================
# ✅ LoopNet (HTML Email)
# ====================================
def extract_loopnet_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text = soup.get_text("\n", strip=True)

    # Reuse the text parser
    return extract_loopnet_text(text)



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
        # --- FCBB ---
        if "fcbb.com" in lowered or "oms.fcbb.com" in lowered or "first choice business brokers" in lowered:
            flat = extract_fcbb_html(body) if is_html else extract_fcbb_text(body)
            return jsonify(to_nested("fcbb", flat))

        # --- BizBuySell ---
        elif "bizbuysell" in lowered:
            flat = extract_bizbuysell_html(body) if is_html else extract_bizbuysell_text(body)
            return jsonify(to_nested("bizbuysell", flat))

        # --- BusinessesForSale ---
        elif "businessesforsale.com" in lowered or "businesses for sale" in lowered:
            flat = extract_businessesforsale_text(
                body if not is_html else BeautifulSoup(body, "html.parser").get_text("\n")
            )
            return jsonify(to_nested("businessesforsale", flat))

        # --- DealStream ---
        elif "dealstream" in lowered or "leads.dealstream.com" in lowered:
            flat = extract_dealstream_html(body) if is_html else extract_dealstream_text(body)
            return jsonify(to_nested("dealstream", flat))

        # --- Murphy Business ---
        elif "murphybusiness.com" in lowered or "murphy business" in lowered:
            flat = extract_murphy_html(body) if is_html else extract_murphy_text(body)
            return jsonify(to_nested("murphybusiness", flat))

        # --- BusinessBroker.net ---
        elif "businessbroker.net" in lowered:
            flat = extract_businessbroker_html(body) if is_html else extract_businessbroker_text(body)
            return jsonify(to_nested("businessbroker", flat))

                # --- RestaurantsForSale ---
        elif "restaurants-for-sale.com" in lowered or "restaurants for sale online" in lowered:
            flat = extract_restaurantsforsale_html(body) if is_html else extract_restaurantsforsale_text(body)
            return jsonify(to_nested("restaurantsforsale", flat))

                # --- FranchiseResales ---
        elif "franchiseresales.com" in lowered or "franchise resales" in lowered:
            flat = extract_franchiseresales_text(
                body if not is_html else BeautifulSoup(body, "html.parser").get_text("\n")
            )
            return jsonify(to_nested("franchiseresales", flat))

                # --- LoopNet ---
        elif "loopnet.com" in lowered or "loopnet" in lowered:
            flat = extract_loopnet_html(body) if is_html else extract_loopnet_text(body)
            return jsonify(to_nested("loopnet", flat))


        # --- Unknown ---
        else:
            return jsonify(to_nested("unknown", {}))

    except Exception as outer:
        return jsonify(to_nested("unknown", {}, f"router_error: {outer}"))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
