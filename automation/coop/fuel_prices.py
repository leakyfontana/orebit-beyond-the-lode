"""Current AAA regular US national average, cached until Eastern midnight."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import math
import re
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientTimeout

AAA_URL = "https://gasprices.aaa.com/"
MAX_RESPONSE = 2 * 1024 * 1024
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc


class PriceUnavailable(Exception):
    """No current usable AAA price exists."""


class AAAHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.rows = []
        self.row = None
        self.cell = None
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "tr":
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.cell is not None:
                self.cell.append(data)


def parse_aaa(document, now):
    page = AAAHTML()
    page.feed(document)
    match = re.search(r"Price\s+as\s+of\s+(\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))\b", " ".join(page.text), re.I)
    if not match:
        raise ValueError("AAA date missing")
    raw_date = match.group(1)
    date = datetime.strptime(raw_date, "%m/%d/%Y" if len(raw_date.rsplit("/", 1)[1]) == 4 else "%m/%d/%y").date()
    if date != now.astimezone(EASTERN).date():
        raise ValueError("AAA date is not current")
    regular = None
    for row in page.rows:
        if "Regular" in row and "Mid-Grade" in row:
            regular = row.index("Regular")
        elif regular is not None and row and row[0] == "Current Avg." and len(row) > regular:
            cell = row[regular]
            if re.fullmatch(r"\$\d+(?:\.\d+)?", cell):
                price = float(cell[1:])
                if math.isfinite(price) and price > 0:
                    return {"price_per_gallon": price, "date": date.isoformat(), "source": "aaa"}
    raise ValueError("AAA regular average missing")


class FuelPrices:
    def __init__(self, http, *, user_agent="OrebitBeyondTheLode/1.0", clock=None):
        self.http = http
        self.user_agent = user_agent
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock = asyncio.Lock()
        self.quote = None
        self.expires = None
        self.retry_at = None

    async def _fetch(self):
        async with self.http.request(
            "GET", AAA_URL, headers={"User-Agent": self.user_agent},
            timeout=ClientTimeout(total=20), raise_for_status=False,
        ) as response:
            if response.status != 200:
                raise PriceUnavailable()
            try:
                raw = await response.content.readexactly(MAX_RESPONSE + 1)
            except asyncio.IncompleteReadError as completed:
                raw = completed.partial
            else:
                raise PriceUnavailable()
            return raw.decode("utf-8")

    async def price(self):
        async with self.lock:
            now = self.clock()
            if self.quote is not None and now < self.expires:
                return dict(self.quote)
            if self.retry_at is not None and now < self.retry_at:
                raise PriceUnavailable()
            try:
                document = await self._fetch()
                # A request may cross midnight: date validation and expiry must
                # both use the time at which the response actually arrived.
                now = self.clock()
                quote = parse_aaa(document, now)
            except (PriceUnavailable, ClientError, asyncio.TimeoutError, ValueError, UnicodeError):
                self.quote = None
                self.expires = None
                self.retry_at = self.clock() + timedelta(seconds=60)
                raise PriceUnavailable() from None
            day = now.astimezone(EASTERN).date()
            self.expires = datetime.combine(day + timedelta(days=1), datetime.min.time(), EASTERN).astimezone(UTC)
            self.quote = {**quote, "valid_until": self.expires.timestamp()}
            self.retry_at = None
            return dict(self.quote)
