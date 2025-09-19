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
    # JDownloader2 files
    JD_FILENAME = Path('proxylist.jdproxies')

    # MegaBasterd files
    MB_ALL_FILENAME = Path('megabasterd_proxies_all.txt')
    MB_HTTP_FILENAME = Path('megabasterd_proxies_http.txt')
    MB_SOCKS4_FILENAME = Path('megabasterd_proxies_socks4.txt')
    MB_SOCKS5_FILENAME = Path('megabasterd_proxies_socks5.txt')

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

    def save_jdownloader_proxies(self, proxies: List[ProxyRecord]):
        """Save proxies in JDownloader2 format"""
        valid_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        proxy_stats = defaultdict(lambda: {'count': 0, 'avg_time': 0})
        for proxy in valid_proxies:
            stats = proxy_stats[proxy.proxy.type]
            stats['count'] += 1
            stats['avg_time'] += proxy.response_time

        logger.info("\nJDownloader2 Proxy Statistics:")
        for proxy_type, stats in proxy_stats.items():
            avg_time = stats['avg_time'] / stats['count'] if stats['count'] > 0 else 0
            logger.info(f"{proxy_type}: {stats['count']} proxies (Avg: {avg_time:.2f}s)")

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
                for proxy in valid_proxies
            ]
        }

        with open(ProxyScraperConfig.JD_FILENAME, 'w') as f:
            json.dump(output, f, indent=2)

        logger.info(f"✅ Saved {len(valid_proxies)} proxies to {ProxyScraperConfig.JD_FILENAME}")

    def save_megabasterd_proxies(self, proxies: List[ProxyRecord]):
        """Save proxies in MegaBasterd format (IP:PORT per line)"""
        valid_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        # Group proxies by type for MegaBasterd
        proxies_by_type = defaultdict(list)
        all_proxies = []

        for proxy in valid_proxies:
            proxy_line = f"{proxy.proxy.address}:{proxy.proxy.port}"
            all_proxies.append(proxy_line)

            # Group by original type (convert JD format back to simple format)
            if proxy.proxy.type == "HTTP":
                proxies_by_type['http'].append(proxy_line)
            elif proxy.proxy.type == "SOCKS4":
                proxies_by_type['socks4'].append(proxy_line)
            elif proxy.proxy.type == "SOCKS5":
                proxies_by_type['socks5'].append(proxy_line)

        # Save combined list
        with open(ProxyScraperConfig.MB_ALL_FILENAME, 'w') as f:
            f.write('\n'.join(all_proxies))
        logger.info(f"✅ Saved {len(all_proxies)} proxies to {ProxyScraperConfig.MB_ALL_FILENAME}")

        # Save individual protocol lists
        for proxy_type, proxy_list in proxies_by_type.items():
            if proxy_type == 'http':
                filename = ProxyScraperConfig.MB_HTTP_FILENAME
            elif proxy_type == 'socks4':
                filename = ProxyScraperConfig.MB_SOCKS4_FILENAME
            elif proxy_type == 'socks5':
                filename = ProxyScraperConfig.MB_SOCKS5_FILENAME
            else:
                continue

            with open(filename, 'w') as f:
                f.write('\n'.join(proxy_list))
            logger.info(f"✅ Saved {len(proxy_list)} {proxy_type.upper()} proxies to {filename}")

        logger.info("\nMegaBasterd Proxy Statistics:")
        for proxy_type, proxy_list in proxies_by_type.items():
            logger.info(f"{proxy_type.upper()}: {len(proxy_list)} proxies")

    def save_proxies(self, proxies: List[ProxyRecord]):
        """Save proxies in both JDownloader2 and MegaBasterd formats"""
        logger.info("\n" + "="*60)
        logger.info("SAVING PROXY LISTS")
        logger.info("="*60)

        # Save JDownloader2 format
        self.save_jdownloader_proxies(proxies)

        # Save MegaBasterd format
        self.save_megabasterd_proxies(proxies)

        logger.info("\n" + "="*60)
        logger.info("FILES CREATED:")
        logger.info("="*60)
        logger.info("📁 JDownloader2 Format:")
        logger.info(f"   • {ProxyScraperConfig.JD_FILENAME}")
        logger.info("\n📁 MegaBasterd Format:")
        logger.info(f"   • {ProxyScraperConfig.MB_ALL_FILENAME} (All protocols)")
        logger.info(f"   • {ProxyScraperConfig.MB_HTTP_FILENAME} (HTTP only)")
        logger.info(f"   • {ProxyScraperConfig.MB_SOCKS4_FILENAME} (SOCKS4 only)")
        logger.info(f"   • {ProxyScraperConfig.MB_SOCKS5_FILENAME} (SOCKS5 only)")
        logger.info("="*60)

def parse_arguments():
    parser = argparse.ArgumentParser(description='Enhanced Proxy Generator for JDownloader2 and MegaBasterd')
    parser.add_argument('-type', '--proxy-type',
                        choices=['http', 'socks4', 'socks5', 'all'],
                        default='all',
                        help='Type of proxies to fetch')
    return parser.parse_args()

async def main():
    start_time = time.time()
    args = parse_arguments()

    proxy_types = list(ProxyScraperConfig.ALL_PROXY_SOURCES.keys()) if args.proxy_type == 'all' else [args.proxy_type]

    logger.info("="*60)
    logger.info("ENHANCED PROXY SCRAPER - JDownloader2 + MegaBasterd")
    logger.info("="*60)
    logger.info(f"Fetching {', '.join(proxy_types)} proxies...")

    scraper = ProxyScraper(proxy_types)

    all_proxies = []
    for source in scraper.proxy_sources:
        proxies = scraper.fetch_proxies_from_url(source)
        all_proxies.extend(proxies)

    logger.info(f"Starting validation of {len(all_proxies)} proxies...")
    valid_proxies = await scraper.validate_proxies(all_proxies)

    scraper.save_proxies(valid_proxies)

    total_time = time.time() - start_time
    logger.info(f"\n🎉 Completed in {total_time:.1f} seconds")

if __name__ == "__main__":
    asyncio.run(main())
