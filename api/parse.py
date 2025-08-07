from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

def extract_bizbuysell(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    # ✅ Extract actual source email from the "From:" line
    source = None
    from_line = soup.find(string=re.compile("From:"))
    if from_line:
        combined_text = str(from_line)
        if from_line.parent:
            combined_text += str(from_line.parent)
            if from_line.parent.next_sibling:
                combined_text += str(from_line.parent.next_sibling)
        email_match = re.search(r'[\w\.-]+@[\w\.-]+', combined_text)
        if email_match:
            source = email_match.group(0)

    # ✅ Extract headline (ignore short/label bolds)
    headline = None
    for b in soup.find_all('b'):
        text = b.get_text(strip=True)
        if text.lower() != "from:" and len(text) > 10:
            headline = text
            break

    # ✅ Extract contact name
    name_tag = soup.find('b', string=re.compile('Contact Name'))
    name = name_tag.find_next('span').get_text(strip=True) if name_tag else ''
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # ✅ Extract contact email
    email_tag = soup.find('b', string=re.compile('Contact Email'))
    email = email_tag.find_next('span').get_text(strip=True) if email_tag else None

    # ✅ Extract contact phone
    phone_tag = soup.find('b', string=re.compile('Contact Phone'))
    phone = phone_tag.find_next('span').get_text(strip=True) if phone_tag else None

    # ✅ Extract Ref ID
    ref_id_match = soup.find(text=re.compile('Ref ID'))
    ref_id = ref_id_match.find_next(text=True).strip() if ref_id_match else None

    # ✅ Extract Listing ID
    listing_id = None
    span_tags = soup.find_all('span')
    for span in span_tags:
        if 'Listing ID:' in span.get_text():
            a = span.find_next('a')
            if a:
                listing_id = a.get_text(strip=True)
                break

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id or '',
        "listing_id": listing_id or '',
        "headline": headline,
        "source": source
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
