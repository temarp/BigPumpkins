"""Run with python -m scrapers --help."""
import argparse
import csv
import sys
import time
from collections import deque
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .bigpumpkins import URL, parse_results
from .common import parse_name, write_csv
from .pumpkinfanatic import TOP_URL, detail_url, parse_detail, parse_progeny, parse_top, progeny_url


def session():
    client = requests.Session()
    client.headers.update({"User-Agent": "BigPumpkinsResearch/0.1 (public data; respectful crawl)"})
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def fetch(client, url, delay):
    time.sleep(delay)
    response = client.get(url, timeout=(10, 45))
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def years_arg(value):
    if ":" in value:
        start, end = map(int, value.split(":", 1))
        if start > end:
            raise argparse.ArgumentTypeError("start year exceeds end year")
        return list(range(start, end + 1))
    return [int(value)]


def bigpumpkins(args):
    client = session()
    rows = []
    failures = []
    for year in args.years:
        url = URL.format(year=year)
        try:
            html = Path(args.input_html).read_text(encoding="utf-8") if args.input_html else fetch(client, url, args.delay)
            found = parse_results(html, year, url)
        except (OSError, requests.RequestException, ValueError) as error:
            failures.append((year, str(error)))
            print(f"Failed {year}: {error}", file=sys.stderr)
            continue
        print(f"{year}: {len(found)} pumpkins", file=sys.stderr)
        rows.extend(found)
    write_csv(args.output, rows)
    print(f"Saved {len(rows)} rows to {args.output}; failed years: {len(failures)}")
    error_path = Path(str(args.output) + ".errors.txt")
    if failures:
        error_path.write_text(
            "\n".join(f"{year}\t{error}" for year, error in failures) + "\n", encoding="utf-8"
        )
    else:
        error_path.unlink(missing_ok=True)
    if not rows or failures:
        raise RuntimeError("Some GPC years could not be collected; see errors file")


def pumpkinfanatic(args):
    client = session()
    seeds = list(args.name)
    if args.names_csv:
        with Path(args.names_csv).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or "name" not in reader.fieldnames:
                raise ValueError("Seed CSV needs a 'name' column")
            seeds.extend(row["name"].strip() for row in reader if row["name"].strip())
    if args.top500:
        seeds.extend(parse_top(fetch(client, TOP_URL, args.delay)))
    if not seeds:
        raise ValueError("Specify --name or --top500")
    queue = deque((name, 0) for name in dict.fromkeys(seeds))
    queued = set(seeds)
    records = {}
    failures = []
    while queue and len(records) + len(failures) < args.max_pages:
        name, depth = queue.popleft()
        url = detail_url(name)
        try:
            record = parse_detail(fetch(client, url, args.delay), url)
        except (requests.RequestException, ValueError) as error:
            failures.append((name, str(error)))
            print(f"Failed {name}: {error}", file=sys.stderr)
            continue
        records[record["name"]] = record
        print(f"{len(records)}: {record['name']}", file=sys.stderr)
        if depth >= args.depth:
            continue
        related = [record["mother"], record["father"]]
        if args.progeny:
            try:
                related.extend(child["name"] for child in parse_progeny(fetch(client, progeny_url(name), args.delay)))
            except (requests.RequestException, ValueError) as error:
                print(f"Progeny unavailable for {name}: {error}", file=sys.stderr)
        for candidate in related:
            if candidate and parse_name(candidate)[2] and candidate not in queued:
                queue.append((candidate, depth + 1))
                queued.add(candidate)
    write_csv(args.output, records.values())
    print(f"Saved {len(records)} rows to {args.output}; failed: {len(failures)}")
    error_path = Path(str(args.output) + ".errors.txt")
    if failures:
        error_path.write_text(
            "\n".join(f"{name}\t{error}" for name, error in failures) + "\n", encoding="utf-8"
        )
    else:
        error_path.unlink(missing_ok=True)
    if not records or failures:
        raise RuntimeError("Some PumpkinFanatic cards could not be collected; see errors file")


def main():
    parser = argparse.ArgumentParser(description="Collect public giant pumpkin data into UTF-8 CSV")
    commands = parser.add_subparsers(dest="command", required=True)
    big = commands.add_parser("bigpumpkins", help="GPC results by year")
    big.add_argument("--years", type=years_arg, required=True, help="2025 or 2020:2025")
    big.add_argument("--input-html", help="Parse a saved HTML page; use with one year")
    big.add_argument("--output", default="data/bigpumpkins.csv")
    big.add_argument("--delay", type=float, default=1.0)
    big.set_defaults(run=bigpumpkins)
    fan = commands.add_parser("pumpkinfanatic", help="Pumpkin cards and optionally relatives")
    fan.add_argument("--name", action="append", default=[], help="Seed pumpkin name; repeatable")
    fan.add_argument("--names-csv", help="Seed from a CSV file with a name column")
    fan.add_argument("--top500", action="store_true", help="Seed crawl from public Top 500 list")
    fan.add_argument("--depth", type=int, default=1, help="Generations to follow")
    fan.add_argument("--progeny", action="store_true", help="Also follow offspring")
    fan.add_argument("--max-pages", type=int, default=1000)
    fan.add_argument("--output", default="data/pumpkinfanatic.csv")
    fan.add_argument("--delay", type=float, default=1.0)
    fan.set_defaults(run=pumpkinfanatic)
    args = parser.parse_args()
    if args.command == "bigpumpkins" and args.input_html and len(args.years) != 1:
        parser.error("--input-html requires one year")
    if args.delay < 0 or getattr(args, "depth", 0) < 0 or getattr(args, "max_pages", 1) < 1:
        parser.error("delay/depth must be nonnegative and max-pages positive")
    args.run(args)


if __name__ == "__main__":
    main()
