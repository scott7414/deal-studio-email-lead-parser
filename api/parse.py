from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

def clean_phone(raw):
    if raw:
        return re.sub(r'[^\d]', '', raw)
    return ''

def extract_headline_from_text(text):
    match = re.search(r"received a new lead regarding your listing:\n\n(.+)", text)
    return match.group(1).strip() if match else ''

# --- BIZBUYSSELL TEXT ---
def extract_bizbuysell_text(text):
    def get_val(label):
        match = re.search(rf"{label}:\s*(.*)", text)
        return match.group(1).strip() if match else ''

    name = get_val("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')
    purchase_timeline = get_val("Purchase Within")

    # Cut off comments before system footer
    comments_raw = text.split("Comments:")[-1].strip()
    comments_clean = re.split(r"You can reply directly|Thank you|BizBuySell|Unsubscribe", comments_raw, flags=re.I)[0].strip()

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get_val("Contact Email"),
        "phone": clean_phone(get_val("Contact Phone")),
        "ref_id": get_val("Ref ID"),
        "listing_id": get_val("Listing ID"),
        "headline": extract_headline_from_text(text),
        "contact_zip": get_val("Contact Zip"),
        "investment_amount": get_val("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments_clean
    }

# --- BIZBUYSELL HTML ---
def extract_bizbuysell_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    def find_b(label):
        tag = soup.find('b', string=re.compile(label, re.I))
        return tag.find_next('span').get_text(strip=True) if tag else ''

    # Headline: use first <b> not labeled 'from'
    headline = ''
    for b in soup.find_all('b'):
        txt = b.get_text(strip=True)
        if txt.lower() != 'from:' and len(txt) > 10:
            headline = txt
            break

    name = find_b("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # Ref ID: look for string pattern
    ref_id_match = soup.find(string=re.compile("Ref ID"))
    ref_id = ''
    if ref_id_match:
        next_line = ref_id_match.strip().split(":")
        if len(next_line) > 1:
            ref_id = next_line[1].strip()

    # Listing ID: scan all spans
    listing_id = ''
    for span in soup.find_all('span'):
        if 'Listing ID:' in span.get_text():
            next_a = span.find_next('a')
            if next_a:
                listing_id = next_a.get_text(strip=True)
                break

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": find_b("Contact Email"),
        "phone": clean_phone(find_b("Contact Phone")),
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": find_b("Contact Zip"),
        "investment_amount": find_b("Able to Invest"),
        "purchase_timeline": find_b("Purchase Within"),
        "comments": find_b("Comments")
    }

# --- BUSINESSESFORSALE TEXT ---
def extract_bfs_text(text):
    def find_line(label):
        match = re.search(rf"{label}:\s*(.*)", text)
        return match.group(1).strip() if match else ''

    name = find_line("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # Ref ID and Headline from one line
    match = re.search(r"Your listing ref:(\d+) (.+)", text)
    ref_id, headline = (match.group(1), match.group(2)) if match else ('', '')

    # Listing URL
    url_match = re.search(r"(https://us\.businessesforsale\.com/[\S]+)", text)
    listing_url = url_match.group(1).strip() if url_match else ''

    comments_match = re.search(r"has received the following message:\n\n(.+?)\n\n", text, re.DOTALL)
    comments = comments_match.group(1).strip() if comments_match else ''

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": find_line("Email"),
        "phone": clean_phone(find_line("Tel")),
        "ref_id": ref_id,
        "headline": headline,
        "listing_url": listing_url,
        "comments": comments
    }

@app.route("/api/parse", methods=["POST"])
def parse_lead():
    try:
        body = request.get_data(as_text=True)
        lower = body.lower()

        if not body:
            return jsonify({"error": "No email body found."}), 400

        # Detect HTML or plain
        is_html = bool(re.search(r"<[^>]+>", body))

        if "bizbuysell.com" in lower:
            parsed = extract_bizbuysell_html(body) if is_html else extract_bizbuysell_text(body)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed})

        elif "businessesforsale.com" in lower:
            parsed = extract_bfs_text(body)
            return jsonify({"source": "businessesforsale", "parsed_data": parsed})

        return jsonify({"source": "unknown", "parsed_data": {}})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True)
