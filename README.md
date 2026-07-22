# Automated Proxy Lists for JDownloader2 and MegaBasterd

Automated pipeline that collects public HTTP, SOCKS4, and SOCKS5 proxy candidates, validates their connectivity, and publishes refreshed proxy lists for JDownloader2 and MegaBasterd.

The GitHub Actions workflow runs every six hours and commits the latest validated output to this repository.

> [!WARNING]
> Public proxies are untrusted infrastructure. Do not use these lists for credentials, personal data, financial activity, or other sensitive traffic. Availability, performance, and anonymity can change without notice. Use them only where permitted by applicable law and the relevant service terms.

## Latest proxy lists

Generated files are committed to [`Output/`](./Output).

| Target | Combined | HTTP | SOCKS4 | SOCKS5 |
| --- | --- | --- | --- | --- |
| JDownloader2 (`.jdproxies`) | [`all`](./Output/jdownloader_proxies_all.jdproxies) | [`http`](./Output/jdownloader_proxies_http.jdproxies) | [`socks4`](./Output/jdownloader_proxies_socks4.jdproxies) | [`socks5`](./Output/jdownloader_proxies_socks5.jdproxies) |
| MegaBasterd (`IP:port`) | [`all`](./Output/megabasterd_proxies_all.txt) | [`http`](./Output/megabasterd_proxies_http.txt) | [`socks4`](./Output/megabasterd_proxies_socks4.txt) | [`socks5`](./Output/megabasterd_proxies_socks5.txt) |

Latest-run metadata:

- [`scraping_summary.txt`](./Output/scraping_summary.txt) — human-readable result summary
- [`scraping_report.json`](./Output/scraping_report.json) — structured metrics and run configuration

## How it works

1. **Collect** — fetches candidates from multiple public sources.
2. **Normalize and deduplicate** — rejects malformed entries and collapses duplicates, prioritizing SOCKS5 when the same endpoint is present under multiple protocols.
3. **Validate** — checks connectivity against a live endpoint and records response times.
4. **Export** — creates combined and protocol-specific lists for both supported applications.
5. **Publish** — GitHub Actions refreshes and commits the output on schedule.

Only proxies that pass the validation step are published. Passing once does not guarantee future availability or compatibility with a particular service.

## Automation

The workflow is defined in [`.github/workflows/complete-proxy-scraper.yml`](./.github/workflows/complete-proxy-scraper.yml).

- **Scheduled:** every six hours
- **Manual runs:** available from the repository's **Actions** tab
- **Options:** `all`, `http`, `socks4`, or `socks5`; optional reduced-source test mode

## Use with JDownloader2

Download the appropriate `.jdproxies` file and import it through JDownloader2's proxy-list configuration. Choose a protocol-specific list when you need to restrict the proxy type, or the combined list when you do not.

## Use with MegaBasterd

Download one of the plain-text `IP:port` files and add its entries through MegaBasterd's proxy configuration. Use a protocol-specific list when your MegaBasterd configuration requires one.

## Run locally

### Requirements

- Python 3.10+
- Network access to the configured source URLs and validation endpoint

```bash
git clone https://github.com/rriordan/Automated-JDownloader2-and-Megabasterd-Proxy-Lists.git
cd Automated-JDownloader2-and-Megabasterd-Proxy-Lists

python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run a full scrape:

```bash
python complete_proxy_scraper.py --proxy-type all
```

Run a single protocol:

```bash
python complete_proxy_scraper.py --proxy-type socks5
```

Run the reduced test source set:

```bash
python complete_proxy_scraper.py --proxy-type all --test-mode
```

Generated files are written to `Output/`.

## Output format

| File pattern | Format | Intended use |
| --- | --- | --- |
| `jdownloader_proxies_*.jdproxies` | JDownloader2 JSON proxy-list structure | JDownloader2 |
| `megabasterd_proxies_*.txt` | One `IP:port` endpoint per line | MegaBasterd |
| `scraping_report.json` | Structured metrics and run configuration | Analysis and automation |
| `scraping_summary.txt` | Human-readable run report | Quick inspection |

## Project status

This repository publishes automatically generated output. Public proxy quality and availability vary continuously; consult the timestamp and validation metrics in the latest report rather than assuming any list will remain valid.

## Attribution and license

This project builds on and was informed by prior work:

- [imwaitingnow/JDownloader2-jdproxies-creator](https://github.com/imwaitingnow/JDownloader2-jdproxies-creator)
- [MuRongPIG/Proxy-Master](https://github.com/MuRongPIG/Proxy-Master)
- [TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List)
- [masterofobzene/JDproxygenerator](https://github.com/masterofobzene/JDproxygenerator)

See [`NOTICE`](./NOTICE) for attribution details and [`LICENSE`](./LICENSE) for license terms.
