# tests/test_fcbb_parser.py
import importlib

# 👇 Change this to your file name (without .py) if not "app"
module_name = "app"
mod = importlib.import_module(module_name)
app = getattr(mod, "app")

def _post_parse(client, body: str):
    return client.post("/api/parse", json={"body": body})

def test_fcbb_html_parses_labels_and_leaves_listing_url_empty():
    expected_url = (
        "https://www.sellbusinessinlasvegas.com/education/agoura-hills/"
        "50-year-old-niche-school-with-loyal-student-pipeline-now-available-101-24593"
    )
    html = f"""\
<!doctype html><html><body>
<table>
<tr><td><strong>First Name:</strong></td><td>Johnny</td></tr>
<tr><td><strong>Last Name:</strong></td><td>Vu</td></tr>
<tr><td><strong>Email Address:</strong></td><td><a href="mailto:johnny@example.com">johnny@example.com</a></td></tr>
<tr><td><strong>Phone Number:</strong></td><td><a href="tel:702-555-1212">(702) 555-1212</a></td></tr>
<tr><td><strong>Address:</strong></td><td>123 Main St</td></tr>
<tr><td><strong>City:</strong></td><td>Agoura Hills,</td></tr>
<tr><td><strong>Postal Code:</strong></td><td>91301</td></tr>
<tr><td><strong>Listing Number:</strong></td><td>101-24593</td></tr>
<tr><td><strong>Originating Website:</strong></td>
    <td><a href="https://track.ct.sendgrid.net/ls/click?x=y">{expected_url}</a></td></tr>
<tr><td><strong>Current Site Page URL:</strong></td><td>{expected_url}</td></tr>
<tr><td><strong>Domain:</strong></td><td>sellbusinessinlasvegas.com</td></tr>
</table>
</body></html>
"""

    with app.test_client() as c:
        res = _post_parse(c, html)
        assert res.status_code == 200
        data = res.get_json()
        assert data["source"] == "fcbb"

        # Contact
        assert data["contact"]["first_name"] == "Johnny"
        assert data["contact"]["last_name"] == "Vu"
        assert data["contact"]["email"] == "johnny@example.com"
        assert data["contact"]["phone"] == "+17025551212"

        # Listing block
        listing = data["listing"]
        assert listing["listing_id"] == "101-24593"
        assert listing["originating_website"] == expected_url
        assert listing["current_site_page_url"] == expected_url
        assert listing["domain"] == "sellbusinessinlasvegas.com"
        # FCBB must NOT populate generic listing_url
        assert listing["listing_url"] == ""

def test_fcbb_text_ignores_sendgrid_tracking_and_leaves_listing_url_empty():
    expected_url = (
        "https://www.sellbusinessinlasvegas.com/education/agoura-hills/"
        "50-year-old-niche-school-with-loyal-student-pipeline-now-available-101-24593"
    )
    text = f"""\
Domain: sellbusinessinlasvegas.com
Listing Number: 101-24593
First Name: Johnny
Last Name: Vu
Email Address: johnny@example.com
Phone Number: (702) 555-1212
Address: 123 Main St
City: Agoura Hills,
Postal Code: 91301
Originating Website: {expected_url} [https://u5728489.ct.sendgrid.net/ls/click?foo=bar]
Current Site Page URL: {expected_url}
"""

    with app.test_client() as c:
        res = _post_parse(c, text)
        assert res.status_code == 200
        data = res.get_json()
        assert data["source"] == "fcbb"

        # Contact
        assert data["contact"]["first_name"] == "Johnny"
        assert data["contact"]["last_name"] == "Vu"
        assert data["contact"]["email"] == "johnny@example.com"
        assert data["contact"]["phone"] == "+17025551212"

        # Listing block
        listing = data["listing"]
        assert listing["listing_id"] == "101-24593"
        assert listing["originating_website"] == expected_url
        assert listing["current_site_page_url"] == expected_url
        assert listing["domain"] == "sellbusinessinlasvegas.com"
        # FCBB must NOT populate generic listing_url
        assert listing["listing_url"] == ""
# tests/test_fcbb_parser.py
import importlib

# 👇 Change this to your file name (without .py) if not "app"
module_name = "app"
mod = importlib.import_module(module_name)
app = getattr(mod, "app")

def _post_parse(client, body: str):
    return client.post("/api/parse", json={"body": body})

def test_fcbb_html_parses_labels_and_leaves_listing_url_empty():
    expected_url = (
        "https://www.sellbusinessinlasvegas.com/education/agoura-hills/"
        "50-year-old-niche-school-with-loyal-student-pipeline-now-available-101-24593"
    )
    html = f"""\
<!doctype html><html><body>
<table>
<tr><td><strong>First Name:</strong></td><td>Johnny</td></tr>
<tr><td><strong>Last Name:</strong></td><td>Vu</td></tr>
<tr><td><strong>Email Address:</strong></td><td><a href="mailto:johnny@example.com">johnny@example.com</a></td></tr>
<tr><td><strong>Phone Number:</strong></td><td><a href="tel:702-555-1212">(702) 555-1212</a></td></tr>
<tr><td><strong>Address:</strong></td><td>123 Main St</td></tr>
<tr><td><strong>City:</strong></td><td>Agoura Hills,</td></tr>
<tr><td><strong>Postal Code:</strong></td><td>91301</td></tr>
<tr><td><strong>Listing Number:</strong></td><td>101-24593</td></tr>
<tr><td><strong>Originating Website:</strong></td>
    <td><a href="https://track.ct.sendgrid.net/ls/click?x=y">{expected_url}</a></td></tr>
<tr><td><strong>Current Site Page URL:</strong></td><td>{expected_url}</td></tr>
<tr><td><strong>Domain:</strong></td><td>sellbusinessinlasvegas.com</td></tr>
</table>
</body></html>
"""

    with app.test_client() as c:
        res = _post_parse(c, html)
        assert res.status_code == 200
        data = res.get_json()
        assert data["source"] == "fcbb"

        # Contact
        assert data["contact"]["first_name"] == "Johnny"
        assert data["contact"]["last_name"] == "Vu"
        assert data["contact"]["email"] == "johnny@example.com"
        assert data["contact"]["phone"] == "+17025551212"

        # Listing block
        listing = data["listing"]
        assert listing["listing_id"] == "101-24593"
        assert listing["originating_website"] == expected_url
        assert listing["current_site_page_url"] == expected_url
        assert listing["domain"] == "sellbusinessinlasvegas.com"
        # FCBB must NOT populate generic listing_url
        assert listing["listing_url"] == ""

def test_fcbb_text_ignores_sendgrid_tracking_and_leaves_listing_url_empty():
    expected_url = (
        "https://www.sellbusinessinlasvegas.com/education/agoura-hills/"
        "50-year-old-niche-school-with-loyal-student-pipeline-now-available-101-24593"
    )
    text = f"""\
Domain: sellbusinessinlasvegas.com
Listing Number: 101-24593
First Name: Johnny
Last Name: Vu
Email Address: johnny@example.com
Phone Number: (702) 555-1212
Address: 123 Main St
City: Agoura Hills,
Postal Code: 91301
Originating Website: {expected_url} [https://u5728489.ct.sendgrid.net/ls/click?foo=bar]
Current Site Page URL: {expected_url}
"""

    with app.test_client() as c:
        res = _post_parse(c, text)
        assert res.status_code == 200
        data = res.get_json()
        assert data["source"] == "fcbb"

        # Contact
        assert data["contact"]["first_name"] == "Johnny"
        assert data["contact"]["last_name"] == "Vu"
        assert data["contact"]["email"] == "johnny@example.com"
        assert data["contact"]["phone"] == "+17025551212"

        # Listing block
        listing = data["listing"]
        assert listing["listing_id"] == "101-24593"
        assert listing["originating_website"] == expected_url
        assert listing["current_site_page_url"] == expected_url
        assert listing["domain"] == "sellbusinessinlasvegas.com"
        # FCBB must NOT populate generic listing_url
        assert listing["listing_url"] == ""
