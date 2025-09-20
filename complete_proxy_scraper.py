import requests
import json
import random
import asyncio
import aiohttp
import time
import argparse
from typing import List, Dict, Optional, Set, Tuple
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

@dataclass
class ProxyPreferences:
    address: str
    port: int
    type: str
    username: Optional[str] = None
    password: Optional[str] = None
    preferNativeImplementation: bool = False
    resolveHostName: bool = False
    connectMethodPreferred: bool = False
    response_time: float = 0.0

@dataclass
class ProxyRecord:
    proxy: ProxyPreferences
    rangeRequestsSupported: bool = True
    filter: Optional[str] = None
    pac: bool = False
    reconnectSupported: bool = False
    enabled: bool = True
    response_time: float = 0.0

class ProxyScraperConfig:
    # Output directory
    OUTPUT_DIR = Path('Output')

    # JDownloader2 files (4 files total)
    JD_COMBINED_FILENAME = OUTPUT_DIR / 'jdownloader_proxies_all.jdproxies'
    JD_HTTP_FILENAME = OUTPUT_DIR / 'jdownloader_proxies_http.jdproxies'
    JD_SOCKS4_FILENAME = OUTPUT_DIR / 'jdownloader_proxies_socks4.jdproxies'
    JD_SOCKS5_FILENAME = OUTPUT_DIR / 'jdownloader_proxies_socks5.jdproxies'

    # MegaBasterd files (4 files total)
    MB_COMBINED_FILENAME = OUTPUT_DIR / 'megabasterd_proxies_all.txt'
    MB_HTTP_FILENAME = OUTPUT_DIR / 'megabasterd_proxies_http.txt'
    MB_SOCKS4_FILENAME = OUTPUT_DIR / 'megabasterd_proxies_socks4.txt'
    MB_SOCKS5_FILENAME = OUTPUT_DIR / 'megabasterd_proxies_socks5.txt'

    TEST_URL = "http://httpbin.org/ip"  # Single fast endpoint
    TIMEOUT = 3  # Reduced timeout
    BATCH_SIZE = 500  # Increased batch size
    MAX_CONCURRENT_TASKS = 2000  # Increased concurrent tasks
    MAX_RESPONSE_TIME = 3  # Reduced max response time

    # Map proxy types to JDownloader2 format
    PROXY_TYPE_MAP = {
        "http": "HTTP",
        "https": "HTTPS",
        "socks4": "SOCKS4",
        "socks5": "SOCKS5"
    }

    ALL_PROXY_SOURCES = {
        "socks5": {
            "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            "type": "socks5"
        },
        "socks4": {
            "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
            "type": "socks4"
        },
        "http": {
            "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            "type": "http"
        }
    }

    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    ]

class ProxyScraper:
    def __init__(self, proxy_types: List[str]):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': ProxyScraperConfig.USER_AGENTS[0]
        })
        self.valid_proxies: Set[str] = set()
        self.proxy_types = proxy_types
        self.semaphore = asyncio.Semaphore(ProxyScraperConfig.MAX_CONCURRENT_TASKS)

        # Create output directory if it doesn't exist
        ProxyScraperConfig.OUTPUT_DIR.mkdir(exist_ok=True)
        logger.info(f"📁 Created output directory: {ProxyScraperConfig.OUTPUT_DIR}")

    @property
    def proxy_sources(self) -> List[Dict]:
        return [
            source for proxy_type in self.proxy_types
            if (source := ProxyScraperConfig.ALL_PROXY_SOURCES.get(proxy_type.lower()))
        ]

    def _create_proxy_record(self, address: str, port: int, proxy_type: str) -> ProxyRecord:
        jd_proxy_type = ProxyScraperConfig.PROXY_TYPE_MAP.get(proxy_type.lower(), "NONE")

        preferences = ProxyPreferences(
            address=address,
            port=port,
            type=jd_proxy_type,
            response_time=0.0
        )

        return ProxyRecord(proxy=preferences, response_time=0.0)

    async def _test_proxy(self, proxy_url: str, session: aiohttp.ClientSession) -> Tuple[bool, float]:
        try:
            start_time = time.time()
            async with session.get(
                    ProxyScraperConfig.TEST_URL,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=ProxyScraperConfig.TIMEOUT),
                    ssl=False
            ) as response:
                if response.status == 200:
                    await response.read()
                    response_time = time.time() - start_time
                    return True, response_time
        except:
            pass
        return False, 0

    async def _validate_proxy(self, proxy: ProxyRecord, session: aiohttp.ClientSession) -> Optional[ProxyRecord]:
        async with self.semaphore:  # Control concurrent connections
            proxy_type = proxy.proxy.type.lower()
            proxy_url = f"{proxy_type}://{proxy.proxy.address}:{proxy.proxy.port}"
            proxy_key = f"{proxy.proxy.address}:{proxy.proxy.port}"

            if proxy_key in self.valid_proxies:
                return None

            success, response_time = await self._test_proxy(proxy_url, session)

            if success and response_time <= ProxyScraperConfig.MAX_RESPONSE_TIME:
                self.valid_proxies.add(proxy_key)
                proxy.response_time = response_time
                proxy.proxy.response_time = response_time
                return proxy

            return None

    async def validate_proxies(self, proxies: List[ProxyRecord]) -> List[ProxyRecord]:
        connector = aiohttp.TCPConnector(
            limit=0,  # No limit
            ttl_dns_cache=300,
            ssl=False,
            use_dns_cache=True
        )

        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [self._validate_proxy(proxy, session) for proxy in proxies]
            valid_proxies = []

            for i in range(0, len(tasks), ProxyScraperConfig.BATCH_SIZE):
                batch = tasks[i:i + ProxyScraperConfig.BATCH_SIZE]
                results = await asyncio.gather(*batch, return_exceptions=True)

                valid_batch = [r for r in results if r is not None and not isinstance(r, Exception)]
                valid_proxies.extend(valid_batch)

                progress = min(100, (i + len(batch)) / len(tasks) * 100)
                avg_time = sum(p.response_time for p in valid_proxies) / len(valid_proxies) if valid_proxies else 0
                logger.info(f"Progress: {progress:.1f}% - Valid: {len(valid_proxies)} - Avg Time: {avg_time:.2f}s")

            return sorted(valid_proxies, key=lambda x: x.response_time)

    def fetch_proxies_from_url(self, source: Dict) -> List[ProxyRecord]:
        try:
            response = self.session.get(source['url'], timeout=ProxyScraperConfig.TIMEOUT)
            response.raise_for_status()

            seen_proxies = set()
            proxy_list = []

            for line in response.text.splitlines():
                if not line.strip() or line.startswith('#'):
                    continue

                try:
                    address, port = line.strip().split(':')
                    proxy_key = f"{address}:{port}"

                    if proxy_key not in seen_proxies:
                        seen_proxies.add(proxy_key)
                        proxy_list.append(self._create_proxy_record(
                            address=address,
                            port=int(port),
                            proxy_type=source['type']
                        ))
                except:
                    continue

            logger.info(f"Fetched {len(proxy_list)} {source['type']} proxies")
            return proxy_list
        except Exception as e:
            logger.error(f"Error fetching proxies: {e}")
            return []

    def _save_jdownloader_file(self, proxies: List[ProxyRecord], filename: Path, proxy_type_filter: str = None):
        """Save proxies in JDownloader2 format with optional type filtering"""
        if proxy_type_filter:
            # Filter for specific proxy type
            filtered_proxies = [p for p in proxies if p.proxy.type.upper() == proxy_type_filter.upper()]
        else:
            # All proxies
            filtered_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not filtered_proxies:
            logger.warning(f"No {proxy_type_filter or 'valid'} proxies to save to {filename}")
            return

        output = {
            "customProxyList": [
                {
                    "proxy": asdict(proxy.proxy),
                    "rangeRequestsSupported": proxy.rangeRequestsSupported,
                    "filter": proxy.filter,
                    "pac": proxy.pac,
                    "reconnectSupported": proxy.reconnectSupported,
                    "enabled": proxy.enabled,
                    "response_time": proxy.response_time
                }
                for proxy in filtered_proxies
            ]
        }

        with open(filename, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"✅ Saved {len(filtered_proxies)} {proxy_type_filter or 'total'} proxies to {filename}")

    def _save_megabasterd_file(self, proxies: List[ProxyRecord], filename: Path, proxy_type_filter: str = None):
        """Save proxies in MegaBasterd format with optional type filtering"""
        if proxy_type_filter:
            # Filter for specific proxy type
            filtered_proxies = [p for p in proxies if p.proxy.type.upper() == proxy_type_filter.upper()]
        else:
            # All proxies
            filtered_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not filtered_proxies:
            logger.warning(f"No {proxy_type_filter or 'valid'} proxies to save to {filename}")
            return

        proxy_lines = []
        for proxy in filtered_proxies:
            proxy_line = f"{proxy.proxy.address}:{proxy.proxy.port}"
            proxy_lines.append(proxy_line)

        with open(filename, 'w') as f:
            f.write('\n'.join(proxy_lines))

        logger.info(f"✅ Saved {len(filtered_proxies)} {proxy_type_filter or 'total'} proxies to {filename}")

    def save_all_proxy_files(self, proxies: List[ProxyRecord]):
        """Save proxies in both JDownloader2 and MegaBasterd formats (8 files total)"""
        valid_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not valid_proxies:
            logger.error("No valid proxies to save!")
            return

        logger.info("\n" + "="*80)
        logger.info("SAVING ALL PROXY FILES TO OUTPUT FOLDER")
        logger.info("="*80)

        # Count proxies by type
        type_stats = defaultdict(int)
        for proxy in valid_proxies:
            type_stats[proxy.proxy.type] += 1

        logger.info("\n📊 Proxy Statistics:")
        total_count = 0
        for proxy_type, count in sorted(type_stats.items()):
            logger.info(f"   • {proxy_type}: {count} proxies")
            total_count += count
        logger.info(f"   • TOTAL: {total_count} proxies")

        # Save JDownloader2 files (4 files)
        logger.info("\n📁 Saving JDownloader2 Files:")
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_COMBINED_FILENAME)
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_HTTP_FILENAME, "HTTP")
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_SOCKS4_FILENAME, "SOCKS4")
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_SOCKS5_FILENAME, "SOCKS5")

        # Save MegaBasterd files (4 files)
        logger.info("\n📁 Saving MegaBasterd Files:")
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_COMBINED_FILENAME)
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_HTTP_FILENAME, "HTTP")
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_SOCKS4_FILENAME, "SOCKS4")
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_SOCKS5_FILENAME, "SOCKS5")

        logger.info("\n" + "="*80)
        logger.info("📁 ALL FILES SAVED TO: Output/")
        logger.info("="*80)
        logger.info("🎯 JDownloader2 Files (4 total):")
        logger.info(f"   • {ProxyScraperConfig.JD_COMBINED_FILENAME.name} (All protocols)")
        logger.info(f"   • {ProxyScraperConfig.JD_HTTP_FILENAME.name} (HTTP only)")
        logger.info(f"   • {ProxyScraperConfig.JD_SOCKS4_FILENAME.name} (SOCKS4 only)")
        logger.info(f"   • {ProxyScraperConfig.JD_SOCKS5_FILENAME.name} (SOCKS5 only)")

        logger.info("\n🎯 MegaBasterd Files (4 total):")
        logger.info(f"   • {ProxyScraperConfig.MB_COMBINED_FILENAME.name} (All protocols)")
        logger.info(f"   • {ProxyScraperConfig.MB_HTTP_FILENAME.name} (HTTP only)")
        logger.info(f"   • {ProxyScraperConfig.MB_SOCKS4_FILENAME.name} (SOCKS4 only)")
        logger.info(f"   • {ProxyScraperConfig.MB_SOCKS5_FILENAME.name} (SOCKS5 only)")
        logger.info("="*80)

def parse_arguments():
    parser = argparse.ArgumentParser(description='Complete Proxy Generator for JDownloader2 and MegaBasterd')
    parser.add_argument('-type', '--proxy-type',
                        choices=['http', 'socks4', 'socks5', 'all'],
                        default='all',
                        help='Type of proxies to fetch')
    return parser.parse_args()

async def main():
    start_time = time.time()
    args = parse_arguments()

    proxy_types = list(ProxyScraperConfig.ALL_PROXY_SOURCES.keys()) if args.proxy_type == 'all' else [args.proxy_type]

    logger.info("="*80)
    logger.info("COMPLETE PROXY SCRAPER - 8 FILES OUTPUT")
    logger.info("="*80)
    logger.info(f"🎯 Target: {', '.join(proxy_types)} proxies")
    logger.info(f"📁 Output folder: {ProxyScraperConfig.OUTPUT_DIR}")
    logger.info(f"📊 Total files to create: 8 (4 JDownloader2 + 4 MegaBasterd)")

    scraper = ProxyScraper(proxy_types)

    all_proxies = []
    for source in scraper.proxy_sources:
        proxies = scraper.fetch_proxies_from_url(source)
        all_proxies.extend(proxies)

    logger.info(f"🚀 Starting validation of {len(all_proxies)} proxies...")
    valid_proxies = await scraper.validate_proxies(all_proxies)

    scraper.save_all_proxy_files(valid_proxies)

    total_time = time.time() - start_time
    logger.info(f"\n🎉 Process completed in {total_time:.1f} seconds")
    logger.info(f"📁 Check the 'Output' folder for all 8 proxy files!")

if __name__ == "__main__":
    asyncio.run(main())
