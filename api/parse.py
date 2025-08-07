from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

def clean_phone_number(phone):
    if not phone:
        return ''
    return re.sub(r'\D', '', phone)

def extract_headline_from_text(text):
    match = re.search(r'lead regarding your listing:\s*(.+?)\s*Listing ID:', text)
    return match.group(1).strip() if match else ''

def extract_bizbuysell_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    def extract_optional(label):
        try:
            tag = soup.find('b', string=re.compile(label))
            if tag:
                span = tag.find_next('span')
                return span.get_text(strip=True) if span else ''
        except Exception:
            pass
        return ''

    name_tag = soup.find('b', string=re.compile('Contact Name'))
    name = name_tag.find_next('span').get_text(strip=True) if name_tag else ''
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email = extract_optional('Contact Email')
    phone = clean_phone_number(extract_optional('Contact Phone'))
    ref_id = extract_optional('Ref ID')
    listing_id = None
    for span in soup.find_all('span'):
        if 'Listing ID:' in span.get_text():
            a = span.find_next('a')
            listing_id = a.get_text(strip=True) if a else ''
            break

    headline = None
    for b in soup.find_all('b'):
        txt = b.get_text(strip=True)
        if txt.lower() != "from:" and len(txt) > 10:
            headline = txt
            break

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": listing_id or '',
        "headline": headline or '',
        "contact_zip": extract_optional("Contact Zip"),
        "investment_amount": extract_optional("Able to Invest"),
        "purchase_timeline": extract_optional("Purchase Within"),
        "comments": extract_optional("Comments")
    }

def extract_bizbuysell_text(text):
    def get(label):
        match = re.search(rf'{label}:\s*(.*)', text)
        return match.group(1).strip() if match else ''

    purchase_within = ''
    comments = ''
    pw_match = re.search(r'Purchase Within:\s*(.*?)\s*Comments:', text, re.DOTALL)
    if pw_match:
        purchase_within = pw_match.group(1).strip()
    comments_match = re.search(r'Comments:\s*(.*)', text, re.DOTALL)
    if comments_match:
        comments = comments_match.group(1).strip()

    name = get("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')
    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get("Contact Email"),
        "phone": clean_phone_number(get("Contact Phone")),
        "ref_id": get("Ref ID"),
        "listing_id": get("Listing ID"),
        "headline": extract_headline_from_text(text),
        "contact_zip": get("Contact Zip"),
        "investment_amount": get("Able to Invest"),
        "purchase_timeline": purchase_within,
        "comments": comments
    }

def extract_businessesforsale(text):
    name_match = re.search(r'Name:\s*(.*)', text)
    email_match = re.search(r'Email:\s*(.*)', text)
    phone_match = re.search(r'Tel:\s*(.*)', text)
    message_match = re.search(r'has received the following message:\s*\n\n(.*?)\n\nName:', text, re.DOTALL)
    listing_url_match = re.search(r'(https://us\.businessesforsale\.com/[^\s]+)', text)
    headline_match = re.search(r'listing ref:\s*\d+\s+(.*)', text)
    ref_id_match = re.search(r'listing ref:(\d+)', text)

    name = name_match.group(1).strip() if name_match else ''
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email_match.group(1).strip() if email_match else '',
        "phone": clean_phone_number(phone_match.group(1)) if phone_match else '',
        "comments": message_match.group(1).strip() if message_match else '',
        "listing_url": listing_url_match.group(1) if listing_url_match else '',
        "headline": headline_match.group(1).strip() if headline_match else '',
        "ref_id": ref_id_match.group(1).strip() if ref_id_match else ''
    }

@app.route('/api/parse', methods=['POST'])
def parse_html():
    try:
        content = request.get_data(as_text=True)
        if not content:
            return jsonify({"error": "No email content provided."}), 400

        lower = content.lower()

        if "bizbuysell" in lower:
            if "<html" in lower:
                data = extract_bizbuysell_html(content)
            else:
                data = extract_bizbuysell_text(content)
            return jsonify({"source": "bizbuysell", "parsed_data": data})

        if "businessesforsale" in lower:
            data = extract_businessesforsale(content)
            return jsonify({"source": "businessesforsale", "parsed_data": data})

        return jsonify({"source": "unknown", "parsed_data": {}})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run()
