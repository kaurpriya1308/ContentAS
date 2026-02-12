import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import re
from collections import deque, defaultdict
import json

# Page config
st.set_page_config(
    page_title="Website & PDF Link Extractor",
    page_icon="🔗",
    layout="wide"
)

# Initialize session state
if 'crawling' not in st.session_state:
    st.session_state.crawling = False
if 'results' not in st.session_state:
    st.session_state.results = None

# ─────────────────────────────────────────────
# CATEGORY DEFINITIONS  (order matters – first match wins)
# Each tuple: (category_name, [keywords_in_url])
# ─────────────────────────────────────────────
CATEGORY_KEYWORDS = [
    # ── Presentations ──
    ("Presentations / Investor Day & Earnings Presentations", [
        "investor-day", "investor_day", "investorday",
        "earnings-presentation", "earnings_presentation",
        "earningspresentation", "investor-presentation",
        "investor_presentation", "investorpresentation",
    ]),
    ("Presentations / Supplementary Information", [
        "supplementary", "supplemental-info", "supplemental_info",
        "supplemental-data", "supplementary-information",
    ]),
    ("Presentations / Non-GAAP Reconciliation / Non-IFRS Measures", [
        "non-gaap", "non_gaap", "nongaap", "non-ifrs", "non_ifrs",
        "nonifrs", "reconciliation",
    ]),
    ("Presentations / ESG & SASB Presentations", [
        "esg-presentation", "esg_presentation",
        "sasb-presentation", "sasb_presentation", "sasb",
    ]),
    ("Presentations / Letter to Shareholders", [
        "letter-to-shareholder", "letter_to_shareholder",
        "shareholder-letter", "shareholder_letter",
        "shareholderletter",
    ]),
    ("Presentations / Roadshow Presentation", [
        "roadshow",
    ]),
    ("Presentations / AGM Presentation", [
        "agm-presentation", "agm_presentation",
        "annual-general-meeting-presentation",
    ]),

    # ── Sector Specific Content ──
    ("Sector Specific / White Paper", [
        "whitepaper", "white-paper", "white_paper",
    ]),
    ("Sector Specific / Case Study", [
        "case-study", "case_study", "casestudy", "customer-story",
        "customer_story", "customerstory",
    ]),
    ("Sector Specific / FactSheets & Factbooks", [
        "factsheet", "fact-sheet", "fact_sheet", "factbook",
        "fact-book", "fact_book", "product-brochure",
        "product_brochure", "brochure","resources",
    ]),
    ("Sector Specific / Prepared Remarks", [
        "prepared-remarks", "prepared_remarks", "preparedremarks",
    ]),
    ("Sector Specific / Speeches", [
        "speech", "speeches",
    ]),
    ("Sector Specific / Follow Up Transcripts", [
        "follow-up-transcript", "follow_up_transcript",
        "followup-transcript", "transcript",
    ]),
    ("Sector Specific / Integrated Resource Plans", [
        "integrated-resource-plan", "integrated_resource_plan",
        "resource-plan", "resource_plan",
    ]),
    ("Sector Specific / Scientific Posters & Presentations", [
        "scientific-poster", "scientific_poster", "poster-presentation",
        "poster_presentation",
    ]),
    ("Sector Specific / Blogs & Insights", [
        "blog", "insights", "viewpoints", "thought-leadership",
        "thought_leadership", "perspectives",
    ]),

    # ── Funds Sheets ──
    ("Funds Sheets", [
        "fund-sheet", "fund_sheet", "fundsheet",
        "fund-report", "fund_report", "fund-prospectus",
        "fund_prospectus", "fund-annual",
    ]),

    # ── Press Releases / News ──
    ("Press Releases / News", [
        "press-release", "press_release", "pressrelease",
        "news-release", "news_release", "newsrelease",
        "newsroom", "news-room", "media-center", "media_center",
        "mediacenter", "press-room", "pressroom",
        "/news/", "/news.", "announcement", "/media/",
    ]),

    # ── Filings / Annual Report ──
    ("Filings / Annual Report & Integrated Report", [
        "annual-report", "annual_report", "annualreport",
        "integrated-report", "integrated_report", "integratedreport",
    ]),
    ("Filings / Interim Report", [
        "interim-report", "interim_report", "interimreport",
        "half-year-report", "half_year_report", "halfyear",
        "quarterly-report", "quarterly_report",
    ]),
    ("Filings / Proxies & Information", [
        "proxy", "proxy-statement", "proxy_statement",
        "agm-notice", "agm_notice", "egm-notice", "egm_notice",
        "board-change", "board_change", "appointment",
        "resignation", "reorgani", "restructur",
        "delisting", "suspension", "bankruptcy",
        "regulatory-correspondence", "regulatory_correspondence",
        "material-change", "material_change",
        "late-filing", "late_filing",
    ]),
    ("Filings / Operating Metrics & Earnings", [
        "operating-metric", "operating_metric", "operatingmetric",
        "earnings", "profit-loss", "profit_loss",
        "financial-result", "financial_result",
    ]),
    ("Filings / Fixed Income & Bond Prospectus", [
        "bond-prospectus", "bond_prospectus", "bondprospectus",
        "fixed-income", "fixed_income", "fixedincome",
        "debt-prospectus", "debt_prospectus",
        "green-bond", "green_bond", "greenbond",
        "municipal-bond", "municipal_bond",
        "bond-offering", "bond_offering",
    ]),
    ("Filings / Prospectus - General", [
        "prospectus",
    ]),
    ("Filings / Prospectus - Equity, M&A, IPO", [
        "ipo-prospectus", "ipo_prospectus",
        "equity-prospectus", "equity_prospectus",
        "ipo", "initial-public-offering",
    ]),
    ("Filings / Ownership", [
        "ownership", "shareholding-pattern", "shareholding_pattern",
        "beneficial-ownership", "beneficial_ownership",
        "institutional-ownership", "institutional_ownership",
        "directors-officers", "directors_officers",
        "major-shareholder", "major_shareholder",
    ]),
    ("Filings / Registrations - Securities", [
        "registration", "listing-application",
        "listing_application", "debt-indenture",
        "debt_indenture", "credit-agreement",
        "credit_agreement", "pre-ipo", "pre_ipo",
        "withdrawal", "termination",
    ]),
    ("Filings / Capital Changes", [
        "stock-option", "stock_option", "stockoption",
        "stock-split", "stock_split", "stocksplit",
        "corporate-action", "corporate_action", "corporateaction",
        "share-repurchase", "share_repurchase", "buyback",
        "rights-offer", "rights_offer",
    ]),
    ("Filings / M&A, Merger, Takeover", [
        "merger", "acquisition", "takeover", "take-over",
        "take_over", "m-and-a", "m_and_a",
    ]),
    ("Filings / Dividends", [
        "dividend",
    ]),
    ("Filings / Auditors Report", [
        "auditor", "audit-report", "audit_report",
        "change-in-auditor", "change_in_auditor",
    ]),

    # ── ESG ──
    ("ESG / Sustainability & CSR Reports", [
        "sustainability", "csr", "corporate-social-responsibility",
        "corporate_social_responsibility",
        "sustainability-report", "sustainability_report",
    ]),
    ("ESG / EHS Reports", [
        "ehs", "environmental-health-safety",
        "environmental_health_safety", "ehs-report", "ehs_report",
    ]),
    ("ESG / Social Reports", [
        "social-report", "social_report", "socialreport",
        "social-responsibility", "social_responsibility",
        "community-engagement", "community_engagement",
    ]),
    ("ESG / GRI Reports", [
        "gri", "global-reporting-initiative",
        "global_reporting_initiative", "gri-report", "gri_report",
    ]),
    ("ESG / Carbon Disclosure Reports", [
        "carbon-disclosure", "carbon_disclosure",
        "carbondisclosure", "cdp", "greenhouse-gas",
        "greenhouse_gas", "ghg", "carbon-footprint",
        "carbon_footprint",
    ]),
    ("ESG / Company Policies & Governance", [
        "governance", "charter", "code-of-ethics",
        "code_of_ethics", "codeofethics", "guidelines",
        "corporate-governance", "corporate_governance",
        "governance-document", "governance_document",
        "policy", "policies",
    ]),
    ("ESG / ESTMA Report", [
        "estma",
    ]),
    ("ESG / Green Report", [
        "green-report", "green_report", "greenreport",
    ]),
    ("ESG / TCFD Report", [
        "tcfd",
    ]),
    ("ESG / ESG Presentations", [
        "esg",
    ]),

    # ── Financial Results & Corporate Actions ──
    ("Results / Earnings / Revenue / Financial Snapshots", [
        "financial-snapshot", "financial_snapshot",
        "quarterly-result", "quarterly_result",
        "revenue", "sales-result", "sales_result",
        "financial-highlight", "financial_highlight",
        "eps", "earnings-per-share", "earnings_per_share",
        "financial-result", "financial_result",
        "funding", "corporate-action", "corporate_action",
    ]),

    # ── About Us / Management ──
    ("About Us / Management Profiles", [
        "about-us", "about_us", "aboutus", "who-we-are",
        "who_we_are", "our-company", "our_company",
        "management", "management-team", "management_team",
        "board-of-director", "board_of_director",
        "executive-team", "executive_team",
        "leadership", "our-team", "our_team",
    ]),
    ("Suppliers / Partners / Customers", [
        "supplier", "partner", "customer-list",
        "customer_list", "our-partner", "our_partner",
        "our-customer", "our_customer", "global-partner",
        "global_partner", "who-we-work-with",
    ]),

    # ── Infographics / Project Updates / R&D ──
    ("Infographics / Project Updates / R&D", [
        "infographic", "project-update", "project_update",
        "business-update", "business_update",
        "r-and-d", "r_and_d", "research-and-development",
        "research_and_development", "innovation",
        "activity-report", "activity_report",
        "rig-count", "rigcount",
    ]),

    # ── Products / Services ──
    ("Products / Features / Services", [
        "product", "service", "solution", "offering",
        "product-launch", "product_launch", "feature",
        "our-product", "our_product", "our-service",
        "our_service", "drilling", "fluid",
    ]),
]

# ── Out of Scope keywords ──
OUT_OF_SCOPE_KEYWORDS = [
    "career", "job", "jobs", "job-posting", "job_posting",
    "faq", "frequently-asked", "frequently_asked",
    "contact-us", "contact_us", "contactus",
    "privacy-policy", "privacy_policy", "privacypolicy",
    "terms-of-use", "terms_of_use", "termsofuse",
    "disclaimer", "cookie-policy", "cookie_policy",
    "stock-price", "stock_price", "stockprice",
    "stock-quote", "stock_quote",
    "dividend-history", "dividend_history",
    "/careers/", "/jobs/", "clinical-trial",
    "clinical_trial", "clinicaltrial","sec-filngs",
    "prescription", "prescribing-information",
    "prescribing_information", "safety-sheet",
    "safety_sheet", "amazon.com", "reddit.com",
]


def categorize_url(url):
    """Categorize a URL based on keyword matching. Returns category name or 'Unclassified'."""
    url_lower = url.lower()

    # Check out-of-scope first
    for kw in OUT_OF_SCOPE_KEYWORDS:
        if kw in url_lower:
            return "⛔ Out of Scope"

    # Try each category
    for category_name, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in url_lower:
                return category_name

    return "❓ Unclassified"


def categorize_all_urls(urls):
    """Categorize a list of URLs. Returns dict of {category: [urls]}."""
    categorized = defaultdict(list)
    for url in urls:
        cat = categorize_url(url)
        categorized[cat].append(url)
    return dict(categorized)


def normalize_url(url):
    """Normalize URL to avoid duplicates"""
    parsed = urlparse(url)
    path = parsed.path.rstrip('/')
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc.lower(),
        path,
        parsed.params,
        parsed.query,
        ''
    ))
    return normalized


def is_social_media_url(url):
    """Check if URL is from social media platforms"""
    social_domains = [
        'instagram.com', 'facebook.com', 'linkedin.com', 'youtube.com',
        'twitter.com', 'x.com', 'tiktok.com', 'snapchat.com', 'pinterest.com',
        'reddit.com', 'tumblr.com', 'whatsapp.com', 'telegram.org'
    ]
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace('www.', '')
    return any(social in domain for social in social_domains)


def is_investor_or_media_page(url):
    """Check if URL likely contains investor or press release information"""
    keywords = ['investor', 'press', 'media', 'news', 'release', 'announcement', 'publication']
    url_lower = url.lower()
    return any(keyword in url_lower for keyword in keywords)


async def extract_json_links(session, url, pdf_regex):
    """Extract links from JSON data on investor/media pages"""
    json_links = set()
    json_pdfs = set()

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return json_links, json_pdfs

            content_type = response.headers.get('Content-Type', '').lower()

            if 'application/json' in content_type:
                try:
                    data = await response.json()
                    extract_urls_from_json(data, url, json_links, json_pdfs, pdf_regex)
                except:
                    pass
            else:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                for script in soup.find_all('script', type='application/json'):
                    try:
                        if script.string:
                            data = json.loads(script.string)
                            extract_urls_from_json(data, url, json_links, json_pdfs, pdf_regex)
                    except:
                        pass
    except:
        pass

    return json_links, json_pdfs


def extract_urls_from_json(data, base_url, links_set, pdfs_set, pdf_regex):
    """Recursively extract URLs from JSON data"""
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and (value.startswith('http') or value.startswith('/')):
                absolute_url = urljoin(base_url, value)
                if absolute_url.startswith('http'):
                    normalized_url = normalize_url(absolute_url)
                    links_set.add(normalized_url)
                    if pdf_regex.search(normalized_url):
                        pdfs_set.add(normalized_url)
            elif isinstance(value, (dict, list)):
                extract_urls_from_json(value, base_url, links_set, pdfs_set, pdf_regex)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str) and (item.startswith('http') or item.startswith('/')):
                absolute_url = urljoin(base_url, item)
                if absolute_url.startswith('http'):
                    normalized_url = normalize_url(absolute_url)
                    links_set.add(normalized_url)
                    if pdf_regex.search(normalized_url):
                        pdfs_set.add(normalized_url)
            elif isinstance(item, (dict, list)):
                extract_urls_from_json(item, base_url, links_set, pdfs_set, pdf_regex)


async def crawl_website(start_url, pdf_pattern, max_depth, max_concurrent, progress_callback):
    """Main crawling function"""
    try:
        if not start_url.startswith(('http://', 'https://')):
            start_url = 'https://' + start_url

        start_url = normalize_url(start_url)
        parsed_start = urlparse(start_url)
        base_domain = parsed_start.netloc

        pdf_regex = re.compile(pdf_pattern, re.IGNORECASE)
        excluded_protocols = ['javascript:', 'mailto:', 'tel:', 'sms:', 'fax:', 'data:', '#']

        visited = set()
        all_links = set()
        pdf_links = set()
        pages_with_pdfs = {}
        json_extracted_links = set()

        queue = deque([(start_url, 0)])
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_and_parse(session, url, depth):
            normalized_url = normalize_url(url)

            if normalized_url in visited or depth >= max_depth:
                return []

            visited.add(normalized_url)
            progress_callback(len(visited), len(queue))

            new_urls = []
            page_pdfs = []

            async with semaphore:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            return []

                        content_type = response.headers.get('Content-Type', '').lower()
                        if 'text/html' not in content_type:
                            return []

                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        for a_tag in soup.find_all('a', href=True):
                            href = a_tag['href']

                            if any(href.strip().lower().startswith(proto) for proto in excluded_protocols):
                                continue

                            absolute_url = urljoin(url, href)
                            normalized_absolute = normalize_url(absolute_url)

                            if is_social_media_url(normalized_absolute):
                                continue

                            parsed = urlparse(normalized_absolute)
                            if parsed.scheme not in ['http', 'https']:
                                continue

                            if any(ext in normalized_absolute.lower() for ext in
                                   ['.jpg', '.png', '.gif', '.css', '.js', '.xml', '.ico', '.svg', '.zip', '.exe']):
                                continue

                            all_links.add(normalized_absolute)

                            if pdf_regex.search(normalized_absolute):
                                pdf_links.add(normalized_absolute)
                                page_pdfs.append(normalized_absolute)

                            if parsed.netloc == base_domain and depth + 1 < max_depth:
                                if normalized_absolute not in visited:
                                    new_urls.append((normalized_absolute, depth + 1))

                        if is_investor_or_media_page(normalized_url):
                            json_links, json_pdfs = await extract_json_links(session, url, pdf_regex)

                            json_links = {link for link in json_links if not is_social_media_url(link)}
                            json_pdfs = {link for link in json_pdfs if not is_social_media_url(link)}

                            json_extracted_links.update(json_links)
                            all_links.update(json_links)
                            pdf_links.update(json_pdfs)
                            page_pdfs.extend(list(json_pdfs))

                        if page_pdfs:
                            pages_with_pdfs[normalized_url] = list(set(page_pdfs))

                except:
                    pass

            return new_urls

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

        async with aiohttp.ClientSession(headers=headers) as session:
            while queue:
                batch_size = min(max_concurrent, len(queue))
                tasks = []

                for _ in range(batch_size):
                    if queue:
                        url, depth = queue.popleft()
                        tasks.append(fetch_and_parse(session, url, depth))

                results = await asyncio.gather(*tasks)

                for new_urls in results:
                    for new_url, new_depth in new_urls:
                        normalized_new = normalize_url(new_url)
                        if normalized_new not in visited:
                            queue.append((normalized_new, new_depth))

        # ── Categorize all links ──
        categorized = categorize_all_urls(sorted(all_links))
        categorized_pdfs = categorize_all_urls(sorted(pdf_links))

        return {
            'all_links': sorted(all_links),
            'pdf_links': sorted(pdf_links),
            'pages_with_pdfs': pages_with_pdfs,
            'pages_crawled': len(visited),
            'json_links_count': len(json_extracted_links),
            'categorized_links': categorized,
            'categorized_pdfs': categorized_pdfs,
        }

    except Exception as e:
        return {'error': str(e)}


# ───────────────────────────────────────────────
# Streamlit UI
# ───────────────────────────────────────────────
st.title("🔗 Website & PDF Link Extractor")
st.markdown("**Async Deep Crawler with URL Categorization, Normalization & Social Media Filtering**")

# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")

    url_input = st.text_input("Website URL", value="https://", help="Enter the website URL to crawl")

    depth = st.slider("Crawl Depth", min_value=1, max_value=5, value=2,
                       help="How many levels deep to crawl (2 recommended)")

    concurrent = st.slider("Concurrent Requests", min_value=5, max_value=50, value=30,
                            help="Higher = faster but more server load")

    pdf_pattern = st.text_input("PDF Regex Pattern",
                                 value=r"\.pdf$|/pdf/|download.*pdf|\.PDF$",
                                 help="Regular expression to detect PDF links")

    st.markdown("---")
    st.markdown("### Features")
    st.markdown("""
    ✅ URL Deduplication  
    ✅ Social Media Filter  
    ✅ JSON Link Extraction  
    ✅ **Keyword-based Categorization**  
    ✅ Clickable Results  
    """)

    st.markdown("---")
    st.markdown("### 📂 Categories Tracked")
    # Show collapsed list of categories
    with st.expander("View all categories"):
        for cat_name, _ in CATEGORY_KEYWORDS:
            st.markdown(f"- {cat_name}")
        st.markdown("- ⛔ Out of Scope")
        st.markdown("- ❓ Unclassified")

# Main content
col1, col2 = st.columns([3, 1])

with col1:
    if st.button("🚀 Start Crawling", type="primary", disabled=st.session_state.crawling):
        if not url_input or url_input == "https://":
            st.error("Please enter a valid URL")
        else:
            try:
                re.compile(pdf_pattern)
            except re.error as e:
                st.error(f"Invalid regex pattern: {str(e)}")
            else:
                st.session_state.crawling = True
                st.session_state.results = None

                progress_bar = st.progress(0)
                status_text = st.empty()

                def update_progress(visited, queue_len):
                    status_text.text(f"Pages crawled: {visited} | Queue: {queue_len}")

                with st.spinner("Crawling website..."):
                    results = asyncio.run(crawl_website(
                        url_input, pdf_pattern, depth, concurrent, update_progress
                    ))

                st.session_state.results = results
                st.session_state.crawling = False
                progress_bar.progress(100)
                st.success("✅ Crawl complete!")

with col2:
    if st.button("🗑️ Clear Results"):
        st.session_state.results = None
        st.rerun()

# ───────────────────────────────────────────────
# Display results
# ───────────────────────────────────────────────
if st.session_state.results:
    results = st.session_state.results

    if 'error' in results:
        st.error(f"Error: {results['error']}")
    else:
        # Summary metrics
        categorized = results.get('categorized_links', {})
        unclassified_count = len(categorized.get("❓ Unclassified", []))
        out_of_scope_count = len(categorized.get("⛔ Out of Scope", []))
        classified_count = len(results['all_links']) - unclassified_count - out_of_scope_count

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Pages Crawled", results['pages_crawled'])
        with col2:
            st.metric("Total Links", len(results['all_links']))
        with col3:
            st.metric("PDF Links", len(results['pdf_links']))
        with col4:
            st.metric("Classified", classified_count)
        with col5:
            st.metric("Unclassified", unclassified_count)
        with col6:
            st.metric("Out of Scope", out_of_scope_count)

        st.markdown("---")

        # Tabs
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📄 All Links",
            "🏷️ Categorized Links",
            "📑 PDF Links",
            "📑 Categorized PDFs",
            "🗂️ Pages with PDFs",
        ])

        # ── Tab 1: All Links (flat) ──
        with tab1:
            st.subheader(f"All Links Found ({len(results['all_links'])})")
            if results['all_links']:
                for link in results['all_links']:
                    st.markdown(f"[{link}]({link})")

                links_text = "\n".join(results['all_links'])
                st.download_button(
                    label="📥 Download All Links",
                    data=links_text,
                    file_name="all_links.txt",
                    mime="text/plain"
                )
            else:
                st.info("No links found")

        # ── Tab 2: Categorized Links ──
        with tab2:
            st.subheader("🏷️ Links Sorted by Category")

            if categorized:
                # Build a downloadable report
                report_lines = []

                # Sort categories: named categories first, then Unclassified, then Out of Scope
                def sort_key(cat_name):
                    if cat_name == "❓ Unclassified":
                        return (1, cat_name)
                    if cat_name == "⛔ Out of Scope":
                        return (2, cat_name)
                    return (0, cat_name)

                sorted_cats = sorted(categorized.keys(), key=sort_key)

                for cat in sorted_cats:
                    urls = categorized[cat]
                    report_lines.append(f"\n{'='*80}")
                    report_lines.append(f"{cat}  ({len(urls)} URLs)")
                    report_lines.append(f"{'='*80}")

                    with st.expander(f"📂 {cat} — {len(urls)} URL(s)", expanded=False):
                        for u in urls:
                            st.markdown(f"- [{u}]({u})")
                            report_lines.append(u)

                report_text = "\n".join(report_lines)
                st.download_button(
                    label="📥 Download Categorized Report",
                    data=report_text,
                    file_name="categorized_links.txt",
                    mime="text/plain",
                    key="dl_cat_links",
                )
            else:
                st.info("No links to categorize")

        # ── Tab 3: PDF Links (flat) ──
        with tab3:
            st.subheader(f"PDF Links ({len(results['pdf_links'])})")
            if results['pdf_links']:
                for link in results['pdf_links']:
                    st.markdown(f"[{link}]({link})")

                pdf_text = "\n".join(results['pdf_links'])
                st.download_button(
                    label="📥 Download PDF Links",
                    data=pdf_text,
                    file_name="pdf_links.txt",
                    mime="text/plain"
                )
            else:
                st.info("No PDF links found")

        # ── Tab 4: Categorized PDFs ──
        with tab4:
            st.subheader("📑 PDF Links Sorted by Category")
            categorized_pdfs = results.get('categorized_pdfs', {})

            if categorized_pdfs:
                pdf_report_lines = []

                sorted_pdf_cats = sorted(categorized_pdfs.keys(), key=sort_key)

                for cat in sorted_pdf_cats:
                    urls = categorized_pdfs[cat]
                    pdf_report_lines.append(f"\n{'='*80}")
                    pdf_report_lines.append(f"{cat}  ({len(urls)} PDFs)")
                    pdf_report_lines.append(f"{'='*80}")

                    with st.expander(f"📂 {cat} — {len(urls)} PDF(s)", expanded=False):
                        for u in urls:
                            st.markdown(f"- [{u}]({u})")
                            pdf_report_lines.append(u)

                pdf_report_text = "\n".join(pdf_report_lines)
                st.download_button(
                    label="📥 Download Categorized PDFs",
                    data=pdf_report_text,
                    file_name="categorized_pdfs.txt",
                    mime="text/plain",
                    key="dl_cat_pdfs",
                )
            else:
                st.info("No PDF links to categorize")

        # ── Tab 5: Pages with PDFs ──
        with tab5:
            st.subheader(f"Pages Containing PDFs ({len(results['pages_with_pdfs'])})")
            if results['pages_with_pdfs']:
                for page_url, pdfs in sorted(results['pages_with_pdfs'].items()):
                    with st.expander(f"📄 {page_url} ({len(pdfs)} PDFs)"):
                        st.markdown(f"**Page:** [{page_url}]({page_url})")
                        st.markdown(f"**Contains {len(pdfs)} PDF(s):**")
                        for pdf in pdfs:
                            cat = categorize_url(pdf)
                            st.markdown(f"  ↳ [{pdf}]({pdf})  `{cat}`")
            else:
                st.info("No pages with PDFs found")
