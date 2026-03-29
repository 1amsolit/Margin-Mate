"""
Email parser — connects to IMAP, fetches merchant order emails,
extracts order data and writes to the database.
"""
import imaplib
import email
import re
import ssl
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from bs4 import BeautifulSoup
import database

# ── Carrier detection ─────────────────────────────────────────────────────────

CARRIER_KEYWORDS = {
    "australia post": ("Australia Post",  "https://auspost.com.au/mypost/track/#/details/{}"),
    "auspost":        ("Australia Post",  "https://auspost.com.au/mypost/track/#/details/{}"),
    "startrack":      ("StarTrack",       "https://startrack.com.au/track-and-trace/?ref={}"),
    "couriers please":("Couriers Please", "https://couriersplease.com.au/Track/Summary?consignmentNumber={}"),
    "dhl":            ("DHL",             "https://www.dhl.com/au-en/home/tracking.html?tracking-id={}"),
    "fedex":          ("FedEx",           "https://www.fedex.com/apps/fedextrack/?tracknumbers={}"),
    "ups":            ("UPS",             "https://www.ups.com/track?tracknum={}"),
    "amazon logistics":("Amazon Logistics","https://track.amazon.com.au/tracking/{}"),
    "sendle":         ("Sendle",          "https://track.sendle.com/tracking?ref={}"),
    "fastway":        ("Aramex/Fastway",  "https://www.aramex.com.au/tools/track?l={}"),
    "aramex":         ("Aramex/Fastway",  "https://www.aramex.com.au/tools/track?l={}"),
    "tnt":            ("TNT",             "https://www.tnt.com/express/en_au/site/shipping-tools/tracking.html?searchType=CON&cons={}"),
    "toll":           ("Toll",            "https://www.tollgroup.com/tools/tracking?ref={}"),
    "hunter express": ("Hunter Express",  "https://www.hunterexpress.com.au/track?ref={}"),
    "gopeople":       ("GoPeople",        "https://www.gopeople.com.au/tracking/?code={}"),
    "go people":      ("GoPeople",        "https://www.gopeople.com.au/tracking/?code={}"),
}

# (pattern, carrier, url_template) — order matters, more specific first
CARRIER_TRACK_PATTERNS = [
    (r"\bTBA\d{12,17}\b",          "Amazon Logistics", "https://track.amazon.com.au/tracking/{}"),
    (r"\bJD\d{18}\b",              "Australia Post",   "https://auspost.com.au/mypost/track/#/details/{}"),
    (r"\b[A-Z]{2}\d{9}AU\b",      "Australia Post",   "https://auspost.com.au/mypost/track/#/details/{}"),
    (r"\bGPM[A-Z0-9]{5,}\b",      "GoPeople",         "https://www.gopeople.com.au/tracking/?code={}"),
    (r"\bST[0-9A-Z]{6,}\b",       "StarTrack",        "https://startrack.com.au/track-and-trace/?ref={}"),
    (r"\b1Z[0-9A-Z]{16}\b",       "UPS",              "https://www.ups.com/track?tracknum={}"),
    (r"\bCP\d{8,12}\b",           "Couriers Please",  "https://couriersplease.com.au/Track/Summary?consignmentNumber={}"),
    (r"\b\d{16,22}\b",             "Australia Post",   "https://auspost.com.au/mypost/track/#/details/{}"),
]

# Tracking URL host → (regex to extract id from href, carrier, canonical url_template)
_TRACKING_URL_PATTERNS = [
    (r"gopeople\.com\.au",         r"code=([A-Z0-9]+)",                  "GoPeople",          "https://www.gopeople.com.au/tracking/?code={}"),
    (r"auspost\.com\.au",          r"[/#]([A-Z0-9]{10,25})(?:[/?&]|$)", "Australia Post",    "https://auspost.com.au/mypost/track/#/details/{}"),
    (r"startrack\.com\.au",        r"ref=([A-Z0-9]{6,})",               "StarTrack",         "https://startrack.com.au/track-and-trace/?ref={}"),
    (r"couriersplease\.com\.au",   r"consignmentNumber=([A-Z0-9]{6,})", "Couriers Please",   "https://couriersplease.com.au/Track/Summary?consignmentNumber={}"),
    (r"track\.amazon\.com",        r"/tracking/([A-Z0-9]{10,20})",      "Amazon Logistics",  "https://track.amazon.com.au/tracking/{}"),
    (r"fedex\.com",                r"tracknumbers=([A-Z0-9]{10,})",     "FedEx",             "https://www.fedex.com/apps/fedextrack/?tracknumbers={}"),
    (r"dhl\.com",                  r"tracking-id=([A-Z0-9]{8,})",       "DHL",               "https://www.dhl.com/au-en/home/tracking.html?tracking-id={}"),
    (r"ups\.com",                  r"tracknum=([A-Z0-9]{10,})",         "UPS",               "https://www.ups.com/track?tracknum={}"),
    (r"sendle\.com",               r"ref=([A-Z0-9]{6,})",               "Sendle",            "https://track.sendle.com/tracking?ref={}"),
    (r"aramex\.com\.au",           r"l=([A-Z0-9]{6,})",                 "Aramex/Fastway",    "https://www.aramex.com.au/tools/track?l={}"),
    (r"hunterexpress\.com\.au",    r"ref=([A-Z0-9]{6,})",               "Hunter Express",    "https://www.hunterexpress.com.au/track?ref={}"),
    (r"tnt\.com",                  r"cons=([A-Z0-9]{6,})",              "TNT",               "https://www.tnt.com/express/en_au/site/shipping-tools/tracking.html?searchType=CON&cons={}"),
]

# Generic label → tracking number pattern (used on plain text body)
_TRACKING_LABEL_RE = re.compile(
    r"(?:tracking\s*(?:id|number|no|code|#)|consignment\s*(?:number|no))[:\s#]*([A-Z0-9]{6,})",
    re.IGNORECASE,
)


def detect_carrier_from_text(text):
    """Return (carrier_name, url_template) from keyword scan, or (None, None)."""
    tl = text.lower()
    for kw, (name, url) in CARRIER_KEYWORDS.items():
        if kw in tl:
            return name, url
    return None, None


def find_tracking_in_text(text):
    """Return (tracking_number, carrier, url_template) or (None, None, None)."""
    # First try labelled patterns (e.g. "Tracking ID: GPM00810789")
    m = _TRACKING_LABEL_RE.search(text)
    if m:
        candidate = m.group(1)
        # Match candidate against each known carrier pattern
        for pattern, carrier, url_tpl in CARRIER_TRACK_PATTERNS:
            if re.search(pattern, candidate):
                return candidate, carrier, url_tpl.format(candidate)
        # Unknown carrier — still return the number, carrier resolved later
        return candidate, None, None

    # Fall back to bare pattern scan
    for pattern, carrier, url_tpl in CARRIER_TRACK_PATTERNS:
        hit = re.search(pattern, text)
        if hit:
            return hit.group(0), carrier, url_tpl.format(hit.group(0))
    return None, None, None


def find_tracking_in_html(html):
    """Extract tracking number + carrier from anchor href URLs in HTML email.
    Handles redirect/click-tracking URLs by URL-decoding the href."""
    if not html:
        return None, None, None
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        raw_href = str(a["href"])
        # Check both the raw href and URL-decoded version (catches redirect links)
        for href in dict.fromkeys([raw_href, unquote(raw_href)]):
            for host_pat, id_pat, carrier, url_tpl in _TRACKING_URL_PATTERNS:
                if re.search(host_pat, href, re.IGNORECASE):
                    hit = re.search(id_pat, href, re.IGNORECASE)
                    if hit:
                        tracking = hit.group(1)
                        return tracking, carrier, url_tpl.format(tracking)
        # Also check if the visible link text itself is a tracking number
        link_text = a.get_text(strip=True)
        if link_text:
            tn, carrier, url = find_tracking_in_text(link_text)
            if tn:
                return tn, carrier, url
    return None, None, None


# ── Email utilities ───────────────────────────────────────────────────────────

def decode_str(s):
    if not s:
        return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def get_email_body(msg):
    """Return (plain_text, html_text) from a Message object."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/plain" and not plain:
                plain = decoded
            elif ct == "text/html" and not html:
                html = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html = decoded
            else:
                plain = decoded
    return plain, html


def html_to_text(html):
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n")


def parse_email_date(date_str):
    """Parse the email Date header and return YYYY-MM-DD, falling back to today."""
    if date_str:
        try:
            return parsedate_to_datetime(date_str).date().isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).date().isoformat()


# Generic order-number patterns tried in order (most specific first)
_ORDER_NUM_PATTERNS = [
    re.compile(r"\b(\d{3}-\d{7}-\d{7})\b"),                                          # Amazon
    re.compile(r"(?:order|#)\s*(?:number|no\.?|id|ref(?:erence)?)?[:\s#]*(\d{7,})", re.IGNORECASE),  # long numeric
    re.compile(r"(?:order\s*(?:number|no\.?|id|reference|#)[:\s#]+)([A-Z0-9][A-Z0-9\-]{3,})", re.IGNORECASE),
    re.compile(r"#([A-Z0-9]{4,})\b"),
]

def generic_order_number(subject, text):
    """Try each pattern against subject then body; return first match."""
    for pat in _ORDER_NUM_PATTERNS:
        for src in (subject, text):
            m = pat.search(src)
            if m:
                return m.group(1)
    return None


# Patterns that mark the END of a product name (everything after gets stripped)
_SUFFIX_CUTOFF = re.compile(
    r"\s*[\*\|]\s*(?:item\s*code|sku|unit\s*price|price|qty|quantity|ref)[:\s].*$"
    r"|(?:\s+item\s*code\s*[:\-#])"
    r"|\s+sku\s*[:\-#]"
    r"|\s+unit\s*price\s*[:\-]"
    r"|\s*\$[\d,]+\.\d{2}.*$"
    r"|\s{2,}.*(?:code|sku|price|qty).*$",
    re.IGNORECASE,
)


def _clean_description(raw: str) -> str:
    """Strip item-code / price / qty suffixes that get bundled into the product name."""
    if not raw:
        return raw
    # Step 1: take only the first meaningful line
    first = raw
    for line in raw.splitlines():
        line = line.strip()
        if len(line) >= 5:
            first = line
            break
    # Step 2: truncate at suffix noise on that single line
    cleaned = _SUFFIX_CUTOFF.sub("", first).rstrip("* ").strip()
    return (cleaned or first)[:200]


# Words/phrases that indicate a cell is a label row, not a product name
_NOISE_RE = re.compile(
    r"^(order(\s*(number|#|no|id|ref))?|ship(ping)?|deliver(y|ing)?|dispatch|"
    r"subtotal|sub.total|grand\s*total|order\s*total|total|tax|gst|"
    r"qty|quantity|price|amount|unit\s*price|date|status|payment|"
    r"hello|dear|hi\s|thanks|thank\s*you|congratul|"
    r"you\s+(have|ordered|placed)|we\s+(have|received|will)|"
    r"your\s+(order|account|invoice|receipt)|"
    r"item\s*#?$|description$|product\s*#?$|sku$|"
    r"view\s|track\s|manage\s|visit\s|click\s|shop\s|browse\s|"
    r"sign\s*in|log\s*in|contact|follow\s*us|unsubscrib|privacy|terms|"
    r"©|\$\s*[\d,])",
    re.IGNORECASE,
)


def _is_candidate(t):
    """Return True if text string looks like a product name."""
    t = re.sub(r"\s+", " ", t).strip()
    if not (10 < len(t) < 200):
        return False
    if "http" in t or "@" in t:
        return False
    if re.match(r"^[\$\d]", t):   # starts with price or pure number
        return False
    if re.match(r"^\d+$", t):     # pure number = qty
        return False
    if _NOISE_RE.match(t):
        return False
    return True


def extract_item_description(html, text):
    """Try to pull a product/item name from the email body."""

    if html:
        soup = BeautifulSoup(html, "lxml")
        # Strip noise elements
        for tag in soup(["nav", "footer", "style", "script", "head", "img"]):
            tag.decompose()

        # Strategy 1: well-known CSS class / id names
        CLASS_HINTS = re.compile(
            r"product.?name|item.?name|product.?title|item.?title|"
            r"order.?item|line.?item|product.?desc|item.?desc",
            re.IGNORECASE,
        )
        for tag in soup.find_all(True):
            cls = " ".join(tag.get("class") or [])
            tid = str(tag.get("id") or "")
            if CLASS_HINTS.search(cls) or CLASS_HINTS.search(tid):
                t = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
                if _is_candidate(t):
                    return _clean_description(t)

        # Strategy 2: table rows that contain a price cell → sibling text cell
        # is the product name (works for Target, Kmart, BigW, Amazon, Shopify)
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            cell_texts = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in cells]
            # Row must have at least one price-looking cell
            if not any(re.search(r"\$[\d,]+\.?\d*", ct) for ct in cell_texts):
                continue
            # Find the non-price text cell — that's the product name
            for ct in cell_texts:
                if _is_candidate(ct):
                    return _clean_description(ct)

        # Strategy 3: broad sweep of all leaf-ish tags
        for tag in soup.find_all(["td", "p", "li", "span", "h2", "h3", "h4"]):
            # Skip if has many block children (container, not leaf)
            if tag.find(["table", "ul", "ol", "div"]):
                continue
            ct = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
            if _is_candidate(ct):
                return _clean_description(ct)

    # Plain-text fallbacks
    for pattern in [
        r"(?:You ordered|Your items?|Items?\s+ordered?|Products?\s+ordered?)[:\s]*([^\n\$]{10,120})",
        r"(?:Description|Item)[:\s]+([A-Z][^\n\$]{10,120})",
        r"(?:^\s*|\n\s*)(\d+\s*[xX×]\s*)([A-Z][^\n\$]{10,120})",
        r"\n([A-Z][a-z][\w ,\-']{10,100})\n",  # Title Case line
    ]:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            candidate = m.group(m.lastindex or 1).strip()
            if _is_candidate(candidate):
                return _clean_description(candidate)

    return None


def find_amount(text):
    patterns = [
        r"(?:order total|total amount|grand total|total charged|amount)[:\s]*\$?([\d,]+\.\d{2})",
        r"\$\s*([\d,]+\.\d{2})",
        r"AUD\s*([\d,]+\.?\d*)",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


# ── Merchant parsers ──────────────────────────────────────────────────────────

class MerchantParser:
    name = "Unknown"

    # Subclasses override these
    _confirmed_subj = []
    _shipped_subj   = []
    _cancelled_subj = []
    _confirmed_body = []
    _shipped_body   = []
    _cancelled_body = []

    def detect_status(self, subject, text):
        sl = subject.lower()
        tl = text.lower()
        for kw in self._shipped_subj:
            if kw in sl: return "shipped"
        for kw in self._cancelled_subj:
            if kw in sl: return "cancelled"
        for kw in self._confirmed_subj:
            if kw in sl: return "confirmed"
        for kw in self._shipped_body:
            if kw in tl: return "shipped"
        for kw in self._cancelled_body:
            if kw in tl: return "cancelled"
        for kw in self._confirmed_body:
            if kw in tl: return "confirmed"
        return None

    def extract_order_number(self, subject, text):
        # Default: try generic patterns
        return generic_order_number(subject, text)

    def extract_extras(self, subject, text, html, status):
        data = {}
        amount = find_amount(text)
        if amount:
            data["amount"] = amount
        # Item description
        desc = extract_item_description(html, text)
        if desc:
            data["item_description"] = desc
        if status == "shipped":
            # 1. Try HTML links first (most reliable — carrier URL reveals both number and carrier)
            tracking, carrier, tracking_url = find_tracking_in_html(html)
            # 2. Fall back to text patterns
            if not tracking:
                tracking, carrier, tracking_url = find_tracking_in_text(text)
            # 3. If we have a number but no carrier yet, try keyword scan on body text
            if tracking and not carrier:
                carrier_kw, url_tpl_kw = detect_carrier_from_text(text)
                if carrier_kw:
                    carrier = carrier_kw
                    tracking_url = url_tpl_kw.format(tracking) if url_tpl_kw else tracking_url
            # 4. If we have carrier but still no URL, build it from CARRIER_KEYWORDS
            if tracking and carrier and not tracking_url:
                for _, (name, tpl) in CARRIER_KEYWORDS.items():
                    if name == carrier:
                        tracking_url = tpl.format(tracking)
                        break
            if tracking:
                data["tracking_number"] = tracking
                data["carrier"]         = carrier
                data["tracking_url"]    = tracking_url
        return data


class AmazonParser(MerchantParser):
    name = "Amazon"
    _ORDER_RE  = re.compile(r"\b(\d{3}-\d{7}-\d{7})\b")
    _TRACK_RE  = re.compile(r"TBA\d{12,17}|\b[A-Z]{2}\d{9}AU\b|JD\d{18}")

    _shipped_subj   = ["shipped", "on its way", "dispatched", "out for delivery"]
    _cancelled_subj = ["cancelled", "canceled", "refund"]
    _confirmed_subj = ["order", "purchase", "confirmation"]
    _shipped_body   = ["your package", "your shipment", "has been shipped"]
    _cancelled_body = ["has been cancelled", "order cancellation", "your refund"]
    _confirmed_body = ["order placed", "order confirmed", "thank you for your order"]

    def extract_order_number(self, subject, text):
        m = self._ORDER_RE.search(subject) or self._ORDER_RE.search(text)
        return m.group(1) if m else None

    def extract_extras(self, subject, text, html, status):
        data = super().extract_extras(subject, text, html, status)
        # Amazon-specific tracking overrides generic
        tm = self._TRACK_RE.search(text)
        if tm and status == "shipped":
            tracking = tm.group(0)
            data["tracking_number"] = tracking
            if tracking.startswith("TBA"):
                data["carrier"] = "Amazon Logistics"
                data["tracking_url"] = f"https://track.amazon.com.au/tracking/{tracking}"
            else:
                data["carrier"] = "Australia Post"
                data["tracking_url"] = f"https://auspost.com.au/mypost/track/#/details/{tracking}"
        return data


class ShopifyParser(MerchantParser):
    name = "Shopify"
    # Shopify order numbers: #1234 up to #99999 (some stores use 5+ digits)
    _ORDER_RE = re.compile(r"#(\d{3,7})\b")

    _shipped_subj   = ["shipped", "on its way", "dispatched", "fulfilled", "out for delivery"]
    _cancelled_subj = ["cancelled", "canceled", "refund"]
    _confirmed_subj = ["confirmed", "received", "placed", "thank you", "order confirmation"]
    _shipped_body   = ["your order is on", "has been shipped", "tracking number"]
    _cancelled_body = ["has been cancelled", "cancellation"]
    _confirmed_body = ["order confirmed", "thank you for your purchase"]

    def detect_status(self, subject, text):
        result = super().detect_status(subject, text)
        return result or "confirmed"  # Shopify emails almost always orders

    def extract_order_number(self, subject, text):
        m = self._ORDER_RE.search(subject) or self._ORDER_RE.search(text)
        return ("#" + m.group(1)) if m else generic_order_number(subject, text)


class TargetParser(MerchantParser):
    name = "Target"

    _shipped_subj   = ["shipped", "dispatched", "on its way", "delivered", "on the way", "your order is on its way"]
    _cancelled_subj = ["cancelled", "canceled", "refund", "cancellation"]
    _confirmed_subj = ["confirmed", "placed", "received", "thank you", "order confirmation", "we've got your order", "we have your order"]
    _shipped_body   = ["your order has been dispatched", "has been shipped", "tracking number", "tracking id", "on its way", "your parcel", "your order is on its way", "has been shipped", "gopeople", "australia post", "couriers please", "startrack"]
    _cancelled_body = ["has been cancelled", "cancellation", "your refund"]
    _confirmed_body = ["order confirmed", "thank you for your order", "order placed", "we've received your order", "we have received your order"]

    # No custom extract_order_number — uses generic from base class


class KmartParser(TargetParser):
    name = "Kmart"


class BigWParser(TargetParser):
    name = "BigW"


PARSERS = {
    "amazon": AmazonParser(),
    "target": TargetParser(),
    "kmart":  KmartParser(),
    "shopify": ShopifyParser(),
    "bigw":   BigWParser(),
}


# ── Main checker ──────────────────────────────────────────────────────────────

class EmailChecker:
    def __init__(self, config):
        self.config   = config
        self.imap_cfg = config.get("imap", {})
        self.merchants = config.get("merchants", {})

    def check_and_process(self):
        host     = self.imap_cfg.get("host", "imap.gmail.com")
        port     = int(self.imap_cfg.get("port", 993))
        username = self.imap_cfg.get("username", "")
        password = self.imap_cfg.get("password", "")
        days     = int(self.imap_cfg.get("scan_days_back", 30))

        if not username or not password or "your_email" in username:
            raise ValueError("IMAP credentials not configured — go to Settings")

        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
        mail.login(username, password)
        mail.select("INBOX")

        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        count = 0

        for merchant_name, merchant_cfg in self.merchants.items():
            if not merchant_cfg.get("enabled", True):
                continue
            parser = PARSERS.get(merchant_name.lower())
            if not parser:
                continue
            for pattern in merchant_cfg.get("sender_patterns", []):
                try:
                    _, data = mail.search(None, f'(FROM "{pattern}" SINCE {since})')
                except Exception:
                    continue
                if not data or not data[0]:
                    continue
                for uid_bytes in data[0].split():
                    try:
                        _, msg_data = mail.fetch(uid_bytes, "(RFC822)")
                        if not msg_data or not msg_data[0]:
                            continue
                        raw = msg_data[0][1]
                        msg = email.message_from_bytes(raw)
                        if self._process(msg, uid_bytes.decode(), merchant_name, parser):
                            count += 1
                    except Exception:
                        continue

        mail.close()
        mail.logout()
        return count

    def _process(self, msg, uid, merchant_name, parser):
        subject  = decode_str(msg.get("Subject", ""))
        from_hdr = msg.get("From", "")
        date_hdr = msg.get("Date", "")

        plain, html = get_email_body(msg)
        body_text   = html_to_text(html) if html else plain

        status = parser.detect_status(subject, body_text)
        print(f"[{merchant_name}] uid={uid} subject={subject!r} → status={status}")
        if not status:
            return False

        order_number = parser.extract_order_number(subject, body_text)
        extras       = parser.extract_extras(subject, body_text, html, status)
        print(f"  order={order_number!r} tracking={extras.get('tracking_number')!r} "
              f"carrier={extras.get('carrier')!r} url={extras.get('tracking_url')!r} "
              f"item={extras.get('item_description','')[:60]!r}")

        email_uid = f"{merchant_name}:{uid}"
        record = {
            "merchant":             merchant_name,
            "order_number":         order_number,
            "status":               status,
            "email_subject":        subject,
            "email_from":           from_hdr,
            "email_received_date":  date_hdr,
            "email_uid":            email_uid,
            "order_date":           parse_email_date(date_hdr),
            **extras,
        }

        result = database.upsert_order_by_uid(record)

        # Backfill item_description / order_date on already-recorded orders.
        if extras.get("item_description") or record.get("order_date"):
            database.fill_missing_items(
                email_uid,
                extras.get("item_description"),
                record.get("order_date"),
            )

        # Backfill tracking on already-recorded shipped orders.
        if extras.get("tracking_number"):
            database.fill_missing_tracking(
                email_uid,
                extras.get("tracking_number"),
                extras.get("carrier"),
                extras.get("tracking_url"),
            )

        return result
