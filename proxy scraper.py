import requests
import json
import random
import asyncio
import aiohttp
import time
from typing import List, Dict, Optional, Set
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

@dataclass
class ProxyRecord:
    proxy: ProxyPreferences
    rangeRequestsSupported: bool = True
    filter: Optional[str] = None
    pac: bool = False
    reconnectSupported: bool = False
    enabled: bool = True

class ProxyScraperConfig:
    FILENAME = Path('proxylist.jdproxies')
    TEST_URL = "http://httpbin.org/ip"
    TIMEOUT = 5
    BATCH_SIZE = 100
    MAX_CONCURRENT_TASKS = 1000

    # Map proxy types to JDownloader2 format
    PROXY_TYPE_MAP = {
        "http": "HTTP",
        "https": "HTTPS",
        "socks4": "SOCKS4",
        "socks5": "SOCKS5"
    }

    PROXY_SOURCES = [
        {
            "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            "type": "socks5"
        },
        {
            "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
            "type": "socks4"
        },
        {
            "url": "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            "type": "http"
        }
    ]

    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    ]

class ProxyScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(ProxyScraperConfig.USER_AGENTS)
        })
        self.valid_proxies: Set[str] = set()

    def _create_proxy_record(self, address: str, port: int, proxy_type: str) -> ProxyRecord:
        # Convert proxy type to JDownloader2 format
        jd_proxy_type = ProxyScraperConfig.PROXY_TYPE_MAP.get(proxy_type.lower(), "NONE")
        
        preferences = ProxyPreferences(
            address=address,
            port=port,
            type=jd_proxy_type,  # Use mapped proxy type
            username=None,
            password=None,
            preferNativeImplementation=False,
            resolveHostName=False,
            connectMethodPreferred=False
        )
        return ProxyRecord(
            proxy=preferences,
            rangeRequestsSupported=True,
            filter=None,
            pac=False,
            reconnectSupported=False,
            enabled=True
        )

    async def _validate_proxy(self, proxy: ProxyRecord, session: aiohttp.ClientSession) -> Optional[ProxyRecord]:
        # Use lowercase proxy type for validation
        proxy_type = proxy.proxy.type.lower()
        proxy_url = f"{proxy_type}://{proxy.proxy.address}:{proxy.proxy.port}"
        
        proxy_key = f"{proxy.proxy.address}:{proxy.proxy.port}"
        if proxy_key in self.valid_proxies:
            return None

        try:
            async with session.get(
                ProxyScraperConfig.TEST_URL,
                proxy=proxy_url,
                timeout=aiohttp.ClientTimeout(total=ProxyScraperConfig.TIMEOUT)
            ) as response:
                if response.status == 200:
                    self.valid_proxies.add(proxy_key)
                    logger.debug(f"Valid proxy found: {proxy_url}")
                    return proxy
        except Exception:
            return None

        return None

    async def _validate_proxy_batch(self, proxies: List[ProxyRecord]) -> List[ProxyRecord]:
        valid_proxies = []
        connector = aiohttp.TCPConnector(limit=None, ttl_dns_cache=300)
        timeout = aiohttp.ClientTimeout(total=ProxyScraperConfig.TIMEOUT)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = []
            for proxy in proxies:
                if len(tasks) >= ProxyScraperConfig.MAX_CONCURRENT_TASKS:
                    done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        if result := await task:
                            valid_proxies.append(result)
                
                tasks.append(asyncio.create_task(self._validate_proxy(proxy, session)))
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                valid_proxies.extend([r for r in results if r is not None])
        
        return valid_proxies

    def _fetch_proxies_from_url(self, source: Dict) -> List[ProxyRecord]:
        try:
            response = self.session.get(source['url'], timeout=ProxyScraperConfig.TIMEOUT)
            response.raise_for_status()
            
            proxy_list = []
            seen_proxies = set()

            for line in response.text.splitlines():
                try:
                    if not line.strip() or line.startswith('#'):
                        continue
                    
                    address, port = line.strip().split(':')
                    proxy_key = f"{address}:{port}"
                    
                    if proxy_key in seen_proxies:
                        continue
                    
                    seen_proxies.add(proxy_key)
                    proxy_list.append(self._create_proxy_record(
                        address=address,
                        port=int(port),
                        proxy_type=source['type']
                    ))
                except (ValueError, IndexError) as e:
                    logger.debug(f"Error parsing proxy entry {line}: {e}")
                    continue

            logger.info(f"Fetched {len(proxy_list)} {source['type']} proxies from {source['url']}")
            return proxy_list

        except Exception as e:
            logger.error(f"Error fetching proxies from {source['url']}: {e}")
            return []

    async def validate_proxies(self, proxies: List[ProxyRecord]) -> List[ProxyRecord]:
        all_valid_proxies = []
        
        for i in range(0, len(proxies), ProxyScraperConfig.BATCH_SIZE):
            batch = proxies[i:i + ProxyScraperConfig.BATCH_SIZE]
            valid_batch = await self._validate_proxy_batch(batch)
            all_valid_proxies.extend(valid_batch)
            
            progress = min(100, (i + len(batch)) / len(proxies) * 100)
            logger.info(f"Validation progress: {progress:.1f}% - Valid proxies found: {len(all_valid_proxies)}")
        
        return all_valid_proxies

    def save_proxies(self, proxies: List[ProxyRecord]):
        # Remove any invalid entries
        valid_proxies = [
            proxy for proxy in proxies 
            if proxy.proxy.address and proxy.proxy.port and proxy.proxy.type != "NONE"
        ]

        # Group proxies by type for statistics
        proxy_stats = defaultdict(int)
        for proxy in valid_proxies:
            proxy_stats[proxy.proxy.type] += 1

        # Log statistics
        logger.info("Proxy Statistics:")
        for proxy_type, count in proxy_stats.items():
            logger.info(f"{proxy_type}: {count} proxies")

        # Create properly formatted JDownloader2 output
        output = {
            "customProxyList": [
                {
                    "proxy": {
                        "username": proxy.proxy.username,
                        "password": proxy.proxy.password,
                        "port": proxy.proxy.port,
                        "address": proxy.proxy.address,
                        "type": proxy.proxy.type,
                        "preferNativeImplementation": proxy.proxy.preferNativeImplementation,
                        "resolveHostName": proxy.proxy.resolveHostName,
                        "connectMethodPreferred": proxy.proxy.connectMethodPreferred
                    },
                    "rangeRequestsSupported": proxy.rangeRequestsSupported,
                    "filter": proxy.filter,
                    "pac": proxy.pac,
                    "reconnectSupported": proxy.reconnectSupported,
                    "enabled": proxy.enabled
                }
                for proxy in valid_proxies
            ]
        }
        
        with open(ProxyScraperConfig.FILENAME, 'w') as f:
            json.dump(output, f, indent=2)
        
        logger.info(f"Valid proxies saved to {ProxyScraperConfig.FILENAME}")

async def main():
    scraper = ProxyScraper()
    
    all_proxies = []
    for source in ProxyScraperConfig.PROXY_SOURCES:
        proxies = scraper._fetch_proxies_from_url(source)
        all_proxies.extend(proxies)

    logger.info(f"Total proxies fetched: {len(all_proxies)}")
    
    valid_proxies = await scraper.validate_proxies(all_proxies)
    logger.info(f"Total valid proxies: {len(valid_proxies)}")
    
    scraper.save_proxies(valid_proxies)

if __name__ == "__main__":
    asyncio.run(main())
