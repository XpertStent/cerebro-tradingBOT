import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)
from datetime import (
    datetime,
    timedelta,
    timezone
)
from email.utils import parsedate_to_datetime
from pathlib import Path


class NewsEnrichmentService:

    def __init__(
        self,
        cache_dir="/data/news_enrichment",
        ttl_seconds=3600,
        request_timeout=8,
        max_workers=6,
        max_items=10
    ):
        self.cache_dir = Path(
            cache_dir
        )

        self.ttl_seconds = (
            ttl_seconds
        )

        self.request_timeout = (
            request_timeout
        )

        self.max_workers = (
            max_workers
        )

        self.max_items = (
            max_items
        )

        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True
        )

    def _ticker(
        self,
        symbol
    ):
        return (
            str(symbol)
            .upper()
            .split(".")[-1]
        )

    def _cache_path(
        self,
        symbol
    ):
        safe = re.sub(
            r"[^A-Z0-9_-]",
            "_",
            str(symbol).upper()
        )

        return (
            self.cache_dir
            / f"{safe}.json"
        )

    def _signature(
        self,
        *,
        symbol,
        company_name,
        event_dates
    ):
        raw = json.dumps(
            {
                "symbol": symbol,
                "company_name":
                    company_name,
                "event_dates":
                    sorted(
                        event_dates
                        or []
                    ),
            },
            sort_keys=True
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

    def _load_cache(
        self,
        *,
        symbol,
        signature
    ):
        path = self._cache_path(
            symbol
        )

        if not path.exists():
            return None

        try:
            age = (
                time.time()
                - path.stat().st_mtime
            )

            if (
                age
                > self.ttl_seconds
            ):
                return None

            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                data.get(
                    "query_signature"
                )
                != signature
            ):
                return None

            data["cache"] = "HIT"

            return data

        except Exception:
            return None

    def _save_cache(
        self,
        symbol,
        payload
    ):
        path = self._cache_path(
            symbol
        )

        temp = path.with_suffix(
            ".tmp"
        )

        temp.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":")
            ),
            encoding="utf-8"
        )

        temp.replace(
            path
        )

    def _strip_html(
        self,
        value
    ):
        if not value:
            return None

        value = html.unescape(
            str(value)
        )

        value = re.sub(
            r"<[^>]+>",
            " ",
            value
        )

        value = re.sub(
            r"\s+",
            " ",
            value
        ).strip()

        return (
            value[:1000]
            if value
            else None
        )

    def _published_at(
        self,
        value
    ):
        if not value:
            return None

        try:
            dt = (
                parsedate_to_datetime(
                    value
                )
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return (
                dt.astimezone(
                    timezone.utc
                ).isoformat()
            )

        except Exception:
            return str(value)

    def _google_news(
        self,
        query,
        *,
        search_type="RECENT_NEWS"
    ):
        encoded = urllib.parse.quote(
            query
        )

        url = (
            "https://news.google.com/"
            "rss/search"
            f"?q={encoded}"
            "&hl=en-US"
            "&gl=US"
            "&ceid=US:en"
        )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    "Cerebro/1.0 "
                    "market-research"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=self.request_timeout
        ) as response:
            raw = response.read()

        root = ET.fromstring(
            raw
        )

        results = []

        for item in root.findall(
            ".//item"
        ):
            source_node = (
                item.find("source")
            )

            source = (
                source_node.text
                if source_node is not None
                else None
            )

            results.append({
                "source_type":
                    "NEWS",

                "search_type":
                    search_type,

                "source":
                    source,

                "title":
                    self._strip_html(
                        item.findtext(
                            "title"
                        )
                    ),

                "url":
                    item.findtext(
                        "link"
                    ),

                "published_at":
                    self._published_at(
                        item.findtext(
                            "pubDate"
                        )
                    ),

                "summary":
                    self._strip_html(
                        item.findtext(
                            "description"
                        )
                    ),
            })

            if (
                len(results)
                >= self.max_items
            ):
                break

        return results

    def _recent_query(
        self,
        *,
        ticker,
        company_name
    ):
        if company_name:
            return (
                f'"{company_name}" '
                f'{ticker} stock'
            )

        return (
            f'"{ticker}" stock'
        )

    def _event_query(
        self,
        *,
        ticker,
        company_name,
        event_date
    ):
        try:
            day = datetime.fromisoformat(
                str(event_date)
                .split(" ")[0]
            ).date()
        except Exception:
            return None

        start = (
            day
            - timedelta(days=1)
        )

        end = (
            day
            + timedelta(days=2)
        )

        subject = (
            f'"{company_name}" {ticker}'
            if company_name
            else f'"{ticker}" stock'
        )

        return (
            f"{subject} "
            f"after:{start.isoformat()} "
            f"before:{end.isoformat()}"
        )

    def _dedupe(
        self,
        items
    ):
        output = []
        seen = set()

        for item in items:
            key = (
                item.get("url")
                or item.get("title")
            )

            if not key:
                continue

            key = str(
                key
            ).strip()

            if key in seen:
                continue

            seen.add(
                key
            )

            output.append(
                item
            )

        return output

    def get(
        self,
        *,
        symbol,
        company_name=None,
        event_dates=None
    ):
        symbol = str(
            symbol
        ).upper()

        event_dates = [
            str(value)
            for value in (
                event_dates
                or []
            )
            if value
        ]

        signature = self._signature(
            symbol=symbol,
            company_name=company_name,
            event_dates=event_dates
        )

        cached = self._load_cache(
            symbol=symbol,
            signature=signature
        )

        if cached:
            return cached

        ticker = self._ticker(
            symbol
        )

        items = []
        errors = []

        #
        # General recent company news.
        #
        try:
            items.extend(
                self._google_news(
                    self._recent_query(
                        ticker=ticker,
                        company_name=(
                            company_name
                        )
                    ),
                    search_type=(
                        "RECENT_NEWS"
                    )
                )
            )

        except Exception as exc:
            errors.append({
                "source":
                    "GOOGLE_NEWS",

                "search_type":
                    "RECENT_NEWS",

                "error":
                    str(exc),
            })

        #
        # If Cerebro detected an extreme move,
        # search specifically around that date.
        #
        for event_date in (
            event_dates[:3]
        ):
            query = self._event_query(
                ticker=ticker,
                company_name=company_name,
                event_date=event_date
            )

            if not query:
                continue

            try:
                items.extend(
                    self._google_news(
                        query,
                        search_type=(
                            "EVENT_WINDOW"
                        )
                    )
                )

            except Exception as exc:
                errors.append({
                    "source":
                        "GOOGLE_NEWS",

                    "search_type":
                        "EVENT_WINDOW",

                    "event_date":
                        event_date,

                    "error":
                        str(exc),
                })

        items = self._dedupe(
            items
        )

        payload = {
            "symbol":
                symbol,

            "status":
                (
                    "READY"
                    if items
                    else "NO_RESULTS"
                ),

            "fetched_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),

            "cache":
                "MISS",

            "provider":
                "GOOGLE_NEWS_RSS",

            "event_dates":
                event_dates,

            "items":
                items,

            "errors":
                errors,

            "query_signature":
                signature,
        }

        self._save_cache(
            symbol,
            payload
        )

        return payload

    def enrich_many(
        self,
        requests
    ):
        requests = [
            item
            for item in requests
            if item.get("symbol")
        ]

        if not requests:
            return {}

        output = {}

        with ThreadPoolExecutor(
            max_workers=(
                self.max_workers
            )
        ) as executor:

            futures = {
                executor.submit(
                    self.get,
                    symbol=(
                        item["symbol"]
                    ),
                    company_name=(
                        item.get(
                            "company_name"
                        )
                    ),
                    event_dates=(
                        item.get(
                            "event_dates"
                        )
                        or []
                    )
                ):
                item["symbol"]

                for item in requests
            }

            for future in (
                as_completed(
                    futures
                )
            ):
                symbol = (
                    futures[
                        future
                    ]
                )

                try:
                    output[
                        symbol
                    ] = future.result()

                except Exception as exc:
                    output[
                        symbol
                    ] = {
                        "symbol":
                            symbol,

                        "status":
                            "ERROR",

                        "items":
                            [],

                        "errors": [{
                            "error":
                                str(exc)
                        }]
                    }

        return output


news_enrichment = (
    NewsEnrichmentService()
)
