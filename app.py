import streamlit as st
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
import re
from collections import deque
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
                            
                            if any(ext in normalized_absolute.lower() for ext in ['.jpg', '.png', '.gif', '.css', '.js', '.xml', '.ico', '.svg', '.zip', '.exe']):
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
        
        return {
            'all_links': sorted(all_links),
            'pdf_links': sorted(pdf_links),
            'pages_with_pdfs': pages_with_pdfs,
            'pages_crawled': len(visited),
            'json_links_count': len(json_extracted_links)
        }
    
    except Exception as e:
        return {'error': str(e)}

# Streamlit UI
st.title("🔗 Website & PDF Link Extractor")
st.markdown("**Async Deep Crawler with URL Normalization & Social Media Filtering**")

# Sidebar for settings
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
    ✅ Clickable Results  
    """)

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
                
                # Progress tracking
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def update_progress(visited, queue):
                    status_text.text(f"Pages crawled: {visited} | Queue: {queue}")
                
                # Run crawler
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

# Display results
if st.session_state.results:
    results = st.session_state.results
    
    if 'error' in results:
        st.error(f"Error: {results['error']}")
    else:
        # Summary
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Pages Crawled", results['pages_crawled'])
        with col2:
            st.metric("Total Links", len(results['all_links']))
        with col3:
            st.metric("PDF Links", len(results['pdf_links']))
        with col4:
            st.metric("JSON Links", results['json_links_count'])
        
        st.markdown("---")
        
        # Tabs for results
        tab1, tab2, tab3 = st.tabs(["📄 All Links", "📑 PDF Links", "🗂️ Pages with PDFs"])
        
        with tab1:
            st.subheader(f"All Links Found ({len(results['all_links'])})")
            if results['all_links']:
                for link in results['all_links']:
                    st.markdown(f"[{link}]({link})")
                
                # Download button
                links_text = "\n".join(results['all_links'])
                st.download_button(
                    label="📥 Download All Links",
                    data=links_text,
                    file_name="all_links.txt",
                    mime="text/plain"
                )
            else:
                st.info("No links found")
        
        with tab2:
            st.subheader(f"PDF Links ({len(results['pdf_links'])})")
            if results['pdf_links']:
                for link in results['pdf_links']:
                    st.markdown(f"[{link}]({link})")
                
                # Download button
                pdf_text = "\n".join(results['pdf_links'])
                st.download_button(
                    label="📥 Download PDF Links",
                    data=pdf_text,
                    file_name="pdf_links.txt",
                    mime="text/plain"
                )
            else:
                st.info("No PDF links found")
        
        with tab3:
            st.subheader(f"Pages Containing PDFs ({len(results['pages_with_pdfs'])})")
            if results['pages_with_pdfs']:
                for page_url, pdfs in sorted(results['pages_with_pdfs'].items()):
                    with st.expander(f"📄 {page_url} ({len(pdfs)} PDFs)"):
                        st.markdown(f"**Page:** [{page_url}]({page_url})")
                        st.markdown(f"**Contains {len(pdfs)} PDF(s):**")
                        for pdf in pdfs:
                            st.markdown(f"  ↳ [{pdf}]({pdf})")
            else:
                st.info("No pages with PDFs found")
