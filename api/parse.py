from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

# -----------------------------
# BizBuySell HTML Parser
# -----------------------------
def extract_bizbuysell_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

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

    name_tag = soup.find('b', string=re.compile('Contact Name'))
    name = name_tag.find_next('span').get_text(strip=True) if name_tag else ''
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email_tag = soup.find('b', string=re.compile('Contact Email'))
    email = email_tag.find_next('span').get_text(strip=True) if email_tag else None

    phone_tag = soup.find('b', string=re.compile('Contact Phone'))
    phone = phone_tag.find_next('span').get_text(strip=True) if phone_tag else None

    ref_id_match = soup.find(text=re.compile('Ref ID'))
    ref_id = ref_id_match.find_next(text=True).strip() if ref_id_match else ''

    listing_id = ''
    for span in soup.find_all('span'):
        if 'Listing ID:' in span.get_text():
            a = span.find_next('a')
            if a:
                listing_id = a.get_text(strip=True)
                break

    headline = ''
    for b in soup.find_all('b'):
        text = b.get_text(strip=True)
        if text.lower() != "from:" and len(text) > 10:
            headline = text
            break

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": extract_optional("Contact Zip"),
        "investment_amount": extract_optional("Able to Invest"),
        "purchase_timeline": extract_optional("Purchase Within"),
        "comments": extract_optional("Comments")
    }

# -----------------------------
# BizBuySell Text Parser
# -----------------------------
import re

def extract_bizbuysell_text_version(text):
    def get_value(label):
        match = re.search(rf"{label}:\s*(.*)", text)
        return match.group(1).strip() if match else ''

    name = get_value("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # Special handling for 'Purchase Within' to stop before 'Comments'
    purchase_within_match = re.search(r"Purchase Within:\s*(.*?)\s*Comments:", text, re.DOTALL)
    purchase_timeline = purchase_within_match.group(1).strip() if purchase_within_match else ''

    # Comments line should only start after 'Comments:'
    comments_match = re.search(r"Comments:\s*(.*)", text, re.DOTALL)
    comments = comments_match.group(1).strip() if comments_match else ''

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get_value("Contact Email"),
        "phone": get_value("Contact Phone"),
        "ref_id": get_value("Ref ID"),
        "listing_id": get_value("Listing ID"),
        "headline": extract_headline_from_text(text),  # Assuming function exists
        "contact_zip": get_value("Contact Zip"),
        "investment_amount": get_value("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments
    }


# -----------------------------
# BusinessesForSale HTML Parser
# -----------------------------
def extract_bfs_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    # Parse main content
    ref_id = ''
    headline = ''
    url = ''
    for line in soup.stripped_strings:
        if 'Your listing ref:' in line:
            ref_id = line.split('Your listing ref:')[-1].split()[0]
        elif line.startswith('http') and 'businessesforsale' in line:
            url = line.strip()
        elif len(line) > 10 and headline == '' and 'listing ref' in line.lower():
            headline = line.split('listing ref:')[1].strip() if 'listing ref:' in line else line

    # Extract user info
    name_match = re.search(r'Name:\s*(.*)', html_body)
    first_name, last_name = ('', '')
    if name_match:
        full_name = name_match.group(1).strip()
        first_name, last_name = full_name.split(' ', 1) if ' ' in full_name else (full_name, '')

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": re.search(r'Email:\s*(.*)', html_body).group(1).strip() if 'Email:' in html_body else '',
        "phone": re.sub(r"\s+", "", re.search(r'Tel:\s*(.*)', html_body).group(1).strip()) if 'Tel:' in html_body else '',
        "ref_id": ref_id,
        "headline": headline,
        "listing_url": url,
        "comments": re.search(r'has received the following message:\n\n(.*?)\n\n', html_body, re.DOTALL).group(1).strip() if 'has received the following message:' in html_body else ''
    }

# -----------------------------
# BusinessesForSale Text Parser
# -----------------------------
def extract_bfs_text(text):
    return extract_bfs_html(text)  # works identically for both

# -----------------------------
# Routing
# -----------------------------
@app.route('/api/parse', methods=['POST'])
def parse_html():
    try:
        raw_body = request.get_data(as_text=True)
        if not raw_body:
            return jsonify({"error": "No email content provided."}), 400

        lower = raw_body.lower()

        # BizBuySell
        if "bizbuysell" in lower:
            if "<html" in lower:
                parsed_data = extract_bizbuysell_html(raw_body)
            else:
                parsed_data = extract_bizbuysell_text(raw_body)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed_data})

        # BusinessesForSale
        if "businessesforsale" in lower:
            if "<html" in lower:
                parsed_data = extract_bfs_html(raw_body)
            else:
                parsed_data = extract_bfs_text(raw_body)
            return jsonify({"source": "businessesforsale", "parsed_data": parsed_data})

        return jsonify({"source": "unknown", "parsed_data": {}})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run()
