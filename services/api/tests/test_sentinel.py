"""Sentinel trap tests. Fake secrets are assembled at runtime so the repository
never contains a string that secret scanners would flag."""

import pytest

from app.db.models import Sensitivity
from app.sentinel import content_hash, scan

GH = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
AWS = "AKIA" + "IOSFODNN7EXAMPL0"
GOOGLE = "AI" + "za" + "SyD-4f8Kq9vX2mZ1pL7nB3cR6tY0wE5uIoH"
RAZORPAY = "rzp_" + "test_" + "9xQ2mK7pL4vB1nZ8"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


@pytest.mark.parametrize(
    ("text", "secret", "label"),
    [
        (f"export GITHUB_TOKEN={GH}", GH, "github-token"),
        (f"aws key {AWS} in the env file", AWS, "aws-key"),
        (f"maps: {GOOGLE}", GOOGLE, "google-api-key"),
        (f"Razorpay key {RAZORPAY} for the payment test", RAZORPAY, "razorpay-key"),
        (f"Authorization: Bearer {JWT}", JWT, "jwt"),
        ("DB_PASSWORD=Nimbus@2026!", "Nimbus@2026!", "secret"),
        ("postgres://admin:s3cretPa55@db.nimbus.dev:5432/app", "s3cretPa55", "password"),
        ("bhai wifi password hai FestWifi#24 dont share", "FestWifi#24", "password"),
    ],
)
def test_secrets_are_masked(text: str, secret: str, label: str) -> None:
    result = scan(text)
    assert secret not in result.text
    assert f"[REDACTED:{label}]" in result.text
    assert result.secret_count >= 1


def test_assignment_keeps_the_key_name() -> None:
    assert scan("DB_PASSWORD=Nimbus@2026!").text == "DB_PASSWORD=[REDACTED:secret]"


@pytest.mark.parametrize(
    "text",
    [
        "We need a password reset flow before launch",
        "token: pending",
        "The API key rotation is Rahul's job",
        "Merged commit 3f9a1c2 into main",
        # code that refers to a secret without containing one
        'token = auth_s.dumps({"id": 5, "name": "itsdangerous"})',
        'api_key = os.environ["API_KEY"]',
        "secret = settings.SECRET_KEY",
        "password: getpass.getpass()",
    ],
)
def test_prose_is_left_alone(text: str) -> None:
    assert scan(text).text == text


@pytest.mark.parametrize(
    ("text", "value", "label"),
    [
        ("mail me at rahul.verma@nimbusfest.in", "rahul.verma@nimbusfest.in", "email"),
        ("call +91 98765 43210 for the stage vendor", "98765 43210", "phone"),
        ("call 9876543210", "9876543210", "phone"),
        ("pay to nimbusfest@okaxis", "nimbusfest@okaxis", "upi-id"),
        ("PAN ABCPE1234F for the invoice", "ABCPE1234F", "pan"),
        ("aadhaar 2345 6789 0123", "2345 6789 0123", "aadhaar"),
        ("IFSC HDFC0001234 branch", "HDFC0001234", "ifsc"),
        ("account no: 50100234567891", "50100234567891", "bank-account"),
    ],
)
def test_pii_is_masked(text: str, value: str, label: str) -> None:
    result = scan(text)
    assert value not in result.text
    assert f"[REDACTED:{label}]" in result.text


def test_placeholders_point_into_redacted_text() -> None:
    result = scan(f"a {GH} b rahul@nimbusfest.in c")
    for finding, start, end in result.placeholders:
        assert result.text[start:end] == f"[REDACTED:{finding.label}]"


def test_overlapping_matches_never_leak() -> None:
    # The URL rule and the email rule overlap here; the whole span must go.
    result = scan("smtp://mailer:Pa55word!@smtp.nimbusfest.in")
    assert "Pa55word!" not in result.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Rahul's stipend is being revised next month", Sensitivity.confidential),
        ("CONFIDENTIAL: appraisal notes for the core team", Sensitivity.confidential),
        ("Sponsor agreement with Zentrix is internal only", Sensitivity.restricted),
        ("Fest budget sheet updated", Sensitivity.restricted),
        ("Moved the login page to the new layout", Sensitivity.team),
        # a text that marks itself, or talks about pay, HR or health
        ("Confidential. Only the club lead and faculty in charge.", Sensitivity.confidential),
        ("## CONFIDENTIAL\nMentor fees", Sensitivity.confidential),
        ("This note is confidential, don't forward it", Sensitivity.confidential),
        ("Strictly confidential: shortlist", Sensitivity.confidential),
        ("[confidential] mentor fee for Dec", Sensitivity.confidential),
        ("Kunal was diagnosed with dengue last week", Sensitivity.confidential),
        ("He's on a PIP until March", Sensitivity.confidential),
        ("Dev has a health issue and is on sick leave", Sensitivity.confidential),
        # ordinary product and code text must stay Team
        ("Legal and confidential document storage on IPFS", Sensitivity.team),
        ("pip install -r requirements.txt", Sensitivity.team),
        ("Fix loop termination and increment the retry counter", Sensitivity.team),
        ("Add passport-jwt strategy for login", Sensitivity.team),
        ("Run diagnostics on startup", Sensitivity.team),
        ("Show the pricing page and invoice PDF", Sensitivity.team),
        ("Restricted mode for guests", Sensitivity.restricted),
        ("Users get restricted access to shared files", Sensitivity.team),
        # seen on a real Jira project: SQL practice data and code-review notes
        ("Write a SQL query to find all employees with a salary greater than 70000", Sensitivity.team),
        ('Comment says "HR only" but there is no auth check on PATCH /schedule', Sensitivity.team),
        ("Rahul's salary is being revised in December", Sensitivity.confidential),
        ("My salary credited late this month", Sensitivity.confidential),
        ("HR only: exit interview notes", Sensitivity.confidential),
        ("Volunteer stipends for the fest days", Sensitivity.confidential),
    ],
)
def test_sensitivity_labels(text: str, expected: Sensitivity) -> None:
    assert scan(text).sensitivity == expected


def test_source_floor_is_respected() -> None:
    assert scan("hello", floor=Sensitivity.restricted).sensitivity == Sensitivity.restricted


def test_content_hash_ignores_whitespace() -> None:
    assert content_hash("a  b\n c") == content_hash("a b c")
