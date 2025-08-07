from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

# ---------- BizBuySell HTML ----------
def extract_bizbuysell_html(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")

    def safe_find_text(label):
        try:
            tag = soup.find('b', string=re.compile(label))
            if tag:
                span = tag.find_next('span')
                return span.get_text(strip=True) if span else ''
        except:
            return ''
        return ''

    name = safe_find_text("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')
    email = safe_find_text("Contact Email")
    phone = safe_find_text("Contact Phone")
    contact_zip = safe_find_text("Contact Zip")
    investment_amount = safe_find_text("Able to Invest")
    purchase_timeline = safe_find_text("Purchase Within")
    comments = safe_find_text("Comments")
    ref_id = safe_find_text("Ref ID")

    # Listing ID
    listing_id = ''
    for span in soup.find_all('span'):
        if 'Listing ID:' in span.get_text():
            a = span.find_next('a')
            if a:
                listing_id = a.get_text(strip=True)
                break

    # Headline (first <b> tag not labeled "From:")
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
        "contact_zip": contact_zip,
        "investment_amount": investment_amount,
        "purchase_timeline": purchase_timeline,
        "comments": comments
    }

# ---------- BizBuySell TEXT ----------
def extract_bizbuysell_text(text):
    def get_value(label):
        match = re.search(rf"{label}:\s*(.*)", text)
        return match.group(1).strip() if match else ''

    name = get_value("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    # Handle special cases
    purchase_match = re.search(r"Purchase Within:\s*(.*?)\s*Comments:", text, re.DOTALL)
    purchase_timeline = purchase_match.group(1).strip() if purchase_match else ''

    comments_match = re.search(r"Comments:\s*(.*)", text, re.DOTALL)
    comments = comments_match.group(1).strip() if comments_match else ''

    # Headline fallback from intro section
    headline_match = re.search(r"regarding your listing:\s*(.*?)\s*Listing ID", text, re.DOTALL)
    headline = headline_match.group(1).strip() if headline_match else ''

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get_value("Contact Email"),
        "phone": get_value("Contact Phone"),
        "ref_id": get_value("Ref ID"),
        "listing_id": get_value("Listing ID"),
        "headline": headline,
        "contact_zip": get_value("Contact Zip"),
        "investment_amount": get_value("Able to Invest"),
        "purchase_timeline": purchase_timeline,
        "comments": comments
    }

# ---------- BusinessesForSale TEXT ----------
def extract_businessesforsale_text(text):
    name_match = re.search(r"Name:\s*(.*)", text)
    name = name_match.group(1).strip() if name_match else ''
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email_match = re.search(r"Email:\s*(.*)", text)
    email = email_match.group(1).strip() if email_match else ''

    phone_match = re.search(r"Tel:\s*(.*)", text)
    phone = phone_match.group(1).replace(' ', '') if phone_match else ''

    ref_id_match = re.search(r"listing ref:(\d+)", text)
    ref_id = ref_id_match.group(1).strip() if ref_id_match else ''

    headline_match = re.search(r"listing ref:\d+\s*(.*?)\s*https?://", text, re.DOTALL)
    headline = headline_match.group(1).strip() if headline_match else ''

    url_match = re.search(r"(https?://\S+)", text)
    listing_url = url_match.group(1).strip() if url_match else ''

    comments_match = re.search(r"received the following message:\s*(.*?)\s*Name:", text, re.DOTALL)
    comments = comments_match.group(1).strip() if comments_match else ''

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

# ---------- Main Entry Point ----------
@app.route('/api/parse', methods=['POST'])
def parse_html():
    try:
        raw_body = request.get_data(as_text=True)
        if not raw_body:
            return jsonify({"error": "No input received"}), 400

        lower_body = raw_body.lower()

        if "bizbuysell" in lower_body:
            if "<html" in lower_body or "<b>" in lower_body or "<span" in lower_body:
                parsed = extract_bizbuysell_html(raw_body)
            else:
                parsed = extract_bizbuysell_text(raw_body)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed})

        elif "businessesforsale" in lower_body:
            parsed = extract_businessesforsale_text(raw_body)
            return jsonify({"source": "businessesforsale", "parsed_data": parsed})

        return jsonify({"source": "unknown", "parsed_data": {}})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run()
