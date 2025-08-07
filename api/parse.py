from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

def extract_bizbuysell_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    # Extract headline
    headline = None
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

    # Phone
    phone_tag = soup.find('b', string=re.compile('Contact Phone'))
    phone = phone_tag.find_next('span').get_text(strip=True) if phone_tag else ''
    phone = re.sub(r'\D', '', phone)

    # Ref ID
    ref_id_match = soup.find(string=re.compile('Ref ID'))
    ref_id = ref_id_match.find_next(string=True).strip() if ref_id_match else ''

    # Listing ID
    listing_id = ''
    span_tags = soup.find_all('span')
    for span in span_tags:
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
        "comments": comments
    }

def extract_bizbuysell_text(text_body):
    lines = text_body.replace('\r', '').split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    full_text = "\n".join(lines)

    def get(label):
        match = re.search(rf"{label}:\s*(.+)", full_text)
        return match.group(1).strip() if match else ''

    name = get("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    purchase_timeline = ''
    pt_match = re.search(r'Purchase Within:\s*(.*?)\s*Comments:', full_text, re.DOTALL)
    if pt_match:
        purchase_timeline = pt_match.group(1).strip()

    comments = ''
    cmt_match = re.search(r'Comments:\s*(.+)', full_text, re.DOTALL)
    if cmt_match:
        comments = cmt_match.group(1).split("You can reply")[0].strip()

    phone = get("Contact Phone")
    phone = re.sub(r'\D', '', phone)

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get("Contact Email"),
        "phone": phone,
        "ref_id": get("Ref ID"),
        "listing_id": get("Listing ID"),
        "headline": get("Ref ID").split("\n")[0] if get("Ref ID") else '',
        "contact_zip": get("Contact Zip"),
        "investment_amount": get("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments
    }

def extract_businessesforsale_text(text_body):
    lines = text_body.replace('\r', '').split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    name = email = phone = ref_id = headline = listing_url = comments = ''
    full_text = "\n".join(lines)

    name_match = re.search(r'Name:\s*(.+)', full_text)
    if name_match:
        name = name_match.group(1).strip()
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email_match = re.search(r'Email:\s*([\w\.-]+@[\w\.-]+)', full_text)
    if email_match:
        email = email_match.group(1).strip()

    phone_match = re.search(r'Tel:\s*([+()0-9\s-]+)', full_text)
    if phone_match:
        phone = re.sub(r'\D', '', phone_match.group(1).strip())

    ref_match = re.search(r'listing ref:(\d+)', full_text, re.IGNORECASE)
    if ref_match:
        ref_id = ref_match.group(1).strip()

    headline_match = re.search(r'listing ref:\d+\s*(.+)', full_text, re.IGNORECASE)
    if headline_match:
        headline = headline_match.group(1).strip()

    url_match = re.search(r'(https?://[^\s]+)', full_text)
    if url_match:
        listing_url = url_match.group(1).strip()

    try:
        msg_index = lines.index("has received the following message:")
        comments = lines[msg_index + 1]
    except:
        pass

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "headline": headline,
        "listing_url": listing_url,
        "comments": comments
    }

@app.route('/api/parse', methods=['POST'])
def parse_email():
    try:
        html_body = request.get_data(as_text=True)
        if not html_body:
            return jsonify({"error": "No email content provided."}), 400

        lowered = html_body.lower()

        if "bizbuysell" in lowered:
            if "<html" in lowered or "<body" in lowered or "<div" in lowered:
                parsed = extract_bizbuysell_html(html_body)
            else:
                parsed = extract_bizbuysell_text(html_body)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed})

        elif "businessesforsale.com" in lowered:
            parsed = extract_businessesforsale_text(html_body)
            return jsonify({"source": "businessesforsale", "parsed_data": parsed})

        return jsonify({"source": "unknown", "parsed_data": {}})
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run()
