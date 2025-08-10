from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

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

    # Drop common extensions at the end (ext 123, x123, extension 123)
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
        # Last resort: try to capture the last 10 digits
        m = re.search(r'(\d{10})$', digits)
        if not m:
            return ''
        national = m.group(1)

    return '+1' + national


# =========================
# BizBuySell (HTML)
# =========================
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

    # Ref ID (works when "Ref ID:" and value are split oddly)
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

    # Standardized set
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


# =========================
# BizBuySell (TEXT)
# =========================
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
        "investment_amount": get("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments,
        "listing_url": "",
        "services_interested_in": "",
        "heard_about": ""
    }


# =========================
# BusinessesForSale (TEXT)
# =========================
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
        "heard_about": ""
    }


# =========================
# Murphy Business (HTML)
# =========================
def extract_murphy_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    text = soup.get_text(separator="\n")

    # Headline (Subject)
    headline = ''
    subj = re.search(r"Subject:\s*(.+)", text, re.IGNORECASE)
    if subj:
        headline = subj.group(1).strip()

    # Flexible field grabber
    def get_after(label):
        pattern = rf"{label}\s*:\s*([^\n\r]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    name = get_after("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email = get_after("Email")
    contact_zip = get_after("ZIP/Postal Code")
    # Phone (E.164)
    phone = normalize_phone_us_e164(get_after("Phone"))
    services = get_after("Services Interested In")
    heard = get_after("How did you hear about us\??")  # allow optional ?

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


# =========================
# Murphy Business (TEXT)
# =========================
def extract_murphy_text(text_body):
    text = text_body.replace('\r', '')

    headline = ''
    subj = re.search(r"Subject:\s*(.+)", text, re.IGNORECASE)
    if subj:
        headline = subj.group(1).strip()

    def get_after(label):
        pattern = rf"{label}\s*:\s*([^\n\r]+)"
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    name = get_after("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email = get_after("Email")
    contact_zip = get_after("ZIP/Postal Code")
    # Phone (E.164)
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


# =========================
# Router
# =========================
@app.route('/api/parse', methods=['POST'])
def parse_email():
    try:
        html_body = request.get_data(as_text=True)
        if not html_body:
            return jsonify({"error": "No email content provided."}), 400

        lowered = html_body.lower()
        is_html = ("<html" in lowered) or ("<body" in lowered) or ("<div" in lowered)

        if "bizbuysell" in lowered:
            parsed = extract_bizbuysell_html(html_body) if is_html else extract_bizbuysell_text(html_body)
            parsed = remove_not_disclosed_fields(parsed)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed})

        if "businessesforsale.com" in lowered:
            parsed = extract_businessesforsale_text(html_body)
            parsed = remove_not_disclosed_fields(parsed)
            return jsonify({"source": "businessesforsale", "parsed_data": parsed})

        if "murphybusiness.com" in lowered or "murphy business" in lowered:
            parsed = extract_murphy_html(html_body) if is_html else extract_murphy_text(html_body)
            parsed = remove_not_disclosed_fields(parsed)
            return jsonify({"source": "murphybusiness", "parsed_data": parsed})

        # Unknown
        empty = {
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
        return jsonify({"source": "unknown", "parsed_data": empty})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    app.run()
