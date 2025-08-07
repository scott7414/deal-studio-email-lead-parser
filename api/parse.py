from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

def extract_bizbuysell(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    # Extract actual source email from the "From:" row
    source = None
    source_block = soup.find(string=re.compile("From:"))
    if source_block:
        full_line = source_block
        if source_block.parent and source_block.parent.next_sibling:
            full_line += str(source_block.parent.next_sibling)
        match = re.search(r'[\w\.-]+@[\w\.-]+', full_line)
        if match:
            source = match.group(0)

    # Headline
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
    email = email_tag.find_next('span').get_text(strip=True) if email_tag else None

    # Phone
    phone_tag = soup.find('b', string=re.compile('Contact Phone'))
    phone = phone_tag.find_next('span').get_text(strip=True) if phone_tag else None

    # Ref ID
    ref_id_match = soup.find(text=re.compile('Ref ID'))
    ref_id = ref_id_match.find_next(text=True).strip() if ref_id_match else None

    # Listing ID
    listing_id = None
    span_tags = soup.find_all('span')
    for span in span_tags:
        if 'Listing ID:' in span.get_text():
            a = span.find_next('a')
            if a:
                listing_id = a.get_text(strip=True)
                break

    # Optional fields: robust extraction
    def extract_optional(label):
        try:
            tag = soup.find('b', string=re.compile(label))
            if tag:
                span = tag.find_next('span')
                if span:
                    return span.get_text(strip=True)
            return ''
        except Exception:
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
        "ref_id": ref_id or '',
        "listing_id": listing_id or '',
        "headline": headline or '',
        "source": source or '',
        "contact_zip": contact_zip,
        "investment_amount": investment_amount,
        "purchase_timeline": purchase_timeline,
        "comments": comments
    }

@app.route('/api/parse', methods=['POST'])
def parse_html():
    try:
        html_body = request.get_data(as_text=True)
        if not html_body:
            return jsonify({"error": "No HTML content provided."}), 400

        if "bizbuysell" in html_body.lower():
            parsed_data = extract_bizbuysell(html_body)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed_data})

        return jsonify({"source": "unknown", "parsed_data": {}})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run()
