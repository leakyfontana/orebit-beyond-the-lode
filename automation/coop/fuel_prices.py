"""Current AAA regular US national average, cached until Eastern midnight."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from html.parser import HTMLParser
import math
import re
from zoneinfo import ZoneInfo

AAA_URL = "https://gasprices.aaa.com/"
MAX_RESPONSE = 2 * 1024 * 1024
FETCH_TIMEOUT = 20
EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc


class PriceUnavailable(Exception):
    """No current usable AAA price exists."""


class HTMLVisibility(Enum):
    VISIBLE = auto()
    HIDDEN = auto()


class HTMLRowState(Enum):
    OUTSIDE = auto()
    COLLECTING = auto()


class HTMLCellState(Enum):
    OUTSIDE = auto()
    COLLECTING = auto()


class HeaderColumnState(Enum):
    SEARCHING = auto()
    REGULAR_KNOWN = auto()


class QuoteState(Enum):
    EMPTY = auto()
    FETCHING = auto()
    VALID = auto()
    EXPIRED = auto()
    RETRY_COOLDOWN = auto()


class AAAHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.rows = []
        self.row = None
        self.cell = None
        self.row_state = HTMLRowState.OUTSIDE
        self.cell_state = HTMLCellState.OUTSIDE
        self.hidden_depth = 0

    @property
    def visibility(self):
        return HTMLVisibility.HIDDEN if self.hidden_depth else HTMLVisibility.VISIBLE

    def _begin_row(self):
        self.row = []
        self.row_state = HTMLRowState.COLLECTING

    def _begin_cell(self):
        self.cell = []
        self.cell_state = HTMLCellState.COLLECTING

    def _finish_cell(self):
        self.row.append(" ".join("".join(self.cell).split()))
        self.cell = None
        self.cell_state = HTMLCellState.OUTSIDE

    def _finish_row(self):
        self.rows.append(self.row)
        self.row = None
        self.row_state = HTMLRowState.OUTSIDE

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden_depth += 1
        if tag == "tr":
            self._begin_row()
        elif tag in ("th", "td") and self.row_state is HTMLRowState.COLLECTING:
            self._begin_cell()

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden_depth = max(0, self.hidden_depth - 1)
        if tag in ("td", "th") and self.cell_state is HTMLCellState.COLLECTING:
            self._finish_cell()
        elif tag == "tr" and self.row_state is HTMLRowState.COLLECTING:
            self._finish_row()

    def handle_data(self, data):
        if self.visibility is HTMLVisibility.VISIBLE:
            self.text.append(data)
            if self.cell_state is HTMLCellState.COLLECTING:
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
    header_state = HeaderColumnState.SEARCHING
    regular = 0
    for row in page.rows:
        if "Regular" in row and "Mid-Grade" in row:
            regular = row.index("Regular")
            header_state = HeaderColumnState.REGULAR_KNOWN
        elif header_state is HeaderColumnState.REGULAR_KNOWN and row and row[0] == "Current Avg." and len(row) > regular:
            cell = row[regular]
            if re.fullmatch(r"\$\d+(?:\.\d+)?", cell):
                price = float(cell[1:])
                if math.isfinite(price) and price > 0:
                    return {"price_per_gallon": price, "date": date.isoformat(), "source": "aaa"}
    raise ValueError("AAA regular average missing")


class FuelPrices:
    def __init__(self, *, user_agent="OrebitBeyondTheLode/1.0", clock=None):
        self.user_agent = user_agent
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock = asyncio.Lock()
        self._state = QuoteState.EMPTY
        self._quote = None
        self._expires = None
        self._retry_at = None

    @property
    def state(self):
        return self._state_at(self.clock())

    def _state_at(self, now):
        if self._state is QuoteState.VALID and now >= self._expires:
            return QuoteState.EXPIRED
        if self._state is QuoteState.RETRY_COOLDOWN and now >= self._retry_at:
            return QuoteState.EMPTY
        return self._state

    def _begin_fetch(self):
        previous = self._state
        self._state = QuoteState.FETCHING
        return previous

    def _restore_interrupted_fetch(self, previous):
        if self._state is QuoteState.FETCHING:
            self._state = previous

    def _begin_retry_cooldown(self):
        self._quote = None
        self._expires = None
        self._retry_at = self.clock() + timedelta(seconds=60)
        self._state = QuoteState.RETRY_COOLDOWN

    def _accept_quote(self, quote, now):
        day = now.astimezone(EASTERN).date()
        self._expires = datetime.combine(day + timedelta(days=1), datetime.min.time(), EASTERN).astimezone(UTC)
        self._quote = {**quote, "valid_until": self._expires.timestamp()}
        self._retry_at = None
        self._state = QuoteState.VALID

    async def _fetch(self):
        process = None
        try:
            # AAA challenges Python's HTTP/TLS client in production. Use the
            # system HTTPS client directly, without cookies or challenge solving.
            process = await asyncio.create_subprocess_exec(
                "curl", "--disable", "--silent", "--fail",
                "--proto", "=https", "--max-time", str(FETCH_TIMEOUT),
                "--max-filesize", str(MAX_RESPONSE),
                "--user-agent", self.user_agent, AAA_URL,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            async def receive():
                try:
                    raw = await process.stdout.readexactly(MAX_RESPONSE + 1)
                except asyncio.IncompleteReadError as completed:
                    raw = completed.partial
                else:
                    raise PriceUnavailable()
                if await process.wait() != 0:
                    raise PriceUnavailable()
                return raw.decode("utf-8")

            return await asyncio.wait_for(receive(), FETCH_TIMEOUT)
        except (OSError, asyncio.TimeoutError, UnicodeError):
            raise PriceUnavailable() from None
        finally:
            if process is not None:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await process.wait()

    async def price(self):
        async with self.lock:
            now = self.clock()
            state = self._state_at(now)
            if state is QuoteState.VALID:
                return dict(self._quote)
            if state is QuoteState.RETRY_COOLDOWN:
                raise PriceUnavailable()
            previous = self._begin_fetch()
            try:
                try:
                    document = await self._fetch()
                    # A request may cross midnight: date validation and expiry must
                    # both use the time at which the response actually arrived.
                    now = self.clock()
                    quote = parse_aaa(document, now)
                except (PriceUnavailable, asyncio.TimeoutError, ValueError, UnicodeError):
                    self._begin_retry_cooldown()
                    raise PriceUnavailable() from None
                self._accept_quote(quote, now)
                return dict(self._quote)
            finally:
                # Cancellation and unexpected failures leave the previous cache
                # eligibility intact, just as a fetch that never completed.
                self._restore_interrupted_fetch(previous)
