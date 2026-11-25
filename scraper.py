import re
from urllib.parse import urlparse

import requests
import truststore
from bs4 import BeautifulSoup

truststore.inject_into_ssl()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
BASE = "https://www.kitapyurdu.com"
SEARCH_URL = BASE + "/index.php"
TIMEOUT = 5


def search_books(query):
    try:
        response = requests.get(
            SEARCH_URL,
            params={"route": "product/search", "filter_name": query},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None, "site-error"

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for card in soup.select(".ky-product"):
        title_link = card.select_one("a.ky-product-title")
        if not title_link:
            continue
        author_link = card.select_one(".ky-product-author a")
        publisher_link = card.select_one(".ky-product-publisher a")
        cover_link = card.select_one("a.ky-product-cover img")
        results.append({
            "title": title_link.get_text(" ", strip=True),
            "author": author_link.get_text(" ", strip=True) if author_link else "",
            "publisher": publisher_link.get_text(" ", strip=True) if publisher_link else "",
            "cover_url": normalize_url(
                (cover_link.get("src") or cover_link.get("data-src")) if cover_link else ""
            ),
            "url": normalize_url(title_link.get("href", "")),
        })
    return results, "ok"


def get_book_details(url):
    if not is_kitapyurdu_url(url):
        return {}
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    details = {}
    for item in soup.select(".ky-pd-attributes__item"):
        text = item.get_text(" ", strip=True)
        if "Sayfa Sayısı:" in text:
            details["page_count"] = extract_number(text)
        elif "ISBN:" in text:
            details["isbn"] = clean_attribute(text, "ISBN:")
        elif "Yayın Yılı:" in text:
            details["publication_year"] = clean_attribute(text, "Yayın Yılı:")
    return details


def normalize_url(url):
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return url


def is_kitapyurdu_url(url):
    hostname = urlparse(url).hostname or ""
    return hostname == "kitapyurdu.com" or hostname.endswith(".kitapyurdu.com")


def extract_number(text):
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def clean_attribute(text, label):
    return text.replace(label, "", 1).strip()


def download_cover(url, destination):
    if not url or not is_kitapyurdu_url(url):
        return False
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        if "image" not in response.headers.get("Content-Type", ""):
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return True
    except requests.RequestException:
        return False
