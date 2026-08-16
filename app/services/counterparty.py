"""Extract a short merchant/payee name (counterParty) from bank operation notes."""

from __future__ import annotations

import re

COUNTERPARTY_MAX_LEN = 255

# Trailing ISO-ish country tokens (card network style: … CITY COUNTRY).
_COUNTRY_TOKENS: frozenset[str] = frozenset(
    {
        "ukr",
        "ukraine",
        "usa",
        "us",
        "lux",
        "luxembourg",
        "pol",
        "poland",
        "deu",
        "ger",
        "germany",
        "gbr",
        "uk",
        "cze",
        "svk",
        "hun",
        "rou",
        "mda",
        "ltu",
        "lva",
        "est",
        "esp",
        "fra",
        "ita",
        "nld",
        "bel",
        "aut",
        "che",
        "can",
        "tur",
        "are",
        "cyp",
        "isr",
        "geo",
        "aze",
        "arm",
    }
)

# Cities / transliterations commonly glued after merchant name.
_CITY_TOKENS: frozenset[str] = frozenset(
    {
        "kyiv",
        "kiyev",
        "kiev",
        "lviv",
        "lvov",
        "odesa",
        "odessa",
        "kharkiv",
        "kharkov",
        "dnipro",
        "dnipropetrovsk",
        "zaporizhzhia",
        "zaporizhia",
        "vinnytsia",
        "vinnitsa",
        "ivano-frankivsk",
        "chernivtsi",
        "chernigiv",
        "chernihiv",
        "mykolaiv",
        "nikolaev",
        "kherson",
        "poltava",
        "sumy",
        "zhytomyr",
        "rivne",
        "rovno",
        "ternopil",
        "uzhhorod",
        "lutsk",
        "kropyvnytskyi",
        "kropivnitsky",
        "luxembourg",
        "renton",
        "london",
        "paris",
        "berlin",
        "warsaw",
        "warszawa",
        "prague",
        "praha",
        "vienna",
        "wien",
        "amsterdam",
        "dublin",
        "madrid",
        "rome",
        "roma",
        "milan",
        "milano",
    }
)

# Legal / company suffixes — keep as part of the name.
_COMPANY_SUFFIXES: frozenset[str] = frozenset(
    {
        "inc",
        "inc.",
        "ltd",
        "ltd.",
        "llc",
        "llc.",
        "llp",
        "corp",
        "corp.",
        "co",
        "co.",
        "sa",
        "s.a.",
        "sarl",
        "s.a.r.l",
        "s.a.r.l.",
        "gmbh",
        "ag",
        "plc",
        "bv",
        "nv",
        "oy",
        "ab",
        "spa",
        "srl",
    }
)

_RE_PAYMENT_TAIL = re.compile(
    r"\s*:\s*(?:Google Pay|Apple Pay|M4M|Garmin Pay|Samsung Pay)\b.*$",
    re.IGNORECASE,
)
_RE_COMPANY_PAYMENT = re.compile(
    r"^Оплата послуг компанії\s+(.+?)(?:\s*\(|$)",
    re.IGNORECASE,
)
_RE_TRANSFER_BENEFIT = re.compile(
    r"^Переказ на користь\s+(.+)$",
    re.IGNORECASE,
)
_RE_TOPUP = re.compile(
    r"^(?:Пополнение счета|Поповнення рахунку)\s+(.+)$",
    re.IGNORECASE,
)
_RE_INSURANCE = re.compile(
    r"/=01~[^~]*~[^~]*~([^~]+)~",
)
_RE_CARD_ONLY = re.compile(
    r"^Переказ на карту\s+\d",
    re.IGNORECASE,
)
_RE_TERMINAL = re.compile(
    r"в\s*терміналі|в\s*ATM|АТМ\s+\w+",
    re.IGNORECASE,
)
_RE_FX = re.compile(
    r"іноземної валюти|купівлі іноземної|Купівля іноземної",
    re.IGNORECASE,
)
_RE_FEE = re.compile(r"^Комісія\b", re.IGNORECASE)
_RE_GIG = re.compile(r"винагор", re.IGNORECASE)


def extract_counterparty(note: str | None) -> str:
    """Return a short payee/merchant name from a bank «Опис операції», or \"\"."""
    if not note:
        return ""
    text = str(note).replace("\xa0", " ").strip()
    if not text:
        return ""

    # Card-network style: …\\MERCHANT CITY COUNTRY : Google Pay ****1234.
    if "\\" in text:
        segment = text.rsplit("\\", 1)[-1].strip()
        segment = _strip_payment_method(segment)
        # Commission lines end with Visa UKRSIBOnline — not a merchant.
        if _looks_like_fee_channel(segment):
            return ""
        name = _strip_trailing_location(segment)
        return _finalize(name)

    m = _RE_COMPANY_PAYMENT.match(text)
    if m:
        return _finalize(m.group(1).strip())

    m = _RE_TRANSFER_BENEFIT.match(text)
    if m:
        return _finalize(m.group(1).strip())

    m = _RE_TOPUP.match(text)
    if m:
        return _finalize(m.group(1).strip())

    m = _RE_INSURANCE.search(text)
    if m:
        return _finalize(m.group(1).strip())

    # No reliable merchant in terminal IDs, FX, fees, card-number transfers, gigs.
    if (
        _RE_CARD_ONLY.match(text)
        or _RE_TERMINAL.search(text)
        or _RE_FX.search(text)
        or _RE_FEE.match(text)
        or _RE_GIG.search(text)
    ):
        return ""

    return ""


def _strip_payment_method(segment: str) -> str:
    # Prefer splitting on " : " (bank format), then known wallet tails.
    if " : " in segment:
        segment = segment.split(" : ", 1)[0]
    segment = _RE_PAYMENT_TAIL.sub("", segment)
    return segment.strip().rstrip(".")


def _looks_like_fee_channel(segment: str) -> bool:
    low = segment.casefold()
    return "ukrsibonline" in low or low in {"visa", "mastercard", "mastercard\\visa"}


def _norm_token(token: str) -> str:
    return token.strip().strip(",.;").casefold()


def _strip_trailing_location(segment: str) -> str:
    tokens = segment.split()
    if not tokens:
        return ""

    # Drop trailing store / terminal numeric codes (e.g. SHOP.SILPO.UA 10).
    while tokens and tokens[-1].isdigit():
        tokens.pop()

    # Drop trailing country, then city (possibly multi-token like New York).
    changed = True
    while changed and tokens:
        changed = False
        last = _norm_token(tokens[-1])
        if last in _COUNTRY_TOKENS:
            tokens.pop()
            changed = True
            continue
        if last in _CITY_TOKENS and last not in _COMPANY_SUFFIXES:
            tokens.pop()
            changed = True
            continue
        # Multi-token city: New York (only as a trailing pair).
        if (
            len(tokens) >= 2
            and _norm_token(tokens[-1]) == "york"
            and _norm_token(tokens[-2]) == "new"
        ):
            tokens.pop()
            tokens.pop()
            changed = True
            continue

    # Drop another trailing digit block if location stripping exposed it.
    while tokens and tokens[-1].isdigit():
        tokens.pop()

    return " ".join(tokens).strip().rstrip(",.;")


def _finalize(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        return ""
    return name[:COUNTERPARTY_MAX_LEN]
