import csv
import io
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path


class UniverseService:

    NASDAQ_URL = (
        "https://www.nasdaqtrader.com/"
        "dynamic/SymDir/nasdaqlisted.txt"
    )

    OTHER_URL = (
        "https://www.nasdaqtrader.com/"
        "dynamic/SymDir/otherlisted.txt"
    )

    def __init__(
        self,
        data_dir="/data/universe"
    ):
        self.data_dir = Path(data_dir)

        self.data_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        self.nasdaq_file = (
            self.data_dir
            / "nasdaqlisted.txt"
        )

        self.other_file = (
            self.data_dir
            / "otherlisted.txt"
        )

        self.meta_file = (
            self.data_dir
            / "universe_meta.json"
        )

    def refresh(self):
        """
        Download BOTH symbol directories on every run.

        Fresh files replace last-good copies only
        after they pass basic validation.

        If a download fails, use the previous
        last-good copy if available.
        """

        started = time.time()

        sources = {}

        nasdaq_text, nasdaq_status = (
            self._download_with_fallback(
                self.NASDAQ_URL,
                self.nasdaq_file,
                expected_header="Symbol|"
            )
        )

        sources[
            "nasdaqlisted"
        ] = nasdaq_status

        other_text, other_status = (
            self._download_with_fallback(
                self.OTHER_URL,
                self.other_file,
                expected_header="ACT Symbol|"
            )
        )

        sources[
            "otherlisted"
        ] = other_status

        nasdaq_rows = (
            self._parse_pipe(
                nasdaq_text
            )
        )

        other_rows = (
            self._parse_pipe(
                other_text
            )
        )

        eligible = {}
        rejected = {}

        #
        # Nasdaq-listed.
        #
        for row in nasdaq_rows:

            symbol = (
                row.get("Symbol")
                or ""
            ).strip()

            if not symbol:
                continue

            item = {
                "symbol":
                    self._normalize(
                        symbol
                    ),

                "raw_symbol":
                    symbol,

                "name":
                    (
                        row.get(
                            "Security Name"
                        )
                        or ""
                    ).strip(),

                "exchange":
                    "NASDAQ",

                "market_category":
                    (
                        row.get(
                            "Market Category"
                        )
                        or ""
                    ).strip(),

                "financial_status":
                    (
                        row.get(
                            "Financial Status"
                        )
                        or ""
                    ).strip(),

                "test_issue":
                    (
                        row.get(
                            "Test Issue"
                        )
                        or ""
                    ).strip(),

                "etf":
                    (
                        row.get("ETF")
                        or ""
                    ).strip(),
            }

            reason = (
                self._reject_reason(
                    item
                )
            )

            if reason:
                rejected[
                    item["symbol"]
                ] = reason
            else:
                eligible[
                    item["symbol"]
                ] = item

        #
        # NYSE / NYSE American / ARCA /
        # BATS / IEX etc.
        #
        for row in other_rows:

            symbol = (
                row.get("ACT Symbol")
                or row.get("NASDAQ Symbol")
                or ""
            ).strip()

            if not symbol:
                continue

            exchange_code = (
                row.get("Exchange")
                or ""
            ).strip()

            item = {
                "symbol":
                    self._normalize(
                        symbol
                    ),

                "raw_symbol":
                    symbol,

                "name":
                    (
                        row.get(
                            "Security Name"
                        )
                        or ""
                    ).strip(),

                "exchange":
                    exchange_code,

                "test_issue":
                    (
                        row.get(
                            "Test Issue"
                        )
                        or ""
                    ).strip(),

                "etf":
                    (
                        row.get("ETF")
                        or ""
                    ).strip(),

                "financial_status":
                    "N",
            }

            reason = (
                self._reject_reason(
                    item
                )
            )

            if reason:
                rejected[
                    item["symbol"]
                ] = reason
            else:
                eligible[
                    item["symbol"]
                ] = item

        elapsed = round(
            time.time() - started,
            3
        )

        result = {
            "source":
                "NASDAQ_TRADER",

            "sources":
                sources,

            "raw_nasdaq":
                len(nasdaq_rows),

            "raw_other":
                len(other_rows),

            "raw_total":
                (
                    len(nasdaq_rows)
                    + len(other_rows)
                ),

            "eligible_count":
                len(eligible),

            "rejected_count":
                len(rejected),

            "elapsed_seconds":
                elapsed,

            "eligible":
                eligible,

            "rejected":
                rejected,
        }

        self._write_meta(
            {
                "refreshed_at":
                    time.time(),

                "raw_nasdaq":
                    len(nasdaq_rows),

                "raw_other":
                    len(other_rows),

                "eligible_count":
                    len(eligible),

                "rejected_count":
                    len(rejected),

                "sources":
                    sources,
            }
        )

        return result

    def _download_with_fallback(
        self,
        url,
        path,
        expected_header
    ):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        "Cerebro/1.0"
                }
            )

            with urllib.request.urlopen(
                req,
                timeout=20
            ) as response:

                data = response.read()

            text = data.decode(
                "utf-8-sig",
                errors="replace"
            )

            if not text.startswith(
                expected_header
            ):
                raise RuntimeError(
                    "Unexpected symbol "
                    "directory format"
                )

            #
            # Don't replace our last-good file
            # until validation succeeded.
            #
            self._atomic_write(
                path,
                text
            )

            return (
                text,
                {
                    "status":
                        "FRESH",

                    "url":
                        url,

                    "bytes":
                        len(data),
                }
            )

        except Exception as exc:

            if path.exists():

                text = path.read_text(
                    encoding="utf-8",
                    errors="replace"
                )

                return (
                    text,
                    {
                        "status":
                            "STALE_FALLBACK",

                        "url":
                            url,

                        "error":
                            str(exc),
                    }
                )

            raise RuntimeError(
                f"Universe download failed "
                f"and no fallback exists: "
                f"{url}: {exc}"
            )

    def _atomic_write(
        self,
        path,
        text
    ):
        fd, temp_path = (
            tempfile.mkstemp(
                dir=str(
                    self.data_dir
                ),
                prefix=".universe-"
            )
        )

        try:
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8"
            ) as f:
                f.write(text)

            os.replace(
                temp_path,
                path
            )

        finally:
            if os.path.exists(
                temp_path
            ):
                os.unlink(
                    temp_path
                )

    def _parse_pipe(
        self,
        text
    ):
        lines = []

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            if line.startswith(
                "File Creation Time:"
            ):
                continue

            lines.append(
                line
            )

        if not lines:
            return []

        reader = csv.DictReader(
            io.StringIO(
                "\n".join(lines)
            ),
            delimiter="|"
        )

        return [
            dict(row)
            for row in reader
        ]

    def _normalize(
        self,
        symbol
    ):
        symbol = (
            str(symbol)
            .strip()
            .upper()
        )

        #
        # Nasdaq directory class symbols
        # sometimes use $ or other separators.
        #
        # Moomoo generally expects dots for
        # class suffixes, e.g. BRK.B.
        #
        symbol = symbol.replace(
            "$",
            "."
        )

        return (
            symbol
            if symbol.startswith(
                "US."
            )
            else "US." + symbol
        )

    def _reject_reason(
        self,
        item
    ):
        symbol = item[
            "raw_symbol"
        ].upper()

        name = (
            item.get("name")
            or ""
        ).upper()

        #
        # Test instruments.
        #
        if (
            item.get(
                "test_issue"
            ) == "Y"
        ):
            return "TEST_ISSUE"

        #
        # ETFs are not part of the stock
        # candidate universe for now.
        #
        if (
            item.get("etf")
            == "Y"
        ):
            return "ETF"

        #
        # Nasdaq-listed securities with
        # abnormal financial/listing status.
        #
        status = (
            item.get(
                "financial_status"
            )
            or "N"
        ).upper()

        if status not in {
            "",
            "N"
        }:
            return (
                "FINANCIAL_STATUS_"
                + status
            )

        #
        # Obvious non-common-equity instruments.
        #
        blocked_name_terms = {
            "PREFERRED STOCK":
                "PREFERRED",

            "PREFERRED SHARES":
                "PREFERRED",

            "PREFERENCE SHARES":
                "PREFERRED",

            "PFD":
                "PREFERRED",

            "WARRANT":
                "WARRANT",

            "RIGHTS":
                "RIGHT",

            "RIGHT ":
                "RIGHT",

            "UNIT ":
                "UNIT",

            " UNITS":
                "UNIT",

            "BOND":
                "BOND",

            "NOTES DUE":
                "NOTE",

            "SENIOR NOTE":
                "NOTE",

            "SNR NTS":
                "NOTE",

            "DEBENTURE":
                "DEBT",

            "DEPOSITARY PREFERRED":
                "PREFERRED",

            "PERPETUAL PREFERRED":
                "PREFERRED",

            "PERP PREFERRED":
                "PREFERRED",

            "(DELISTED)":
                "DELISTED",

            " DELISTED":
                "DELISTED",
        }

        for term, reason in (
            blocked_name_terms.items()
        ):
            if term in name:
                return reason

        #
        # Clearly special issue suffixes.
        #
        #
        # Do NOT blindly reject .A/.B etc;
        # those are valid common-share classes.
        #
        if symbol.endswith(
            " WS"
        ):
            return "WARRANT"

        return None

    def _write_meta(
        self,
        data
    ):
        self.meta_file.write_text(
            json.dumps(
                data,
                indent=2,
                sort_keys=True
            ),
            encoding="utf-8"
        )


universe_service = UniverseService()
