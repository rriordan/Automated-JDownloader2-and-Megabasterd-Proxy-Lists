# Proxy Scraper and Validator

This repository contains a script for fetching, validating, and saving proxies in a format compatible with JDownloader2.
It gathers proxies from https://github.com/TheSpeedX/PROXY-List, validates their functionality,
and outputs the valid ones in a structured JSON format for use in JDownloader2

## Features

- Fetch proxies from configurable sources.
- Validate proxies asynchronously for speed and efficiency.
- Save valid proxies in a format suitable for use with JDownloader2.
- Detailed logging for monitoring progress and statistics.

---

## Installation

### Requirements
- Python 3.8 or newer
- `aiohttp`
- `requests`

### Setup

```bash
# Clone the repository
git clone https://github.com/imwaitingnow/JDownloader2-.jdproxies-creator.git
cd proxy-scraper

# Install dependencies
pip install -r requirements.txt

# Alternatively, install manually
pip install aiohttp requests
```
# usage
````bash
# download and validate all proxy lists
proxy_scraper.py 
# or 
proxy_scraper.py --proxy-type all
````
````bash
# download and validate socks5 list
proxy_scraper.py --proxy-type socks5
````
````bash
# download and validate socks4 list
proxy_scraper.py --proxy-type socks4
````
````bash 
#download and validate http list
proxy_scraper.py --proxy-type http
````
# credits
### this script was highly inspired by these GitHub repositories
#### https://github.com/TheSpeedX/PROXY-List
#### https://github.com/masterofobzene/JDproxygenerator
