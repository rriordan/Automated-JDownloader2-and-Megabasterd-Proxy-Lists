# Automated Proxy Lists for JDownloader2 and MegaBasterd

Automated pipeline that aggregates free proxy lists from multiple public sources, validates each proxy through a live performance check, and exports sorted, tool-specific output files for use in JDownloader2 and MegaBasterd. Runs on a GitHub Actions schedule every 6 hours so the lists stay current without manual effort.

---

## How it works

1. **Aggregate** — pulls proxy candidates from multiple public sources, covering HTTP, SOCKS4, and SOCKS5 protocols
2. **Validate** — tests each candidate for reachability, response time, and connectivity; drops non-responsive proxies
3. **Export** — writes validated proxies in two formats: JDownloader2-compatible JSON and plain IP:Port text for MegaBasterd

Lists are available combined (all protocols) or split by protocol type.

---

## Output

| Format | Location | Compatible with |
|--------|----------|----------------|
| JSON (structured) | `Output/` | JDownloader2 |
| IP:Port (plain text) | `Output/` | MegaBasterd |
| Per-protocol splits | `Output/` | Both |

---

## Automation

The scraper runs automatically via GitHub Actions on a 6-hour cron schedule. It can also be triggered manually from the Actions tab with options to target a specific protocol type or run in test mode (reduced source set).

**Schedule:** every 6 hours  
**Manual trigger:** supported — select protocol type (all / http / socks4 / socks5)

---

## Credits

This project builds on the work of two excellent repositories:

- **[JDownloader2-jdproxies-creator](https://github.com/imwaitingnow/JDownloader2-jdproxies-creator)** by [imwaitingnow](https://github.com/imwaitingnow)
- **[Proxy-Master](https://github.com/MuRongPIG/Proxy-Master)** by [MuRongPIG](https://github.com/MuRongPIG)

My additions: expanded source list, GitHub Actions workflow for scheduled automation, and output format adjustments for MegaBasterd compatibility.

Additional prior art:
- [TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List)
- [masterofobzene/JDproxygenerator](https://github.com/masterofobzene/JDproxygenerator)
