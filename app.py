import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import re
from collections import deque, defaultdict
import json

# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Website & PDF Link Extractor",
    page_icon="🔗",
    layout="wide"
)

if 'crawling' not in st.session_state:
    st.session_state.crawling = False
if 'results' not in st.session_state:
    st.session_state.results = None

# ═══════════════════════════════════════════════════════════════
# CATEGORY DEFINITIONS
# ═══════════════════════════════════════════════════════════════
CATEGORIES = [
    (
        "⛔ Out of Scope", [
            r"career", r"job", r"faq", r"question",
            r"contact.*us", r"privacy", r"sec.*filing",
            r"term.*of.*use", r"contact", r"cookie",
            r"stock.*price", r"legal.*term", r"term.*condition",
            r"stock.*quote", r"linkedin", r"facebook",
            r"twitter", r"youtube", r"forum", r"chat", r"recipe",
        ]
    ),
    (
        "Presentation", [
            r"investor.*day", r"presentation", r"deck",
            r"slide", r"earnings", r"poster", r"supplemental",
            r"supplementary", r"non.*gaap", r"gaap", r"ifrs",
            r"reconciliation", r"roadshow", r"road.*show",
        ]
    ),
    (
        "Reports", [
            r"letter.*to.*shareholder", r"shareholder.*letter",
            r"letter.*stockholder", r"agm",
            r"annual.*general.*meeting", r"meeting",
            r"extra.*ordinary.*meeting", r"egm",
            r"annual.*report", r"integrated.*report",
            r"yearly.*report", r"interim.*report",
            r"quarterly.*report", r"half.*year.*report",
            r"semi.*annual.*report", r"report",
            r"management.*report", r"management.*commentary",
            r"mda", r"management.*discussion", r"proxy",
            r"proxy.*statement", r"information.*circular",
            r"agm.*notice", r"egm.*notice", r"meeting.*notice",
            r"operating.*metric", r"profit.*loss",
            r"financial.*result", r"operating.*result",
            r"fixed.*income", r"bond", r"debt", r"prospectus",
            r"ipo", r"initial.*public.*offering",
            r"fact.*sheet", r"fact.*book", r"result",
            r"revenue", r"sales", r"profit", r"financial",
            r"snapshot", r"funding", r"fund.*raise",
            r"capital.*raise", r"prescription", r"trial",
        ]
    ),
    (
        "News", [
            r"press.*release", r"news", r"media",
            r"press", r"announcement", r"notices",
        ]
    ),
    (
        "Filings", [
            r"board", r"director", r"reorgani", r"restructur",
            r"agreement", r"material.*contract", r"cancellation",
            r"filing.*change", r"cancel.*notice", r"delisting",
            r"suspension", r"bankruptcy", r"trading.*suspension",
            r"disposal", r"asset.*sale", r"legal.*action",
            r"litigation", r"lawsuit", r"material.*change",
            r"late.*filing", r"regulato.*correspondence",
            r"regulato.*letter", r"exemption",
            r"securities.*registration", r"listing.*application",
            r"withdrawal", r"termination", r"debt.*indenture",
            r"credit.*agreement", r"pre.*ipo",
            r"private.*offering", r"privately.*held",
            r"institutional.*ownership", r"institutional.*holding",
            r"officer.*ownership", r"director.*ownership",
            r"beneficial.*ownership", r"share.*holding.*pattern",
            r"major.*shareholder", r"stock.*option",
            r"employee.*stock", r"esop", r"stock.*split",
            r"reverse.*split", r"tender.*offer",
            r"exchange.*offer", r"rights.*offer", r"rights.*issue",
            r"share.*repurchase", r"buyback",
            r"securities.*purchase", r"corporate.*action",
            r"merger", r"takeover", r"m&a", r"acquisition",
            r"dividend", r"audit", r"fund", r"etf",
            r"prepared.*remark", r"transcript", r"speech",
            r"executive.*commentary", r"ceo.*commentary",
            r"business.*update",
        ]
    ),
    (
        "ESG", [
            r"esg", r"sustainabilit", r"csr",
            r"corporate.*social.*responsibility",
            r"ehs", r"environmental.*health.*safety",
            r"carbon.*disclosure", r"carbon.*report",
            r"cdp.*report", r"green.*report", r"tcfd",
            r"climate", r"social", r"human.*rights",
            r"modern.*slavery", r"diversity", r"dei.*report",
            r"inclusion.*report", r"gri.*report",
            r"global.*reporting.*initiative", r"sasb.*report",
            r"sasb.*index", r"cdp", r"estma", r"policy",
            r"policies", r"charter", r"guideline", r"ethics",
            r"code.*of.*conduct", r"governance", r"sustainable",
        ]
    ),
    (
        "Sector Specific", [
            r"white.*paper", r"case.*stud", r"industry",
            r"insight", r"thought.*leadership", r"product",
            r"brochure", r"one.*pager",
            r"integrated.*resource.*plan", r"resource",
            r"scientific", r"research.*publication",
            r"research", r"blog", r"customer.*stor",
            r"client.*stor", r"success.*stor", r"project",
            r"r&d", r"r.*and.*d", r"rd.*update",
            r"research.*development", r"activity",
            r"infographic", r"catalog", r"safety.*sheet",
            r"data.*sheet", r"launch", r"specification",
            r"clinical.*trial", r"sds.*sheet", r"feature",
            r"service", r"solution", r"model",
        ]
    ),
    (
        "Company Info", [
            r"interview", r"about.*us", r"about",
            r"who.*we.*are", r"our.*company", r"overview",
            r"company.*history", r"history", r"mission",
            r"purpose", r"corporate.*info", r"management",
            r"profile", r"board.*of.*director", r"board.*member",
            r"executive.*team", r"leadership", r"team",
            r"supplier", r"vendor", r"partner", r"alliance",
            r"customer.*list", r"who.*we.*work.*with",
        ]
    ),
]

COMPILED_CATEGORIES = [
    (label, [re.compile(p, re.IGNORECASE) for p in patterns])
    for label, patterns in CATEGORIES
]

# ═══════════════════════════════════════════════════════════════
# EXTERNAL DOMAIN FILTERS
# ═══════════════════════════════════════════════════════════════
JUNK_EXTERNAL_DOMAINS = {
    "doi.org", "dx.doi.org", "ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov", "iopscience.iop.org",
    "link.springer.com", "springer.com", "sciencedirect.com",
    "pubs.acs.org", "pubs.rsc.org", "onlinelibrary.wiley.com",
    "nature.com", "wikipedia.org", "en.wikipedia.org",
    "scitation.aip.org", "opticsinfobase.org",
    "ingentaconnect.com", "mdpi.com", "jove.com",
    "hal.inria.fr", "scripts.iucr.org",
    "nar.oxfordjournals.org", "nass.oxfordjournals.org",
    "uvx.edpsciences.org", "biophysj.org",
    "medcraveonline.com", "readcube.com", "rsc.org",
    "intechopen.com", "photonics.com",
}

EXTERNAL_KEEP_KEYWORDS = [
    "investor", "press", "media", "news",
    "release", "announcement", "publication", "/ir/",
]

SEC_FILING_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"sec\.gov", r"edgar\.sec\.gov",
        r"/sec[-_]filings?", r"sec[-_]filing",
        r"secfiling", r"/edgar/",
    ]
]


# ═══════════════════════════════════════════════════════════════
# CORE HELPERS
# ═══════════════════════════════════════════════════════════════

def categorize_url(url: str) -> str:
    for label, compiled_patterns in COMPILED_CATEGORIES:
        for pattern in compiled_patterns:
            if pattern.search(url):
                return label
    return "❓ Unclassified"


def categorize_all_urls(urls: list) -> dict:
    result = defaultdict(list)
    for url in urls:
        result[categorize_url(url)].append(url)
    return dict(result)


def normalize_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((
        p.scheme, p.netloc.lower(),
        p.path.rstrip("/"),
        p.params, p.query, ""
    ))


def strip_query(url: str) -> str:
    """Return URL with query string and fragment removed."""
    p = urlparse(url)
    return urlunparse((
        p.scheme, p.netloc.lower(),
        p.path.rstrip("/"),
        "", "", ""
    ))


def get_path_depth(url: str) -> int:
    """
    Return the number of non-empty path segments.
    https://example.com/           → 0
    https://example.com/about      → 1
    https://example.com/about/team → 2
    """
    path = urlparse(url).path.strip("/")
    if not path:
        return 0
    return len(path.split("/"))


def is_social_media_url(url: str) -> bool:
    social = [
        "instagram.com", "facebook.com", "linkedin.com",
        "youtube.com", "twitter.com", "x.com", "tiktok.com",
        "snapchat.com", "pinterest.com", "reddit.com",
        "tumblr.com", "whatsapp.com", "telegram.org",
    ]
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(s in domain for s in social)


def is_sec_filing_url(url: str) -> bool:
    for pat in SEC_FILING_PATTERNS:
        if pat.search(url):
            return True
    return False


def _clean_domain(netloc: str) -> str:
    d = netloc.lower().replace("www.", "")
    return d.split(":")[0]


def is_same_domain_or_allowed(url: str, base_domain: str) -> bool:
    parsed    = urlparse(url)
    url_dom   = _clean_domain(parsed.netloc)
    base_clean = _clean_domain(base_domain)

    if url_dom == base_clean or url_dom.endswith("." + base_clean):
        return True
    for junk in JUNK_EXTERNAL_DOMAINS:
        if url_dom == junk or url_dom.endswith("." + junk):
            return False
    if any(kw in url.lower() for kw in EXTERNAL_KEEP_KEYWORDS):
        return True
    return False


def is_investor_or_media_page(url: str) -> bool:
    kws = ["investor", "press", "media", "news",
           "release", "announcement", "publication"]
    return any(k in url.lower() for k in kws)


# ═══════════════════════════════════════════════════════════════
# DEDUPLICATION
#
# The full pipeline:
#
#   Step 1 — Strip query strings
#            page?src=A  +  page?src=B  →  keep one  →  page
#
#   Step 2 — Parent-path suppression
#            If /solutions is in the set, drop /solutions/pageA
#            because /solutions is a shallower ancestor
#
#   Step 3 — Sibling flood detection  ← NEW
#            At each (domain, parent_path) bucket, if the number
#            of direct children exceeds SIBLING_THRESHOLD, keep
#            only the first SIBLING_KEEP of them.
#            This collapses pages like:
#              /webinar_request_fluorescence2021
#              /webinar_request_fluorescence2022
#              /webinar_request_raman2020
#              /webinar_request_raman2026
#            down to a small representative set when there are
#            too many siblings with no shared parent in the list.
#
# SIBLING_THRESHOLD  – how many siblings at one level before
#                      we start collapsing (default 10)
# SIBLING_KEEP       – how many to keep after collapsing (default 3)
# ═══════════════════════════════════════════════════════════════

SIBLING_THRESHOLD = 10   # tune via sidebar slider
SIBLING_KEEP      = 3    # tune via sidebar slider


def deduplicate_urls(urls: list,
                     sibling_threshold: int = SIBLING_THRESHOLD,
                     sibling_keep: int = SIBLING_KEEP) -> list:
    """
    Full deduplication pipeline.

    Step 1 – strip query strings, unique paths only.
    Step 2 – drop any URL whose direct parent path also exists.
    Step 3 – if a (domain, parent_path) bucket has more than
             sibling_threshold children, keep only sibling_keep.
    """

    # ── Step 1: strip queries ─────────────────────────────────
    seen: set   = set()
    clean: list = []
    for url in sorted(urls):          # sort → shorter paths first
        c = strip_query(url)
        if c not in seen:
            seen.add(c)
            clean.append(c)

    # ── Step 2: parent-path suppression ──────────────────────
    # Build lookup of all (scheme, netloc, path) present
    path_set: set = set()
    parsed_cache: dict = {}
    for u in clean:
        p = urlparse(u)
        parsed_cache[u] = p
        path_set.add((p.scheme, p.netloc, p.path.rstrip("/")))

    after_parent_drop: list = []
    for u in clean:
        p     = parsed_cache[u]
        parts = p.path.strip("/").split("/")
        is_child = False

        # Walk up: does any strict ancestor exist in our set?
        for depth in range(len(parts) - 1, 0, -1):
            parent_path = "/" + "/".join(parts[:depth])
            if (p.scheme, p.netloc, parent_path) in path_set:
                is_child = True
                break

        if not is_child:
            after_parent_drop.append(u)

    # ── Step 3: sibling flood detection ──────────────────────
    # Group remaining URLs by (netloc, parent_path)
    # parent_path = everything except the last path segment
    #
    # e.g.  /webinar_request_raman2020  →  parent = ""  (root)
    #       /solutions/pageA            →  parent = "/solutions"
    #
    # If a bucket has > sibling_threshold entries, trim to
    # sibling_keep (alphabetically first = shortest/earliest)

    buckets: dict = defaultdict(list)
    for u in after_parent_drop:
        p      = urlparse(u)
        parts  = p.path.strip("/").split("/")
        # parent segment = all parts except last
        parent = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
        key    = (p.netloc, parent)
        buckets[key].append(u)

    result: list = []
    for key, bucket_urls in buckets.items():
        if len(bucket_urls) > sibling_threshold:
            # Keep only the first sibling_keep entries
            # (list is already sorted from Step 1)
            result.extend(bucket_urls[:sibling_keep])
        else:
            result.extend(bucket_urls)

    # Re-sort for stable output
    result.sort()
    return result


# ═══════════════════════════════════════════════════════════════
# JSON EXTRACTION
# ═══════════════════════════════════════════════════════════════

async def extract_json_links(session, url, pdf_regex):
    json_links: set = set()
    json_pdfs:  set = set()
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                return json_links, json_pdfs
            ct = response.headers.get("Content-Type", "").lower()
            if "application/json" in ct:
                try:
                    data = await response.json()
                    _extract_from_json(
                        data, url, json_links, json_pdfs, pdf_regex
                    )
                except Exception:
                    pass
            else:
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                for script in soup.find_all(
                    "script", type="application/json"
                ):
                    try:
                        if script.string:
                            data = json.loads(script.string)
                            _extract_from_json(
                                data, url, json_links,
                                json_pdfs, pdf_regex
                            )
                    except Exception:
                        pass
    except Exception:
        pass
    return json_links, json_pdfs


def _extract_from_json(data, base_url, links, pdfs, pdf_regex):
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, str) and (
                v.startswith("http") or v.startswith("/")
            ):
                abs_url = normalize_url(urljoin(base_url, v))
                if abs_url.startswith("http"):
                    links.add(abs_url)
                    if pdf_regex.search(abs_url):
                        pdfs.add(abs_url)
            elif isinstance(v, (dict, list)):
                _extract_from_json(v, base_url, links, pdfs, pdf_regex)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str) and (
                item.startswith("http") or item.startswith("/")
            ):
                abs_url = normalize_url(urljoin(base_url, item))
                if abs_url.startswith("http"):
                    links.add(abs_url)
                    if pdf_regex.search(abs_url):
                        pdfs.add(abs_url)
            elif isinstance(item, (dict, list)):
                _extract_from_json(
                    item, base_url, links, pdfs, pdf_regex
                )


# ═══════════════════════════════════════════════════════════════
# MAIN CRAWLER
# ═══════════════════════════════════════════════════════════════

async def crawl_website(
    start_url, pdf_pattern, max_depth,
    max_concurrent, progress_callback,
    sibling_threshold, sibling_keep
):
    try:
        if not start_url.startswith(("http://", "https://")):
            start_url = "https://" + start_url

        start_url   = normalize_url(start_url)
        base_domain = urlparse(start_url).netloc
        pdf_regex   = re.compile(pdf_pattern, re.IGNORECASE)

        excluded = [
            "javascript:", "mailto:", "tel:",
            "sms:", "fax:", "data:", "#",
        ]
        skip_exts = {
            ".jpg", ".jpeg", ".png", ".gif", ".css",
            ".js", ".xml", ".ico", ".svg", ".zip", ".exe",
        }

        visited:         set  = set()
        raw_links:       set  = set()
        raw_pdfs:        set  = set()
        pages_with_pdfs: dict = {}
        json_link_count: int  = 0

        queue     = deque([(start_url, 0)])
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_and_parse(session, url, depth):
            norm = normalize_url(url)
            if norm in visited or depth >= max_depth:
                return []
            visited.add(norm)
            progress_callback(len(visited), len(queue))

            new_urls:  list = []
            page_pdfs: list = []

            async with semaphore:
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status != 200:
                            return []
                        ct = resp.headers.get(
                            "Content-Type", ""
                        ).lower()
                        if "text/html" not in ct:
                            return []

                        html = await resp.text()
                        soup = BeautifulSoup(html, "html.parser")

                        for a in soup.find_all("a", href=True):
                            href = a["href"]
                            if any(
                                href.strip().lower().startswith(ex)
                                for ex in excluded
                            ):
                                continue

                            abs_url = normalize_url(
                                urljoin(url, href)
                            )
                            if is_social_media_url(abs_url):
                                continue
                            if is_sec_filing_url(abs_url):
                                continue

                            parsed = urlparse(abs_url)
                            if parsed.scheme not in ("http", "https"):
                                continue
                            if any(
                                parsed.path.lower().endswith(ext)
                                for ext in skip_exts
                            ):
                                continue
                            if not is_same_domain_or_allowed(
                                abs_url, base_domain
                            ):
                                continue

                            # Always collect raw (for PDF hunting)
                            raw_links.add(abs_url)

                            if pdf_regex.search(abs_url):
                                raw_pdfs.add(abs_url)
                                page_pdfs.append(abs_url)

                            # Follow only same-domain links
                            if (
                                parsed.netloc == base_domain
                                and depth + 1 < max_depth
                                and abs_url not in visited
                            ):
                                new_urls.append((abs_url, depth + 1))

                        # JSON extraction on IR/media pages
                        if is_investor_or_media_page(norm):
                            jlinks, jpdfs = await extract_json_links(
                                session, url, pdf_regex
                            )
                            nonlocal json_link_count
                            json_link_count += len(jlinks)
                            for lnk in jlinks:
                                if (
                                    not is_social_media_url(lnk)
                                    and is_same_domain_or_allowed(
                                        lnk, base_domain
                                    )
                                ):
                                    raw_links.add(lnk)
                            for lnk in jpdfs:
                                if (
                                    not is_social_media_url(lnk)
                                    and is_same_domain_or_allowed(
                                        lnk, base_domain
                                    )
                                ):
                                    raw_pdfs.add(lnk)
                                    page_pdfs.append(lnk)

                        if page_pdfs:
                            pages_with_pdfs[norm] = list(
                                set(page_pdfs)
                            )

                except Exception:
                    pass

            return new_urls

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            )
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            while queue:
                batch = min(max_concurrent, len(queue))
                tasks = []
                for _ in range(batch):
                    if queue:
                        u, d = queue.popleft()
                        tasks.append(fetch_and_parse(session, u, d))
                for new_urls in await asyncio.gather(*tasks):
                    for nu, nd in new_urls:
                        if normalize_url(nu) not in visited:
                            queue.append((nu, nd))

        # ── Deduplication ─────────────────────────────────────
        deduped_links = deduplicate_urls(
            sorted(raw_links), sibling_threshold, sibling_keep
        )
        deduped_pdfs = deduplicate_urls(
            sorted(raw_pdfs), sibling_threshold, sibling_keep
        )

        return {
            "all_links":         deduped_links,
            "pdf_links":         deduped_pdfs,
            "raw_link_count":    len(raw_links),
            "raw_pdf_count":     len(raw_pdfs),
            "pages_with_pdfs":   pages_with_pdfs,
            "pages_crawled":     len(visited),
            "json_links_count":  json_link_count,
            "categorized_links": categorize_all_urls(deduped_links),
            "categorized_pdfs":  categorize_all_urls(deduped_pdfs),
        }

    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# STREAMLIT UI
# ═══════════════════════════════════════════════════════════════

st.title("🔗 Website & PDF Link Extractor")
st.markdown(
    "**Async Deep Crawler — Regex Categories · "
    "Query-Strip · Parent Suppression · Sibling Flood Control**"
)

with st.sidebar:
    st.header("⚙️ Settings")

    url_input = st.text_input(
        "Website URL", value="https://",
        help="Enter the website URL to crawl"
    )
    depth = st.slider(
        "Crawl Depth", min_value=1, max_value=5, value=2,
        help="Subpages are crawled for PDFs but collapsed in output"
    )
    concurrent = st.slider(
        "Concurrent Requests", min_value=5, max_value=50, value=30
    )
    pdf_pattern = st.text_input(
        "PDF Regex Pattern",
        value=r"\.pdf$|/pdf/|download.*pdf|\.PDF$",
    )

    st.markdown("---")
    st.markdown("### 🔁 Deduplication Controls")

    sibling_threshold = st.slider(
        "Sibling Flood Threshold",
        min_value=3, max_value=50, value=10,
        help=(
            "If more than this many sibling URLs share the same "
            "parent path, collapse them down to 'Keep N' below."
        )
    )
    sibling_keep = st.slider(
        "Keep N Siblings (after flood)",
        min_value=1, max_value=10, value=3,
        help="How many siblings to keep when flood is detected."
    )

    st.markdown("---")
    st.markdown("### 📂 Categories")
    for label, patterns in CATEGORIES:
        with st.expander(label):
            for p in patterns:
                st.code(p)

    st.markdown("### Features")
    st.markdown("""
    ✅ Query-string deduplication  
    ✅ Parent-path suppression  
    ✅ Sibling flood detection *(new)*  
    ✅ External domain filtering  
    ✅ SEC filing override  
    ✅ Regex-based categorization  
    ✅ Social media filter  
    ✅ JSON link extraction  
    """)


def sort_key(cat: str) -> int:
    order = {
        "Presentation": 0, "Reports": 1, "News": 2,
        "Filings": 3, "ESG": 4, "Sector Specific": 5,
        "Company Info": 6, "❓ Unclassified": 8,
        "⛔ Out of Scope": 9,
    }
    return order.get(cat, 7)


# ── Main buttons ──────────────────────────────────────────────
col1, col2 = st.columns([3, 1])

with col1:
    if st.button(
        "🚀 Start Crawling", type="primary",
        disabled=st.session_state.crawling
    ):
        if not url_input or url_input == "https://":
            st.error("Please enter a valid URL")
        else:
            try:
                re.compile(pdf_pattern)
            except re.error as e:
                st.error(f"Invalid regex: {e}")
            else:
                st.session_state.crawling = True
                st.session_state.results  = None

                progress_bar = st.progress(0)
                status_text  = st.empty()

                def update_progress(vis, q_len):
                    status_text.text(
                        f"Pages crawled: {vis} | Queue: {q_len}"
                    )

                with st.spinner("Crawling…"):
                    res = asyncio.run(crawl_website(
                        url_input, pdf_pattern,
                        depth, concurrent,
                        update_progress,
                        sibling_threshold, sibling_keep,
                    ))

                st.session_state.results  = res
                st.session_state.crawling = False
                progress_bar.progress(100)
                st.success("✅ Crawl complete!")

with col2:
    if st.button("🗑️ Clear Results"):
        st.session_state.results = None
        st.rerun()

# ── Results ───────────────────────────────────────────────────
if st.session_state.results:
    res = st.session_state.results

    if "error" in res:
        st.error(f"Error: {res['error']}")
    else:
        cat          = res.get("categorized_links", {})
        n_unclass    = len(cat.get("❓ Unclassified", []))
        n_oos        = len(cat.get("⛔ Out of Scope", []))
        n_classified = len(res["all_links"]) - n_unclass - n_oos

        # ── Metrics row ───────────────────────────────────────
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
        c1.metric("Pages Crawled",   res["pages_crawled"])
        c2.metric("Raw Links",       res["raw_link_count"])
        c3.metric("After Dedup",     len(res["all_links"]))
        c4.metric("PDF Links",       len(res["pdf_links"]))
        c5.metric("Raw PDFs",        res["raw_pdf_count"])
        c6.metric("Classified",      n_classified)
        c7.metric("Unclassified",    n_unclass)
        c8.metric("Out of Scope",    n_oos)

        # Show reduction stats
        raw   = res["raw_link_count"]
        dedup = len(res["all_links"])
        if raw > 0:
            pct = round((raw - dedup) / raw * 100, 1)
            st.info(
                f"🔁 Deduplication removed **{raw - dedup}** URLs "
                f"({pct}% reduction) — from {raw} raw → {dedup} unique"
            )

        st.markdown("---")

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📄 All Links",
            "🏷️ Categorized Links",
            "📑 PDF Links",
            "📑 Categorized PDFs",
            "🗂️ Pages with PDFs",
        ])

        with tab1:
            st.subheader(f"All Links ({len(res['all_links'])})")
            for lnk in res["all_links"]:
                st.markdown(f"[{lnk}]({lnk})")
            if res["all_links"]:
                st.download_button(
                    "📥 Download All Links",
                    "\n".join(res["all_links"]),
                    "all_links.txt", "text/plain",
                )

        with tab2:
            st.subheader("🏷️ Links by Category")
            lines = []
            for label in sorted(cat.keys(), key=sort_key):
                urls = cat[label]
                lines += [
                    f"\n{'='*60}",
                    f"{label}  ({len(urls)} URLs)",
                    f"{'='*60}",
                ]
                with st.expander(
                    f"📂 {label} — {len(urls)} URL(s)",
                    expanded=False
                ):
                    for u in urls:
                        st.markdown(f"- [{u}]({u})")
                        lines.append(u)
            st.download_button(
                "📥 Download Categorized",
                "\n".join(lines),
                "categorized_links.txt", "text/plain",
                key="dl_cat",
            )

        with tab3:
            st.subheader(f"PDF Links ({len(res['pdf_links'])})")
            for lnk in res["pdf_links"]:
                st.markdown(f"[{lnk}]({lnk})")
            if res["pdf_links"]:
                st.download_button(
                    "📥 Download PDFs",
                    "\n".join(res["pdf_links"]),
                    "pdf_links.txt", "text/plain",
                )

        with tab4:
            st.subheader("📑 PDFs by Category")
            cpdf      = res.get("categorized_pdfs", {})
            pdf_lines = []
            for label in sorted(cpdf.keys(), key=sort_key):
                urls = cpdf[label]
                pdf_lines += [
                    f"\n{'='*60}",
                    f"{label}  ({len(urls)} PDFs)",
                    f"{'='*60}",
                ]
                with st.expander(
                    f"📂 {label} — {len(urls)} PDF(s)",
                    expanded=False
                ):
                    for u in urls:
                        st.markdown(f"- [{u}]({u})")
                        pdf_lines.append(u)
            if pdf_lines:
                st.download_button(
                    "📥 Download Categorized PDFs",
                    "\n".join(pdf_lines),
                    "categorized_pdfs.txt", "text/plain",
                    key="dl_cat_pdf",
                )

        with tab5:
            st.subheader(
                f"Pages with PDFs ({len(res['pages_with_pdfs'])})"
            )
            for page_url, pdfs in sorted(
                res["pages_with_pdfs"].items()
            ):
                with st.expander(
                    f"📄 {page_url} ({len(pdfs)} PDFs)"
                ):
                    st.markdown(
                        f"**Page:** [{page_url}]({page_url})"
                    )
                    for pdf in pdfs:
                        c = categorize_url(pdf)
                        st.markdown(
                            f"  ↳ [{pdf}]({pdf})  `{c}`"
                        )
