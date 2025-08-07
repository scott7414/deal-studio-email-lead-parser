from bs4 import BeautifulSoup
import re

def extract_bizbuysell(html):
    soup = BeautifulSoup(html, 'html.parser')

    def extract_text(label):
        tag = soup.find('b', string=re.compile(label))
        if tag:
            return tag.find_next(text=True).strip()
        return None

    source = extract_text('From:')
    headline_tag = soup.find('b')
    headline = headline_tag.get_text(strip=True) if headline_tag else None

    name_tag = soup.find('b', string=re.compile('Contact Name'))
    name = name_tag.find_next('span').get_text(strip=True) if name_tag else ''
    first_name, last_name = name.split(' ', 1) if ' ' in name else (name, '')

    email_tag = soup.find('b', string=re.compile('Contact Email'))
    email = email_tag.find_next('span').get_text(strip=True) if email_tag else None

    phone_tag = soup.find('b', string=re.compile('Contact Phone'))
    phone = phone_tag.find_next('span').get_text(strip=True) if phone_tag else None

    ref_id_match = soup.find(text=re.compile('Ref ID'))
    ref_id = ref_id_match.find_next(text=True).strip() if ref_id_match else None

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "ref_id": ref_id or '',
        "headline": headline,
        "source": source
    }

# This is the expected Vercel handler format
def handler(request):
    try:
        body = request.get("body", "")
        html = body.encode('utf-8').decode('utf-8')

        if 'bizbuysell' in html:
            parsed = extract_bizbuysell(html)
            source = "bizbuysell"
        else:
            parsed = {}
            source
