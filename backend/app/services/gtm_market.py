"""
Market intelligence per region.

Static, researched profiles (outreach law, buying culture, channels, fiscal years) are
combined with live signals fetched at request time:

- Public holidays in the next 60 days (Nager.Date, no key)
- GDP growth, inflation, unemployment (World Bank Indicators API, no key)
- Recent business headlines (Google News RSS, no key)
- Computed from today's date: local time, business hours, fiscal year-end countdown,
  quarter-end pressure, and seasonal windows (Ramadan, Golden Week, August in Europe...)

Live data is cached in memory for a few hours and every fetch fails soft: a region
always returns its static profile even when a source is down.

The outreach rules summarise published guidance as of November 2026. Several are
contested in the sources and are marked as such. This is not legal advice.
"""

import calendar
import json
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..utils.logger import get_logger

logger = get_logger('mirofish.gtm_market')

USER_AGENT = 'GTM-Simulation-Lab/1.0 (market intelligence)'
HTTP_TIMEOUT = 6
WB_TIMEOUT = 20  # the World Bank API is often slow
CACHE_TTL = 6 * 3600
HOLIDAY_WINDOW_DAYS = 60

# Rule codes, from most to least permissive
RULE_LABELS = {
    'opt_out': 'Cold B2B email allowed with opt-out',
    'role_based': 'Allowed to published work addresses, if relevant to the role',
    'changing': 'Rules tightening soon',
    'unclear': 'Unclear, get legal review',
    'opt_in': 'Prior consent required',
}
RULE_STRICTNESS = ['opt_out', 'role_based', 'changing', 'unclear', 'opt_in']


def _c(code, name, tz, law, rule, confidence, note, weekend=(5, 6)):
    return {'code': code, 'name': name, 'tz': tz, 'weekend': list(weekend),
            'law': law, 'rule': rule, 'confidence': confidence, 'note': note}


REGION_MARKETS: Dict[str, Dict[str, Any]] = {
    'north_america': {
        'label': 'North America',
        'countries': [
            _c('US', 'United States', 'America/New_York', 'CAN-SPAM Act', 'opt_out', 'settled',
               'Cold B2B email is legal with accurate headers, a physical postal address, and an unsubscribe honored within 10 business days.'),
            _c('CA', 'Canada', 'America/Toronto', 'CASL', 'opt_in', 'settled',
               'Needs express or implied consent. A published business address only counts if it has no "no solicitation" notice and the message fits the person\'s role. You carry the burden of proof.'),
        ],
        'languages': ['English', 'French (Quebec)', 'Spanish'],
        'currency': 'USD, CAD',
        'channels': ['Email', 'LinkedIn', 'Phone', 'Events'],
        'culture': 'Direct and ROI-driven. Buyers expect numbers, case studies, and a fast path to a demo. Startups decide quickly; enterprises route through security reviews and procurement.',
        'sales_cycle': 'SMB 2 to 6 weeks, mid-market 1 to 3 months, enterprise 6 to 12 months.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31},
                         {'label': 'US federal government', 'month': 9, 'day': 30}],
        'news_terms': ['US economy', 'US startups', 'Canada economy'],
    },
    'latam': {
        'label': 'Latin America',
        'countries': [
            _c('BR', 'Brazil', 'America/Sao_Paulo', 'LGPD', 'opt_out', 'contested',
               'No dedicated anti-spam statute. Business contacts need a documented legal basis (often legitimate interest) and an easy opt-out.'),
            _c('MX', 'Mexico', 'America/Mexico_City', 'LFPDPPP (2025)', 'opt_out', 'contested',
               'A privacy notice and a way to object are required; honor opt-out requests promptly.'),
            _c('CO', 'Colombia', 'America/Bogota', 'Law 1581 of 2012', 'opt_in', 'contested',
               'Prior, express, informed authorization is the general rule for processing personal data.'),
            _c('CL', 'Chile', 'America/Santiago', 'Law 21.719 (from Dec 2026)', 'changing', 'contested',
               'A new GDPR-style data protection law takes effect in December 2026. Promotional emails must already carry an unsubscribe link.'),
        ],
        'languages': ['Portuguese', 'Spanish'],
        'currency': 'BRL, MXN, COP, CLP',
        'channels': ['WhatsApp', 'LinkedIn', 'Email', 'Phone'],
        'culture': 'Relationship-first. Expect calls and video meetings before any deal, and WhatsApp for day-to-day contact. Local-language outreach and local pricing in local currency lift replies.',
        'sales_cycle': 'Usually longer than the US for the same deal size; trust is built over several touches.',
        'fiscal_years': [{'label': 'Calendar year (set by law in most countries)', 'month': 12, 'day': 31}],
        'news_terms': ['Brazil economy', 'Mexico economy', 'Latin America startups'],
    },
    'uk_ireland': {
        'label': 'UK & Ireland',
        'countries': [
            _c('GB', 'United Kingdom', 'Europe/London', 'PECR + UK GDPR', 'opt_out', 'settled',
               'Email to companies (corporate subscribers) needs no prior consent, with sender ID and an opt-out. Sole traders and partnerships need consent.'),
            _c('IE', 'Ireland', 'Europe/Dublin', 'ePrivacy Regulations (S.I. 336/2011)', 'opt_out', 'contested',
               'Email to business addresses is generally allowed with an opt-out; individuals need consent.'),
        ],
        'languages': ['English', 'Irish'],
        'currency': 'GBP, EUR',
        'channels': ['Email', 'LinkedIn', 'Phone (screen against CTPS)'],
        'culture': 'Understated and skeptical of hype. Credible references and a low-pressure ask work better than urgency tactics.',
        'sales_cycle': 'Similar to the US mid-market; public sector buys through frameworks and tenders.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31},
                         {'label': 'UK government and many UK firms', 'month': 3, 'day': 31}],
        'news_terms': ['UK economy', 'UK startups', 'Ireland economy'],
    },
    'western_europe': {
        'label': 'Western Europe',
        'countries': [
            _c('FR', 'France', 'Europe/Paris', 'CNIL guidance (CPCE L.34-5)', 'role_based', 'settled',
               'B2B email without prior consent is allowed when the message relates to the recipient\'s job, with an opt-out.'),
            _c('NL', 'Netherlands', 'Europe/Amsterdam', 'Telecommunicatiewet art. 11.7', 'unclear', 'contested',
               'The opt-in rule was extended to legal entities in 2009; sources disagree on how far the published-address exception goes.'),
            _c('ES', 'Spain', 'Europe/Madrid', 'LSSI art. 21', 'opt_in', 'settled',
               'Commercial email needs prior consent, business recipients included.'),
            _c('IT', 'Italy', 'Europe/Rome', 'Privacy Code art. 130', 'opt_in', 'settled',
               'Automated or email marketing needs prior consent.'),
        ],
        'languages': ['French', 'Dutch', 'Spanish', 'Italian', 'English'],
        'currency': 'EUR',
        'channels': ['LinkedIn', 'Email (where allowed)', 'Events', 'Partners'],
        'culture': 'Local language matters, especially in France, Spain, and Italy. GDPR awareness is high, so expect data-handling questions early. Relationships and referrals carry weight.',
        'sales_cycle': 'Longer than the US; summer and year-end slow decisions noticeably.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31}],
        'news_terms': ['France economy', 'eurozone economy', 'European startups'],
    },
    'dach': {
        'label': 'DACH',
        'countries': [
            _c('DE', 'Germany', 'Europe/Berlin', 'UWG §7', 'opt_in', 'settled',
               'Email advertising needs prior express consent, B2B included. B2B phone calls may rely on presumed consent.'),
            _c('AT', 'Austria', 'Europe/Vienna', 'TKG 2021 §174', 'opt_in', 'contested',
               'Email marketing needs prior consent, generally including business recipients.'),
            _c('CH', 'Switzerland', 'Europe/Zurich', 'UWG Art. 3(1)(o)', 'opt_in', 'contested',
               'Mass advertising email needs prior consent and an opt-out; one-to-one, individually written emails are treated more leniently.'),
        ],
        'languages': ['German', 'French', 'Italian'],
        'currency': 'EUR, CHF',
        'channels': ['LinkedIn', 'Phone (B2B)', 'Events and trade fairs', 'Partners'],
        'culture': 'Formal (use "Sie"), precise, and evidence-driven. Expect detailed technical and data-protection questions, German-language materials, and consensus across several stakeholders.',
        'sales_cycle': 'Long and thorough; a pilot or proof of concept is common before signing.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31}],
        'news_terms': ['Germany economy', 'German startups', 'Switzerland economy'],
    },
    'nordics': {
        'label': 'Nordics',
        'countries': [
            _c('SE', 'Sweden', 'Europe/Stockholm', 'Marketing Act §19-20', 'opt_out', 'contested',
               'The consent rule covers individuals; email to legal persons is allowed with a working opt-out.'),
            _c('NO', 'Norway', 'Europe/Oslo', 'Marketing Control Act §15', 'role_based', 'contested',
               'Consent required for individuals; email to company addresses is generally allowed.'),
            _c('DK', 'Denmark', 'Europe/Copenhagen', 'Marketing Practices Act §10', 'opt_in', 'settled',
               'Consent needed for businesses too, and an email asking for consent counts as marketing.'),
            _c('FI', 'Finland', 'Europe/Helsinki', 'Information Society Code', 'role_based', 'contested',
               'B2B email allowed when relevant to the recipient\'s role, with an opt-out.'),
        ],
        'languages': ['Swedish', 'Norwegian', 'Danish', 'Finnish', 'English'],
        'currency': 'SEK, NOK, DKK, EUR',
        'channels': ['Email', 'LinkedIn', 'Events'],
        'culture': 'Flat hierarchies and consensus. Direct, factual, and allergic to hype. English is widely accepted, and sustainability claims get scrutinised.',
        'sales_cycle': 'Moderate; consensus takes time but decisions stick.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31}],
        'news_terms': ['Sweden economy', 'Nordic startups', 'Denmark economy'],
    },
    'middle_east': {
        'label': 'Middle East',
        'countries': [
            _c('AE', 'United Arab Emirates', 'Asia/Dubai', 'PDPL (Decree-Law 45/2021)', 'opt_in', 'contested',
               'Consent is the main legal basis for marketing; treat cold email as opt-in.'),
            _c('SA', 'Saudi Arabia', 'Asia/Riyadh', 'PDPL (SDAIA)', 'opt_in', 'contested',
               'Direct marketing generally needs prior consent and an opt-out.', weekend=(4, 5)),
        ],
        'languages': ['Arabic', 'English'],
        'currency': 'AED, SAR',
        'channels': ['WhatsApp', 'LinkedIn', 'In-person meetings', 'Partners'],
        'culture': 'Trust and relationships come before business. Senior people decide, meetings often happen in person, and government-linked buyers expect local presence or a local partner.',
        'sales_cycle': 'Relationship-led and can be long; Ramadan slows decisions.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31}],
        'news_terms': ['UAE economy', 'Saudi Arabia economy', 'Middle East startups'],
    },
    'africa': {
        'label': 'Africa',
        'countries': [
            _c('ZA', 'South Africa', 'Africa/Johannesburg', 'POPIA s69', 'opt_in', 'contested',
               'Electronic direct marketing needs consent unless the recipient is an existing customer; widely read to cover companies too.'),
            _c('NG', 'Nigeria', 'Africa/Lagos', 'NDPA 2023', 'opt_in', 'contested',
               'Consent-based regime for direct marketing; honor objections.'),
            _c('KE', 'Kenya', 'Africa/Nairobi', 'Data Protection Act 2019', 'opt_in', 'contested',
               'Commercial use of personal data for direct marketing generally needs consent.'),
            _c('EG', 'Egypt', 'Africa/Cairo', 'PDPL (Law 151/2020)', 'opt_in', 'contested',
               'Electronic marketing needs the recipient\'s consent and an opt-out.'),
        ],
        'languages': ['English', 'French', 'Arabic', 'Swahili'],
        'currency': 'ZAR, NGN, KES, EGP',
        'channels': ['WhatsApp', 'LinkedIn', 'Phone', 'Partners'],
        'culture': 'Mobile-first and relationship-driven. Price and currency risk matter, so local pricing and flexible payment terms help.',
        'sales_cycle': 'Varies widely by country; referrals shorten it.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31},
                         {'label': 'South African government', 'month': 3, 'day': 31}],
        'news_terms': ['South Africa economy', 'Nigeria economy', 'African startups'],
    },
    'india': {
        'label': 'India',
        'countries': [
            _c('IN', 'India', 'Asia/Kolkata', 'DPDP Act 2023 + Rules 2025', 'changing', 'settled',
               'No dedicated anti-spam email law today. DPDP consent and notice duties apply from 13 May 2027. Calls and SMS fall under TRAI\'s DND rules.'),
        ],
        'languages': ['English', 'Hindi', 'regional languages'],
        'currency': 'INR',
        'channels': ['Email', 'LinkedIn', 'WhatsApp', 'Phone'],
        'culture': 'Price-sensitive with negotiation expected. Several stakeholders weigh in, and a pilot or proof of concept is common. Relationships and referrals open doors.',
        'sales_cycle': 'SMB fast; enterprise long, with procurement and pricing rounds.',
        'fiscal_years': [{'label': 'All companies (statutory)', 'month': 3, 'day': 31}],
        'news_terms': ['India economy', 'Indian startups', 'India funding'],
    },
    'southeast_asia': {
        'label': 'Southeast Asia',
        'countries': [
            _c('SG', 'Singapore', 'Asia/Singapore', 'Spam Control Act + PDPA', 'opt_out', 'settled',
               'Unsolicited bulk email needs an unsubscribe and an <ADV> label. B2B messages are exempt from the Do Not Call rules.'),
            _c('ID', 'Indonesia', 'Asia/Jakarta', 'PDP Law 27/2022', 'opt_in', 'contested',
               'Comprehensive data law in force since October 2024; consent is the main basis.'),
            _c('MY', 'Malaysia', 'Asia/Kuala_Lumpur', 'PDPA 2010', 'unclear', 'contested',
               'Processing needs consent, and recipients can demand you stop direct marketing.'),
            _c('PH', 'Philippines', 'Asia/Manila', 'Data Privacy Act 2012', 'opt_in', 'contested',
               'Consent-based for marketing to individuals; respect opt-outs.'),
            _c('VN', 'Vietnam', 'Asia/Ho_Chi_Minh', 'Decree 91/2020 + Decree 13/2023', 'opt_in', 'contested',
               'Advertising email needs the recipient\'s prior consent.'),
            _c('TH', 'Thailand', 'Asia/Bangkok', 'PDPA 2019', 'opt_in', 'contested',
               'Consent is generally required for direct marketing.'),
        ],
        'languages': ['English', 'Bahasa', 'Thai', 'Vietnamese', 'Tagalog'],
        'currency': 'SGD, IDR, MYR, PHP, VND, THB',
        'channels': ['LinkedIn', 'WhatsApp', 'LINE (Thailand)', 'Email (Singapore)'],
        'culture': 'Very different markets under one label. Singapore is the regional HQ hub and buys like a developed market; elsewhere relationships, local partners, and messaging apps dominate.',
        'sales_cycle': 'Singapore moderate; emerging markets longer and partner-led.',
        'fiscal_years': [{'label': 'Most companies', 'month': 12, 'day': 31},
                         {'label': 'Singapore government', 'month': 3, 'day': 31}],
        'news_terms': ['Singapore economy', 'Southeast Asia startups', 'Indonesia economy'],
    },
    'anz': {
        'label': 'Australia & NZ',
        'countries': [
            _c('AU', 'Australia', 'Australia/Sydney', 'Spam Act 2003', 'role_based', 'settled',
               'Consent can be inferred from a conspicuously published work address only if the message relates to the person\'s role. Unsubscribe required.'),
            _c('NZ', 'New Zealand', 'Pacific/Auckland', 'UEM Act 2007', 'role_based', 'settled',
               'Deemed consent from a published work address applies only when the message is relevant to the role.'),
        ],
        'languages': ['English'],
        'currency': 'AUD, NZD',
        'channels': ['Email', 'LinkedIn', 'Phone'],
        'culture': 'Informal and direct, with little patience for hard selling or hype. Local references and support in local time zones matter.',
        'sales_cycle': 'Similar to the UK; government buys via panels.',
        'fiscal_years': [{'label': 'Most Australian companies', 'month': 6, 'day': 30},
                         {'label': 'Many NZ companies', 'month': 3, 'day': 31}],
        'news_terms': ['Australia economy', 'Australian startups', 'New Zealand economy'],
    },
    'east_asia': {
        'label': 'Japan & Korea',
        'countries': [
            _c('JP', 'Japan', 'Asia/Tokyo', 'Specified Electronic Mail Act', 'role_based', 'contested',
               'Opt-in by default, but a business that publishes its own address can be emailed unless it says it refuses ads. Sender ID and opt-out required.'),
            _c('KR', 'South Korea', 'Asia/Seoul', 'Network Act Art. 50', 'opt_in', 'settled',
               'Prior consent needed, B2B included. Ads must be labeled, and sending between 9pm and 8am needs separate consent.'),
        ],
        'languages': ['Japanese', 'Korean'],
        'currency': 'JPY, KRW',
        'channels': ['Partners and resellers', 'Events', 'LinkedIn (limited)', 'KakaoTalk (Korea)'],
        'culture': 'Japan decides by consensus (nemawashi, ringi) and expects Japanese-language materials, local references, and long-term commitment. Korea moves faster but is hierarchical.',
        'sales_cycle': 'Japan long (often 6 to 12 months); Korea moderate.',
        'fiscal_years': [{'label': 'Most large Japanese companies', 'month': 3, 'day': 31},
                         {'label': 'Korean companies', 'month': 12, 'day': 31}],
        'news_terms': ['Japan economy', 'Japan startups', 'South Korea economy'],
    },
}

# Seasonal windows: (region ids or '*', start (m, d), end (m, d), note). Dated events
# that move each year (Ramadan, Lunar New Year, Diwali) are listed per year.
SEASONS = [
    (tuple(r for r in REGION_MARKETS if r != 'middle_east'), (12, 18), (12, 31),
     'Year-end holidays: many buyers are away and new projects wait for January.'),
    (('western_europe', 'dach', 'nordics', 'uk_ireland'), (7, 15), (8, 31), 'Summer holidays: decision makers are often away for two to four weeks.'),
    (('east_asia',), (4, 29), (5, 6), 'Golden Week in Japan: offices largely closed.'),
    (('east_asia',), (8, 10), (8, 18), 'Obon in Japan: many companies close for several days.'),
    (('east_asia',), (12, 28), (12, 31), 'Japanese year-end closing period.'),
    (('east_asia',), (1, 1), (1, 4), 'Japanese New Year closing period.'),
    (('north_america',), (11, 20), (11, 30), 'Thanksgiving week in the US: low response rates.'),
]
DATED_EVENTS = {
    ('middle_east', 'africa', 'southeast_asia', 'india'): [
        (date(2026, 2, 18), date(2026, 3, 19), 'Ramadan (approximate dates): shorter working hours and slower decisions.'),
        (date(2027, 2, 8), date(2027, 3, 9), 'Ramadan (approximate dates): shorter working hours and slower decisions.'),
        (date(2028, 1, 28), date(2028, 2, 26), 'Ramadan (approximate dates): shorter working hours and slower decisions.'),
    ],
    ('east_asia', 'southeast_asia'): [
        (date(2027, 2, 5), date(2027, 2, 9), 'Lunar New Year: Korean Seollal and wider Asia slow down.'),
        (date(2028, 1, 25), date(2028, 1, 29), 'Lunar New Year: Korean Seollal and wider Asia slow down.'),
    ],
    ('india',): [
        (date(2026, 11, 6), date(2026, 11, 10), 'Diwali week: many businesses slow down.'),
        (date(2027, 10, 27), date(2027, 10, 31), 'Diwali week: many businesses slow down.'),
    ],
}

# ── Cache and HTTP ───────────────────────────────────────────────────────────

_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()


def _cached(key: str, fn, ttl: int = CACHE_TTL):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    if value is not None:
        with _cache_lock:
            _cache[key] = (now, value)
    return value


def _get(url: str, timeout: float = HTTP_TIMEOUT) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        logger.warning(f"Market fetch failed ({url.split('?')[0]}): {e}")
        return None


# ── Live sources ─────────────────────────────────────────────────────────────

INDICATORS = {
    'gdp_growth': ('NY.GDP.MKTP.KD.ZG', 'GDP growth', '%'),
    'inflation': ('FP.CPI.TOTL.ZG', 'Inflation', '%'),
    'unemployment': ('SL.UEM.TOTL.ZS', 'Unemployment', '%'),
}


def fetch_indicators(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """Most recent non-empty World Bank value per country and indicator (cached per country)."""
    out: Dict[str, Dict[str, Any]] = {}
    missing = []
    now = time.time()
    with _cache_lock:
        for c in codes:
            hit = _cache.get(f'wbc:{c}')
            if hit and now - hit[0] < 24 * 3600:
                out[c] = hit[1]
            else:
                missing.append(c)
    if not missing:
        return out

    def one(item):
        key, (wb_code, _, _) = item
        url = (f"https://api.worldbank.org/v2/country/{';'.join(missing)}/indicator/{wb_code}"
               f"?format=json&mrnev=1&per_page=200")
        raw = _get(url, timeout=WB_TIMEOUT)
        try:
            return key, (json.loads(raw)[1] or []) if raw else []
        except (ValueError, IndexError, TypeError):
            return key, []

    fresh: Dict[str, Dict[str, Any]] = {c: {} for c in missing}
    with ThreadPoolExecutor(max_workers=len(INDICATORS)) as pool:
        for key, rows in pool.map(one, INDICATORS.items()):
            for r in rows:
                iso2 = (r.get('country') or {}).get('id')
                if iso2 in fresh and r.get('value') is not None:
                    fresh[iso2][key] = {'value': round(float(r['value']), 1), 'year': r.get('date')}
    with _cache_lock:
        for c, vals in fresh.items():
            if vals:
                _cache[f'wbc:{c}'] = (now, vals)
    out.update(fresh)
    return out


def prefetch_indicators(region_ids: List[str]) -> None:
    """Warm the indicator cache for several regions in one round of requests."""
    codes = [c['code'] for r in region_ids if r in REGION_MARKETS for c in REGION_MARKETS[r]['countries']]
    if codes:
        fetch_indicators(codes)


def fetch_holidays(code: str, today: date) -> Optional[List[Dict[str, str]]]:
    """Public holidays in the next HOLIDAY_WINDOW_DAYS days, or None when unsupported."""
    def load():
        raw = _get(f"https://date.nager.at/api/v3/NextPublicHolidays/{code}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None
    rows = _cached(f'hol:{code}', load)
    if rows is None:
        return None
    horizon = today + timedelta(days=HOLIDAY_WINDOW_DAYS)
    out = []
    for r in rows:
        try:
            d = date.fromisoformat(r['date'])
        except (KeyError, ValueError):
            continue
        if today <= d <= horizon and (r.get('global', True) or not r.get('counties')):
            out.append({'date': r['date'], 'name': r.get('name') or r.get('localName', '')})
    return out


_SKIP_SOURCES = ('britannica', 'wikipedia')


def fetch_headlines(terms: List[str], limit: int = 4) -> List[Dict[str, str]]:
    """Recent business headlines (last 7 days) from Google News RSS."""
    def load():
        q = ' OR '.join(f'"{t}"' for t in terms) + ' when:7d'
        url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode(
            {'q': q, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
        raw = _get(url)
        if not raw:
            return None
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return None
        items = []
        for it in root.findall('./channel/item'):
            src = it.find('source')
            source = (src.text or '') if src is not None else ''
            title = it.findtext('title') or ''
            if source and title.endswith(' - ' + source):
                title = title[: -len(' - ' + source)]
            if any(s in source.lower() for s in _SKIP_SOURCES):
                continue
            items.append({'title': title.strip(), 'source': source, 'url': it.findtext('link') or '',
                          'date': it.findtext('pubDate') or ''})
            if len(items) >= limit:
                break
        return items
    return _cached('news:' + '|'.join(terms), load, ttl=3 * 3600) or []


# ── Computed signals ─────────────────────────────────────────────────────────

def _local_status(country: Dict[str, Any], now_utc: datetime) -> Dict[str, Any]:
    local = now_utc.astimezone(ZoneInfo(country['tz']))
    is_workday = local.weekday() not in country['weekend']
    open_now = is_workday and 9 <= local.hour < 18
    return {'time': local.strftime('%H:%M'), 'weekday': local.strftime('%a'),
            'open': open_now, 'tz': country['tz']}


def _next_fiscal_end(month: int, day: int, today: date) -> date:
    end = date(today.year, month, day)
    return end if end >= today else date(today.year + 1, month, day)


def _timing(region_id: str, profile: Dict[str, Any], today: date) -> List[str]:
    notes: List[str] = []
    for fy in profile['fiscal_years']:
        end = _next_fiscal_end(fy['month'], fy['day'], today)
        days = (end - today).days
        prev_end = date(end.year - 1, fy['month'], fy['day'])
        since_start = (today - prev_end).days
        if days <= 60:
            notes.append(f"{fy['label']}: fiscal year ends in {days} days. Expect use-it-or-lose-it budget, "
                         'but few new projects start before the new year.')
        elif since_start <= 60:
            notes.append(f"{fy['label']}: new fiscal year started {since_start} days ago. Fresh budgets are being allocated.")
    q_month = ((today.month - 1) // 3 + 1) * 3
    q_end = date(today.year, q_month, calendar.monthrange(today.year, q_month)[1])
    if 0 <= (q_end - today).days <= 14:
        notes.append(f"Quarter ends in {(q_end - today).days} days: sales teams push to close, buyers can negotiate.")
    for regions, start, end, note in SEASONS:
        if region_id not in regions:
            continue
        s, e = date(today.year, *start), date(today.year, *end)
        if s - timedelta(days=21) <= today <= e:
            notes.append(note)
    for regions, events in DATED_EVENTS.items():
        if region_id not in regions:
            continue
        for s, e, note in events:
            if s - timedelta(days=45) <= today <= e:
                when = 'now' if s <= today else f"from {s.strftime('%d %b')}"
                notes.append(f"{note} ({when} to {e.strftime('%d %b %Y')})")
    return notes


# ── Public API ───────────────────────────────────────────────────────────────

def _strictest(rules: List[str]) -> str:
    return max(rules, key=RULE_STRICTNESS.index) if rules else 'unclear'


def region_intel(region_id: str, live: bool = True, now_utc: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    profile = REGION_MARKETS.get(region_id)
    if not profile:
        return None
    now_utc = now_utc or datetime.now(timezone.utc)
    today = now_utc.date()
    countries = profile['countries']
    codes = [c['code'] for c in countries]

    indicators: Dict[str, Dict[str, Any]] = {}
    holidays: Dict[str, Optional[List[Dict[str, str]]]] = {}
    headlines: List[Dict[str, str]] = []
    if live:
        with ThreadPoolExecutor(max_workers=6) as pool:
            f_ind = pool.submit(fetch_indicators, codes)
            f_news = pool.submit(fetch_headlines, profile['news_terms'])
            f_hol = {c: pool.submit(fetch_holidays, c, today) for c in codes}
            indicators = f_ind.result()
            headlines = f_news.result()
            holidays = {c: f.result() for c, f in f_hol.items()}

    rules = [c['rule'] for c in countries]
    overall = _strictest(rules)
    merged: Dict[tuple, List[str]] = {}
    for c, hs in holidays.items():
        for h in hs or []:
            merged.setdefault((h['date'], h['name']), []).append(c)
    upcoming = [{'date': d, 'name': n, 'country': ', '.join(cs)} for (d, n), cs in sorted(merged.items())]
    return {
        'id': region_id,
        'label': profile['label'],
        'outreach': {
            'rule': overall,
            'label': RULE_LABELS[overall] if len(set(rules)) == 1 else f"Mixed: strictest is \"{RULE_LABELS[overall].lower()}\"",
        },
        'countries': [{
            **{k: c[k] for k in ('code', 'name', 'law', 'rule', 'confidence', 'note')},
            'rule_label': RULE_LABELS[c['rule']],
            'local': _local_status(c, now_utc),
            'indicators': indicators.get(c['code'], {}),
            'holidays_supported': holidays.get(c['code']) is not None if live else None,
        } for c in countries],
        'languages': profile['languages'],
        'currency': profile['currency'],
        'channels': profile['channels'],
        'culture': profile['culture'],
        'sales_cycle': profile['sales_cycle'],
        'fiscal_years': [{
            'label': fy['label'],
            'ends': _next_fiscal_end(fy['month'], fy['day'], today).isoformat(),
            'days_left': (_next_fiscal_end(fy['month'], fy['day'], today) - today).days,
        } for fy in profile['fiscal_years']],
        'timing': _timing(region_id, profile, today),
        'holidays': upcoming[:8],
        'headlines': headlines,
        'live': live,
    }


def market_intel(region_ids: List[str], live: bool = True) -> Dict[str, Any]:
    ids = [r for r in dict.fromkeys(region_ids) if r in REGION_MARKETS][:6]
    now = datetime.now(timezone.utc)
    if live:
        prefetch_indicators(ids)
    with ThreadPoolExecutor(max_workers=4) as pool:
        regions = list(pool.map(lambda r: region_intel(r, live=live, now_utc=now), ids))
    return {
        'regions': [r for r in regions if r],
        'generated_at': now.isoformat(timespec='seconds'),
        'sources': [
            {'name': 'World Bank Indicators API', 'url': 'https://data.worldbank.org/'},
            {'name': 'Nager.Date public holidays', 'url': 'https://date.nager.at/'},
            {'name': 'Google News', 'url': 'https://news.google.com/'},
        ],
        'disclaimer': 'Outreach rules summarise published guidance as of November 2026 and are not legal advice.',
    }


def market_prompt(intel: Optional[Dict[str, Any]]) -> str:
    """Compact market context for persona and report prompts."""
    if not intel or not intel.get('regions'):
        return ''
    lines = ['Live market context (as of ' + intel['generated_at'][:10] + '):']
    for r in intel['regions']:
        lines.append(f"\n[{r['label']}]")
        for c in r['countries']:
            ind = c['indicators']
            stats = ', '.join(
                f"{INDICATORS[k][1].lower()} {v['value']}% ({v['year']})" for k, v in ind.items()
            )
            lines.append(f"- {c['name']}: outreach rule: {c['rule_label'].lower()} ({c['law']})."
                         + (f" Economy: {stats}." if stats else ''))
        lines.append(f"- Buying culture: {r['culture']}")
        lines.append(f"- Channels that work: {', '.join(r['channels'])}. Languages: {', '.join(r['languages'])}.")
        for t in r['timing']:
            lines.append(f"- Timing: {t}")
        if r['holidays']:
            lines.append('- Upcoming holidays: ' + '; '.join(f"{h['date']} {h['name']} ({h['country']})" for h in r['holidays'][:5]))
        if r['headlines']:
            lines.append('- Recent headlines: ' + ' | '.join(h['title'] for h in r['headlines'][:3]))
    return '\n'.join(lines)
