"""Optional public article excerpts; respect robots and never bypass access controls."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import threading
import time
from io import BytesIO
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .news import NewsItem, parse_time, safe_url

USER_AGENT = "InvestmentResearch/0.3"


def public_url(url: str) -> bool:
    url = safe_url(url)
    if not url:
        return False
    host = urlsplit(url).hostname
    if host.lower() == "localhost" or host.lower().endswith((".local", ".localhost")):
        return False
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        return bool(addresses) and all(
            ipaddress.ip_address(row[4][0]).is_global for row in addresses
        )
    except (OSError, ValueError):
        return False


class PublicContent:
    def __init__(self, cancel: threading.Event, sec_contact=""):
        self.cancel = cancel
        self.robots = {}
        self.last_request = {}
        self.delays = {}
        self.sec_contact = sec_contact

    def request(self, url, max_bytes=2 * 1024 * 1024, respect_robots=False):
        for _ in range(5):
            if self.cancel.is_set() or not public_url(url):
                raise RuntimeError("공개 URL을 확인할 수 없습니다.")
            if respect_robots and not self.allowed(url):
                raise RuntimeError("robots.txt 수집 불허")
            host = urlsplit(url).netloc
            delay = self.delays.get(host, 1)
            self.cancel.wait(max(0, delay - (time.monotonic() - self.last_request.get(host, 0))))
            if self.cancel.is_set():
                raise RuntimeError("취소됨")
            self.last_request[host] = time.monotonic()
            user_agent = USER_AGENT
            hostname = (urlsplit(url).hostname or "").lower()
            if hostname == "sec.gov" or hostname.endswith(".sec.gov"):
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.sec_contact):
                    raise RuntimeError("SEC 연락 이메일 설정이 필요합니다.")
                user_agent += " " + self.sec_contact
            with requests.get(
                url,
                headers={"User-Agent": user_agent},
                timeout=(5, 10),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get("Location", ""))
                    continue
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes or self.cancel.is_set():
                        raise RuntimeError("크기 제한 또는 취소")
                    chunks.append(chunk)
                return (
                    response.status_code,
                    response.headers.get("Content-Type", ""),
                    b"".join(chunks),
                    url,
                )
        raise RuntimeError("리다이렉트 한도 초과")

    def allowed(self, url):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            status, _, payload, _ = self.request(origin + "/robots.txt", max_bytes=512000)
            if status == 404:
                self.robots[origin] = True
            elif status == 200:
                parser = RobotFileParser()
                parser.parse(payload.decode("utf-8", "replace").splitlines())
                self.robots[origin] = parser
            else:
                self.robots[origin] = False
        rule = self.robots[origin]
        if not isinstance(rule, bool):
            delay = rule.crawl_delay(USER_AGENT) or rule.crawl_delay("*") or 1
            rate = rule.request_rate(USER_AGENT) or rule.request_rate("*")
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
            self.delays[parts.netloc] = max(1, delay)
            if delay > 30:
                return False  # Skip long waits instead of violating the site's crawl policy.
        return rule if isinstance(rule, bool) else rule.can_fetch(USER_AGENT, url)

    def enrich(self, item: NewsItem) -> NewsItem:
        if item.body_status == "restricted":
            return item
        if not item.url or "news.google.com" == urlsplit(item.url).hostname:
            item.body_status = "link_only"
            return item
        try:
            if not self.allowed(item.url):
                item.body_status = "robots_disallowed"
                return item
            status, content_type, payload, actual_url = self.request(item.url, respect_robots=True)
            if urlsplit(actual_url).netloc != urlsplit(item.url).netloc and not self.allowed(
                actual_url
            ):
                item.body_status = "robots_disallowed"
                return item
            if status != 200:
                item.body_status = f"http_{status}"
                return item
            if "pdf" in content_type.lower():
                from pypdf import PdfReader

                reader = PdfReader(BytesIO(payload))
                item.body = "\n".join(page.extract_text() or "" for page in reader.pages[:15])[
                    :40000
                ]
                item.body_status = "public_excerpt" if item.body else "unavailable"
                return item
            if "html" not in content_type.lower():
                item.body_status = "unsupported_content"
                return item
            soup = BeautifulSoup(payload, "html.parser")
            for node in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(node.string or "{}")
                except (ValueError, TypeError):
                    continue
                objects = data if isinstance(data, list) else [data]
                objects += [
                    child
                    for value in objects
                    if isinstance(value, dict)
                    for child in value.get("@graph", [])
                ]
                for value in objects:
                    if not isinstance(value, dict):
                        continue
                    if value.get("isAccessibleForFree") in (False, "false"):
                        item.body_status = "restricted"
                        return item
                    if "Article" in str(value.get("@type", "")):
                        item.original_published_at = parse_time(value.get("datePublished"))[0]
                        item.original_updated_at = parse_time(value.get("dateModified"))[0]
            article = (
                soup.find(attrs={"itemprop": "articleBody"})
                or soup.find("article")
                or soup.find("main")
            )
            if article:
                for node in article.find_all(["script", "style", "nav", "aside", "footer", "form"]):
                    node.decompose()
                paragraphs = [node.get_text(" ", strip=True) for node in article.find_all("p")]
                item.body = "\n".join(paragraphs)[:40000]
            item.body_status = "public_excerpt" if len(item.body) >= 200 else "unavailable"
            if item.body_status == "unavailable":
                item.body = ""
        except Exception:
            item.body_status = "fetch_failed" if not self.cancel.is_set() else "cancelled"
        return item
