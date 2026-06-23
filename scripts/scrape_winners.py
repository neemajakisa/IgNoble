"""
scripts/scrape_winners.py

Scrapes the full list of Ig Nobel Prize winners from Wikipedia and
optionally fetches paper abstracts from referenced URLs.

Writes to: data/past_winners.json

Usage:
    python scripts/scrape_winners.py               # scrape winners only
    python scripts/scrape_winners.py --abstracts   # also fetch paper abstracts (slow)

Requirements:
    pip install requests beautifulsoup4
"""
import json
import os
import re
import sys
import time
import requests
import urllib.parse  # Added to help unpack encoded DOI characters
from bs4 import BeautifulSoup, Tag
import re
import requests

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_Ig_Nobel_Prize_winners"
OUTPUT_PATH = "data/past_winners.json"
REQUEST_DELAY = 0.5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_abstract(url: str) -> str | None:
    """
    Extracts DOI, tries Semantic Scholar and Crossref APIs, 
    and falls back to HTML scraping if the APIs lack abstract text.
    """
    decoded_url = urllib.parse.unquote(url)
    
    # 1. Strict DOI extraction
    doi_match = re.search(r'(10\.\d{4,9}/[-._;()/:A-Z0-9]+)', decoded_url, re.IGNORECASE)
    if not doi_match:
        # If it's a standard webpage and not a DOI, skip straight to HTML scraping
        return scrape_html_fallback(url)
        
    doi = doi_match.group(1).strip().rstrip('/')
    
    # --- STRATEGY A: Semantic Scholar API ---
    s2_api_url = f"https://semanticscholar.org:{urllib.parse.quote(doi)}?fields=abstract"
    try:
        response = requests.get(s2_api_url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("abstract"):
                return data["abstract"]
    except Exception:
        pass
        
    # --- STRATEGY B: Crossref API ---
    crossref_url = f"https://crossref.org{urllib.parse.quote(doi)}"
    try:
        response = requests.get(crossref_url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            abstract_text = data.get("message", {}).get("abstract")
            if abstract_text:
                clean_abstract = re.sub(r'<[^>]+>', '', abstract_text)
                return clean_abstract.strip()
    except Exception:
        pass
        
    # --- STRATEGY C: HTML Scraping Fallback (For missing API data) ---
    print(f" ↳ APIs lacked abstract for DOI {doi}. Trying HTML scraping...")
    return scrape_html_fallback(url)


def scrape_html_fallback(url: str) -> str | None:
    """Scrapes common meta tags or paragraph classes where publishers store abstracts."""
    try:
        # Emulate a real browser to avoid getting blocked
        scrape_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=scrape_headers, timeout=15, allow_redirects=True)
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Check standard academic meta tags
        meta_selectors = [
            {"name": "citation_abstract"},
            {"name": "dc.description"},
            {"property": "og:description"}
        ]
        for selector in meta_selectors:
            meta = soup.find("meta", selector)
            if meta and meta.get("content"):
                return meta["content"].strip()
                
        # 2. Check common HTML class names for abstracts
        abstract_box = soup.find(class_=re.compile(r'abstract|abstract-text|content-abstract', re.I))
        if abstract_box:
            return abstract_box.get_text(strip=True)
            
    except Exception:
        pass
    return None

def enrich_with_abstracts(winners: list[dict]) -> list[dict]:
    """Loops through all winners to populate abstract strings via their links."""
    total = sum(1 for w in winners if w.get("paper_links"))
    done = 0
    print(f"\nStarting abstract download sequence for {total} entries...")
    
    for winner in winners:
        links = winner.get("paper_links", [])
        if not links:
            continue
            
        done += 1
        print(f"  [{done}/{total}] Fetching abstract for Year {winner['year']} - {winner['category']}...")
        
        for link in links:
            abstract = fetch_abstract(link)
            if abstract:
                winner["abstract"] = abstract
                print(f"    ✓ Success! Gathered ({len(abstract)} characters)")
                break  # Stop trying links for this entry once an abstract is captured
            time.sleep(REQUEST_DELAY) # Polite throttle cadence control
    return winners

# ── Original Utility Parsing Mechanics ─────────────────────────────────────────
def fetch_page(url: str) -> BeautifulSoup:
    print(f"  Fetching: {url}")
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return BeautifulSoup(response.text, "html.parser")

def clean_text(text: str) -> str:
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"\[citation needed\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def extract_external_links(cell: Tag) -> list[str]:
    links = []
    for a in cell.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "wikipedia.org" not in href:
            links.append(href)
        elif href.startswith("//doi.org") or href.startswith("//www.ncbi"):
            links.append("https:" + href)
    return links

def build_reference_map(soup: BeautifulSoup) -> dict[str, list[str]]:
    ref_map = {}
    all_reference_items = soup.find_all("li", id=re.compile(r"^cite_note-"))
    for li in all_reference_items:
        ref_id = "#" + li["id"]
        links = []
        for a in li.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http") and "wikipedia.org" not in href:
                links.append(href)
            elif href.startswith("//doi.org") or href.startswith("//www.ncbi"):
                links.append("https:" + href)
        ref_map[ref_id] = links
    return ref_map

def parse_all_years(soup: BeautifulSoup) -> list[dict]:
    winners = []
    content = soup.find("div", {"class": "mw-parser-output"})
    if not content:
        content = soup

    ref_map = build_reference_map(soup)
    all_tables = content.find_all("table", class_="wikitable")
    all_lists = content.find_all("ul")

    # 1. Parse Modern Years (Wikitables)
    for table in all_tables:
        prev_heading = table.find_previous(["h2", "h3", "h4"])
        if not prev_heading:
            continue
        year_match = re.search(r"\b(\d{4})\b", prev_heading.get_text())
        if not year_match:
            continue
        year = int(year_match.group(1))

        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        col_category = next((i for i, h in enumerate(headers) if "category" in h), 0)
        col_winner = next((i for i, h in enumerate(headers) if "winner" in h or "recipient" in h), 1)
        col_rationale = next((i for i, h in enumerate(headers) if "rationale" in h or "reason" in h or "citation" in h), 2)

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            cat_cell = cells[col_category] if col_category < len(cells) else None
            win_cell = cells[col_winner] if col_winner < len(cells) else None
            rat_cell = cells[col_rationale] if col_rationale < len(cells) else None

            category = clean_text(cat_cell.get_text()) if cat_cell else "Unknown"
            researchers_text = clean_text(win_cell.get_text()) if win_cell else ""
            rationale = clean_text(rat_cell.get_text()) if rat_cell else ""
            rationale = re.sub(r'^["\u201c]|["\u201d]$', "", rationale.strip())

            paper_links = []
            for cell in cells:
                paper_links.extend(extract_external_links(cell))
                for a in cell.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("#cite_note-") and href in ref_map:
                        paper_links.extend(ref_map[href])

            paper_links = list(dict.fromkeys(paper_links))
            researchers = [
                r.strip() for r in re.split(r",\s*|\s+and\s+", researchers_text)
                if r.strip() and len(r.strip()) > 2
            ]

            if category and (rationale or researchers_text):
                winners.append({
                    "year": year,
                    "category": category,
                    "title": rationale[:200] if rationale else researchers_text[:200],
                    "summary": rationale or researchers_text,
                    "researchers": researchers[:10],
                    "paper_links": paper_links[:3],
                    "abstract": None,
                })

    # 2. Parse Early Prose Years (Unordered Lists)
    for ul in all_lists:
        prev_heading = ul.find_previous(["h2", "h3", "h4"])
        if not prev_heading:
            continue
        year_match = re.search(r"\b(\d{4})\b", prev_heading.get_text())
        if not year_match:
            continue
        year = int(year_match.group(1))
        if year >= 2001:
            continue

        for li in ul.find_all("li", recursive=False):
            li_text = clean_text(li.get_text(separator=" "))
            if not li_text or ":" not in li_text:
                continue
            cat_match = re.match(r"^([A-Za-z /&]+?):\s*(.+)", li_text, re.DOTALL)
            if cat_match:
                category = cat_match.group(1).strip()
                summary = cat_match.group(2).strip()
            else:
                continue

            if any(w["year"] == year and w["category"] == category and w["summary"][:50] == summary[:50] for w in winners):
                continue

            winners.append({
                "year": year,
                "category": category,
                "title": summary[:200],
                "summary": summary,
                "researchers": [],
                "paper_links": extract_external_links(li)[:3],
                "abstract": None,
            })
    return winners

# ── Controller & Main Logic Pipeline ──────────────────────────────────────────
def scrape(fetch_abstracts: bool = False) -> list[dict]:
    print("Initializing Scraper...")
    print(f"Fetching Wikipedia page...")
    soup = fetch_page(WIKIPEDIA_URL)

    print("Parsing Ig Nobel page sections dynamically...")
    all_winners = parse_all_years(soup)

    if not all_winners:
        print("\n❌ Error: No elements were matched. Check page structure.")
        return []

    all_winners.sort(key=lambda w: (w["year"], w["category"]))

    print(f"\nTotal winners scraped: {len(all_winners)}")
    print(f"Years covered: {all_winners[0]['year']} – {all_winners[-1]['year']}")

    # Added abstract enrichment phase control step
    if fetch_abstracts:
        all_winners = enrich_with_abstracts(all_winners)

    return all_winners

if __name__ == "__main__":
    # Toggle this to True if you want to turn on the slow abstract lookup download pass.
    # Set to False to just grab the basic fields instantly.
    RUN_ABSTRACT_LOOKUPS = True

    winners = scrape(fetch_abstracts=RUN_ABSTRACT_LOOKUPS)
    
    if winners:
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        output = {"winners": winners}
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Saved {len(winners)} winners to {OUTPUT_PATH}")

        print("\nSample entries:")
        for w in winners[:3]:
            print(f"  {w['year']} [{w['category']}] {w['title'][:60]}...")
