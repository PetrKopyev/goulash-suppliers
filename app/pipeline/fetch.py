import asyncio
import ipaddress
import re
import socket
import ssl
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx
import idna
from selectolax.lexbor import LexborHTMLParser as HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; GoulashSuppliersBot/0.1; supplier search prototype)"
ROBOT_NAME = "GoulashSuppliersBot"
TIMEOUT = 6.0
MAX_BYTES = 1_500_000
MAX_REDIRECTS = 3
MAX_TEXT = 80_000
PAGES_PER_SITE = 3
ALLOWED_PORTS = (None, 80, 443)
NAT64 = ipaddress.ip_network("64:ff9b::/96")

LINK_KEYWORDS = [
    ("контакт", "contact", "kontakt"),
    ("доставк", "delivery", "dostavk", "оплат", "oplat", "payment"),
    ("прайс", "price", "цены", "опт", "optov"),
    ("сертифик", "документ", "sertifikat", "dokument", "certificate"),
    ("о компании", "о нас", "about", "o-kompanii", "company"),
]
BLOCK_TAGS = r"p|div|li|tr|td|th|h[1-6]|section|article|header|footer|ul|ol|table|dt|dd|address|nav"


@dataclass
class Page:
    url: str
    text: str
    title: str = ""
    site_name: str = ""
    headings: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    tel_links: list[str] = field(default_factory=list)
    mail_links: list[str] = field(default_factory=list)


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    elif ip in NAT64:
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip.is_global and not ip.is_multicast


def is_private_literal(host: str) -> bool:
    try:
        return not is_public_ip(host)
    except ValueError:
        return False


def safe_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        port = parts.port
        host = idna.encode(parts.hostname or "", uts46=True).decode()
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or port not in ALLOWED_PORTS or is_private_literal(host):
        return None
    return parts._replace(netloc=host if port is None else f"{host}:{port}").geturl()


async def resolve_public(host: str, port: int) -> str | None:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    addresses = [info[4][0] for info in infos]
    return addresses[0] if addresses and all(is_public_ip(a) for a in addresses) else None


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        address = await resolve_public(host, port)
        if not address:
            raise httpcore.ConnectError(f"{host} не резолвится в публичный адрес")
        return await self.backend.connect_tcp(address, port, timeout, local_address, socket_options)

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


class PublicOnlyTransport(httpx.AsyncHTTPTransport):
    def __init__(self, tls: ssl.SSLContext, max_connections: int) -> None:
        super().__init__(verify=tls)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=tls, max_connections=max_connections, network_backend=PublicOnlyBackend()
        )


def decode(content: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE) or re.search(
        rb"<meta[^>]+charset=[\"']?([\w-]+)", content[:4096], re.IGNORECASE
    )
    if match:
        charset = match.group(1)
        charset = charset.decode() if isinstance(charset, bytes) else charset
        try:
            return content.decode(charset, errors="replace")
        except LookupError:
            pass
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1251", errors="replace")


async def read_limited(response: httpx.Response) -> bytes:
    chunks, size = [], 0
    async for chunk in response.aiter_raw():
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BYTES:
            break
    return b"".join(chunks)[:MAX_BYTES]


async def get(client: httpx.AsyncClient, url: str, accept_html: bool = True) -> tuple[str, str] | None:
    for _ in range(MAX_REDIRECTS + 1):
        url = safe_url(url)
        if not url:
            return None
        async with client.stream(
            "GET", url, headers={"Accept-Encoding": "identity"}, follow_redirects=False
        ) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            content_type = response.headers.get("content-type", "")
            if (
                response.status_code != 200
                or response.headers.get("content-encoding", "identity") != "identity"
                or (accept_html and "html" not in content_type)
            ):
                return None
            return url, decode(await read_limited(response), content_type)
    return None


def parse_html(url: str, html: str) -> Page:
    html = re.sub(rf"(?i)(</(?:{BLOCK_TAGS})>|<br\s*/?>)", r"\n\1", html)
    tree = HTMLParser(html)
    links, tels, mails = [], [], []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if href.startswith("tel:"):
            tels.append(href[4:])
        elif href.startswith("mailto:"):
            mails.append(href[7:].split("?")[0])
        else:
            links.append((urljoin(url, href), " ".join(a.text().split())))
    title_node = tree.css_first("title")
    title = " ".join(title_node.text().split()) if title_node else ""
    h1s = [" ".join(h.text().split()) for h in tree.css("h1")]
    site_name = tree.css_first('meta[property="og:site_name"]')
    tree.strip_tags(["script", "style", "noscript", "svg", "iframe", "template", "head"])
    body = tree.body.text(separator=" ") if tree.body else ""
    lines = (" ".join(line.split()) for line in body.splitlines())
    text = "\n".join(line for line in lines if line)[:MAX_TEXT]
    return Page(
        url=url,
        text=text,
        title=title,
        site_name=(site_name.attributes.get("content") or "").strip() if site_name else "",
        headings=[h for h in (title, *h1s) if h],
        links=links,
        tel_links=tels,
        mail_links=mails,
    )


def bare_host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def same_site(a: str, b: str) -> bool:
    return bare_host(a) == bare_host(b)


def pick_subpages(page: Page, limit: int) -> list[str]:
    picked: list[str] = []
    for keywords in LINK_KEYWORDS:
        for href, text in page.links:
            haystack = f"{href.lower()} {text.lower()}"
            if (
                same_site(href, page.url)
                and href.split("#")[0] not in picked
                and href.split("#")[0].rstrip("/") != page.url.rstrip("/")
                and any(k in haystack for k in keywords)
            ):
                picked.append(href.split("#")[0])
                break
        if len(picked) >= limit:
            break
    return picked


def rule_matches(rule: str, path: str) -> bool:
    pieces = rule.removesuffix("$").split("*")
    if not rule.endswith("$"):
        pieces.append("")
    if len(pieces) == 1:
        return path == pieces[0]
    head, *middle, tail = pieces
    if not path.startswith(head) or not path.endswith(tail):
        return False
    position, end = len(head), len(path) - len(tail)
    for piece in middle:
        position = path.find(piece, position, end)
        if position < 0:
            return False
        position += len(piece)
    return position <= end


@dataclass
class Robots:
    rules: list[tuple[bool, str]] = field(default_factory=list)

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        matched = [(len(rule), allow) for allow, rule in self.rules if rule_matches(rule, path)]
        return max(matched, default=(0, True))[1]


def parse_robots(text: str) -> Robots:
    groups: dict[str, list[tuple[bool, str]]] = {}
    agents: list[str] = []
    in_rules = False
    for line in text.splitlines():
        key, _, value = line.split("#")[0].partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value.lower())
            for agent in agents:
                groups.setdefault(agent, [])
        elif key in ("allow", "disallow") and agents:
            in_rules = True
            if value:
                for agent in agents:
                    groups[agent].append((key == "allow", value))
    own = next((rules for agent, rules in groups.items() if agent == ROBOT_NAME.lower()), None)
    return Robots(own if own is not None else groups.get("*", []))


async def load_robots(client: httpx.AsyncClient, url: str) -> Robots:
    parts = urlsplit(url)
    try:
        result = await asyncio.wait_for(get(client, f"{parts.scheme}://{parts.netloc}/robots.txt", False), 3)
    except (TimeoutError, httpx.HTTPError, ValueError):
        result = None
    return parse_robots(result[1]) if result else Robots()


async def fetch_site(client: httpx.AsyncClient, url: str, slots: asyncio.Semaphore, pages: list[Page]) -> None:
    async def load(page_url: str) -> Page | None:
        if not robots.allows(page_url):
            return None
        async with slots:
            try:
                result = await asyncio.wait_for(get(client, page_url), TIMEOUT + 2)
            except (TimeoutError, httpx.HTTPError, ValueError):
                return None
        return parse_html(*result) if result else None

    async with slots:
        robots = await load_robots(client, url)
    root = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}/"
    first = await load(url) or (await load(root) if url != root else None)
    if not first:
        return
    pages.append(first)
    for page in await asyncio.gather(*(load(u) for u in pick_subpages(first, PAGES_PER_SITE - 1))):
        if page:
            pages.append(page)
