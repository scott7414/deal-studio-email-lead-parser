# Email Lead Parser API
# Handles multiple sources: BizBuySell, BusinessesForSale

from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import html
import re

app = Flask(__name__)

# --------------------------
# BizBuySell Parser
# --------------------------
def extract_bizbuysell(html_body):
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    full_text = soup.get_text(separator="\n")

    # Try extracting structured values via text-based fallback
    def search_line(label, multiline=False):
        pattern = rf"{label}:(.*)"
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if multiline:
                # Capture next line too
                next_lines = full_text.split(match.group(0))[-1].strip().splitlines()
                if next_lines:
                    return next_lines[0].strip()
            return value
        return ""

    # Parse plain text version
    name = search_line("Contact Name")
    first_name, last_name = name.split(" ", 1) if " " in name else (name, "")

    email = search_line("Contact Email")
    phone = search_line("Contact Phone")
    ref_id = search_line("Ref ID")
    listing_id = search_line("Listing ID")
    headline = ""
headline_match = re.search(r"regarding your listing:\s*\n(.*?)(?:\n|Listing ID:)", full_text, re.IGNORECASE)
if headline_match:
    headline = headline_match.group(1).strip()


    contact_zip = search_line("Contact Zip")
    investment_amount = search_line("Able to Invest")
    purchase_timeline = search_line("Purchase Within")
    comments_match = re.search(r"Comments:(.*?)\n(?:You can reply|$)", full_text, re.DOTALL | re.IGNORECASE)
    comments = comments_match.group(1).strip() if comments_match else ""

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email or None,
        "phone": phone or None,
        "ref_id": ref_id,
        "listing_id": listing_id,
        "headline": headline,
        "contact_zip": contact_zip,
        "investment_amount": investment_amount,
        "purchase_timeline": purchase_timeline,
        "comments": comments
    }

# --------------------------
# BusinessesForSale Parser
# --------------------------
def extract_businessesforsale(html_body):
    # Convert HTML to plain text, preserving line breaks
    soup = BeautifulSoup(html.unescape(html_body), "html.parser")
    full_text = soup.get_text(separator="\n")

    # Extract fields
    email = ""
    phone = ""
    first_name = ""
    last_name = ""
    headline = ""
    ref_id = ""
    listing_url = ""
    comments = ""

    email_match = re.search(r'Email:\s*([^\s]+@[^\s]+)', full_text)
    if email_match:
        email = email_match.group(1).strip()

    phone_match = re.search(r'Tel:\s*([+()0-9\s-]+)', full_text)
    if phone_match:
        phone = re.sub(r"\s+", "", phone_match.group(1).strip())

    name_match = re.search(r'Name:\s*(.*)', full_text)
    if name_match:
        name = name_match.group(1).strip()
        first_name, last_name = name.split(" ", 1) if " " in name else (name, "")

    ref_match = re.search(r'listing ref:([0-9]+)', full_text, re.IGNORECASE)
    if ref_match:
        ref_id = ref_match.group(1).strip()

    headline_match = re.search(r'Your listing ref:[0-9]+\s*(.*?)\s*https?://', full_text, re.IGNORECASE)
    if headline_match:
        headline = headline_match.group(1).strip()

    url_match = re.search(r'(https?://[^"]+)', full_text)
    if url_match:
        listing_url = url_match.group(1).strip()

    comments_match = re.search(r'has received the following message:\s*(.*?)\s*Name:', full_text, re.DOTALL | re.IGNORECASE)
    if comments_match:
        comments = comments_match.group(1).strip()

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

# --------------------------
# Route
# --------------------------
@app.route('/api/parse', methods=['POST'])
def parse_html():
    try:
        html_body = request.get_data(as_text=True)
        if not html_body:
            return jsonify({"error": "No HTML content provided."}), 400

        if "bizbuysell" in html_body.lower():
            parsed_data = extract_bizbuysell(html_body)
            return jsonify({"source": "bizbuysell", "parsed_data": parsed_data})

        if "businessesforsale" in html_body.lower():
            parsed_data = extract_businessesforsale(html_body)
            return jsonify({"source": "businessesforsale", "parsed_data": parsed_data})

        return jsonify({"source": "unknown", "parsed_data": {}})

    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500

if __name__ == "__main__":
    app.run()
