#!/usr/bin/env python3
"""Extrae y muestra los enlaces magnet encontrados en una página web."""

import argparse
import html
import re
import sys
from http.cookiejar import LoadError, MozillaCookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


MAX_PAGE_SIZE = 5 * 1024 * 1024
MAGNET_PATTERN = re.compile(r"magnet:\?[^\"'`<>\s]+", re.IGNORECASE)


def extract_magnets(page_html: str) -> list[str]:
    """Devuelve enlaces magnet únicos, decodificando entidades HTML."""
    magnets = []
    seen = set()

    for match in MAGNET_PATTERN.findall(page_html):
        magnet = html.unescape(match).rstrip("),.;]}")
        if re.match(r"^magnet:\?xt=", magnet, re.IGNORECASE) and magnet not in seen:
            seen.add(magnet)
            magnets.append(magnet)

    return magnets


def fetch_page(url: str, timeout: float = 20, cookie_file: str | None = None) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("La URL debe empezar por http:// o https://")

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
            "Upgrade-Insecure-Requests": "1",
        },
    )

    opener = build_opener()
    if cookie_file:
        cookies = MozillaCookieJar(cookie_file)
        try:
            cookies.load(ignore_discard=True, ignore_expires=True)
        except (OSError, LoadError) as error:
            raise ValueError(f"No se pudo leer el archivo de cookies: {error}") from error
        for cookie in cookies:
            if cookie.expires == 0:
                cookie.expires = None
                cookie.discard = True
        opener.add_handler(HTTPCookieProcessor(cookies))

    with opener.open(request, timeout=timeout) as response:
        page = response.read(MAX_PAGE_SIZE + 1)
        if len(page) > MAX_PAGE_SIZE:
            raise ValueError("La página supera el límite de 5 MB")
        encoding = response.headers.get_content_charset() or "utf-8"
        return page.decode(encoding, errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrae enlaces magnet de una página web o de un HTML guardado."
    )
    parser.add_argument("url", nargs="?", help="URL HTTP o HTTPS de la página")
    parser.add_argument(
        "--html-file", metavar="ARCHIVO", help="extrae los magnets de una copia HTML guardada"
    )
    parser.add_argument(
        "--cookies",
        metavar="COOKIES.TXT",
        help="archivo de cookies exportado en formato Netscape",
    )
    args = parser.parse_args()

    if bool(args.url) == bool(args.html_file):
        parser.error("indica una URL o usa --html-file ARCHIVO")
    if args.cookies and args.html_file:
        parser.error("--cookies solo se puede usar con una URL")

    try:
        if args.html_file:
            page = Path(args.html_file).read_text(encoding="utf-8", errors="replace")
        else:
            page = fetch_page(args.url, cookie_file=args.cookies)
        magnets = extract_magnets(page)
    except HTTPError as error:
        if error.code == 403:
            if args.cookies:
                message = "El servidor sigue rechazando la petición (HTTP 403), incluso con las cookies indicadas."
            else:
                message = (
                    "El servidor rechazó la petición (HTTP 403). Si la página abre en tu navegador, "
                    "prueba con --cookies COOKIES.TXT o guarda la página y usa --html-file ARCHIVO."
                )
            print(f"Error: {message}", file=sys.stderr)
        else:
            print(f"Error: {error}", file=sys.stderr)
        return 1
    except (OSError, URLError, TimeoutError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if not magnets:
        print("No se encontraron enlaces magnet.")
        return 0

    print("\n".join(magnets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
