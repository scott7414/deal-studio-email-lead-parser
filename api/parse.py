from bs4 import BeautifulSoup
import re

def normalize_phone(phone):
    """Strip non-numeric characters from phone numbers."""
    if not phone:
        return ''
    return re.sub(r'\D', '', phone)

# ✅ BizBuySell (HTML)
def extract_bizbuysell_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(separator='\n')

    def find_text_after(label):
        match = re.search(rf"{label}:\s*([^\n\r]+)", text)
        return match.group(1).strip() if match else ''

    name = find_text_after("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    comments_match = re.search(r"Comments:\s*(.*?)\n(?:You can reply directly|Thank you,|$)", text, re.DOTALL)
    comments = comments_match.group(1).strip() if comments_match else ''

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": find_text_after("Contact Email"),
        "phone": normalize_phone(find_text_after("Contact Phone")),
        "ref_id": find_text_after("Ref ID"),
        "listing_id": find_text_after("Listing ID"),
        "headline": find_text_after("You’ve received a new lead regarding your listing"),
        "contact_zip": find_text_after("Contact Zip"),
        "investment_amount": find_text_after("Able to Invest"),
        "purchase_timeline": find_text_after("Purchase Within"),
        "comments": comments
    }

# ✅ BizBuySell (Plain Text)
def extract_bizbuysell_text(text):
    def get_value(label):
        match = re.search(rf"{label}:\s*(.*)", text)
        return match.group(1).strip() if match else ''

    name = get_value("Contact Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    comments_match = re.search(r"Comments:\s*((?:.|\n)*?)(?:\n(?:You can reply directly|We take our lead quality|Thank you,|$))", text)
    comments = comments_match.group(1).strip() if comments_match else ''

    ref_id_match = re.search(r"Ref ID:\s*(.+)", text)
    ref_id = ref_id_match.group(1).split('\n')[0].strip() if ref_id_match else ''

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get_value("Contact Email"),
        "phone": normalize_phone(get_value("Contact Phone")),
        "ref_id": ref_id,
        "listing_id": get_value("Listing ID"),
        "headline": get_value("You’ve received a new lead regarding your listing"),
        "contact_zip": get_value("Contact Zip"),
        "investment_amount": get_value("Able to Invest"),
        "purchase_timeline": get_value("Purchase Within"),
        "comments": comments
    }

# ✅ BusinessesForSale (Plain Text only for now)
def extract_businessesforsale_text(text):
    def get_field(label):
        match = re.search(rf"{label}:\s*(.+)", text)
        return match.group(1).strip() if match else ''

    listing_info = re.search(r"Your listing ref:(\d+)\s+(.+)\n(https?://[^\s]+)", text)
    ref_id, headline, listing_url = listing_info.groups() if listing_info else ('', '', '')

    name = get_field("Name")
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    comment_match = re.search(r"has received the following message:\s*\n\n(.+?)\n\nName:", text, re.DOTALL)
    comments = comment_match.group(1).strip() if comment_match else ''

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": get_field("Email"),
        "phone": normalize_phone(get_field("Tel")),
        "ref_id": ref_id,
        "headline": headline,
        "listing_url": listing_url,
        "comments": comments
    }
