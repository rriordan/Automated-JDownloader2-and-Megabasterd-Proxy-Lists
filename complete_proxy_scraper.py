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
from datetime import datetime, timedelta

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

@dataclass
class TimingStats:
    """Detailed timing statistics for different stages"""
    # Overall timing
    total_start_time: float
    total_end_time: float = 0.0

    # Stage timing
    fetching_start_time: float = 0.0
    fetching_end_time: float = 0.0
    deduplication_start_time: float = 0.0
    deduplication_end_time: float = 0.0
    validation_start_time: float = 0.0
    validation_end_time: float = 0.0
    saving_start_time: float = 0.0
    saving_end_time: float = 0.0
    reporting_start_time: float = 0.0
    reporting_end_time: float = 0.0

    # Validation progress tracking
    validation_batches_completed: int = 0
    validation_total_batches: int = 0
    validation_current_batch_start: float = 0.0

    @property
    def total_duration(self) -> float:
        return self.total_end_time - self.total_start_time if self.total_end_time > 0 else time.time() - self.total_start_time

    @property
    def fetching_duration(self) -> float:
        return self.fetching_end_time - self.fetching_start_time if self.fetching_end_time > 0 else 0.0

    @property
    def deduplication_duration(self) -> float:
        return self.deduplication_end_time - self.deduplication_start_time if self.deduplication_end_time > 0 else 0.0

    @property
    def validation_duration(self) -> float:
        return self.validation_end_time - self.validation_start_time if self.validation_end_time > 0 else 0.0

    @property
    def saving_duration(self) -> float:
        return self.saving_end_time - self.saving_start_time if self.saving_end_time > 0 else 0.0

    @property
    def reporting_duration(self) -> float:
        return self.reporting_end_time - self.reporting_start_time if self.reporting_end_time > 0 else 0.0

    def get_validation_eta(self, proxies_processed: int, total_proxies: int) -> float:
        """Calculate ETA for validation based on current progress"""
        if proxies_processed == 0 or self.validation_start_time == 0:
            return 0.0

        elapsed = time.time() - self.validation_start_time
        rate = proxies_processed / elapsed  # proxies per second
        remaining = total_proxies - proxies_processed

        return remaining / rate if rate > 0 else 0.0

    def get_processing_rate(self, proxies_processed: int) -> float:
        """Calculate current processing rate in proxies per second"""
        if proxies_processed == 0 or self.validation_start_time == 0:
            return 0.0

        elapsed = time.time() - self.validation_start_time
        return proxies_processed / elapsed if elapsed > 0 else 0.0

@dataclass
class ScrapingStats:
    """Comprehensive statistics tracking for the scraping process"""
    start_time: float
    end_time: float = 0.0

    # Source statistics
    sources_attempted: int = 0
    sources_successful: int = 0
    sources_failed: int = 0

    # Raw proxy statistics
    raw_proxies_fetched: Dict[str, int] = None
    total_raw_proxies: int = 0
    duplicates_removed_raw: int = 0
    unique_raw_proxies: int = 0

    # Testing statistics
    proxies_tested: int = 0
    proxies_passed: int = 0
    proxies_failed: int = 0
    timeouts: int = 0

    # Performance statistics
    fastest_response_time: float = 0.0
    slowest_response_time: float = 0.0
    average_response_time: float = 0.0

    # Final output statistics
    final_valid_proxies: Dict[str, int] = None
    total_valid_proxies: int = 0

    # Files created
    files_created: List[str] = None

    # Timing statistics
    timing: TimingStats = None

    def __post_init__(self):
        if self.raw_proxies_fetched is None:
            self.raw_proxies_fetched = {}
        if self.final_valid_proxies is None:
            self.final_valid_proxies = {}
        if self.files_created is None:
            self.files_created = []
        if self.timing is None:
            self.timing = TimingStats(total_start_time=self.start_time)

    @property
    def total_duration(self) -> float:
        return self.end_time - self.start_time if self.end_time > 0 else time.time() - self.start_time

    @property
    def success_rate(self) -> float:
        if self.proxies_tested == 0:
            return 0.0
        return (self.proxies_passed / self.proxies_tested) * 100

    @property
    def filter_efficiency(self) -> float:
        if self.total_raw_proxies == 0:
            return 0.0
        return (self.total_valid_proxies / self.total_raw_proxies) * 100

class ProxyScraperConfig:
    # Output directory
    OUTPUT_DIR = Path('Output')
    REPORT_FILENAME = OUTPUT_DIR / 'scraping_report.json'
    REPORT_SUMMARY_FILENAME = OUTPUT_DIR / 'scraping_summary.txt'

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
    TIMEOUT = 5  # Increased timeout for more sources
    BATCH_SIZE = 500  # Increased batch size
    MAX_CONCURRENT_TASKS = 1500  # Slightly reduced to handle more sources reliably
    MAX_RESPONSE_TIME = 5  # Increased max response time for more sources

    # Map proxy types to JDownloader2 format
    PROXY_TYPE_MAP = {
        "http": "HTTP",
        "https": "HTTPS",
        "socks4": "SOCKS4",
        "socks5": "SOCKS5"
    }

    # EXPANDED GitHub-only proxy sources for better coverage and reliability
    ALL_PROXY_SOURCES = {
        "socks4": [
            # Original source (kept for consistency)
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
            # Additional GitHub sources
            "https://raw.githubusercontent.com/mzyui/proxy-list/refs/heads/main/socks4.txt",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt",
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt",
            "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks4.txt",
            "https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks4_proxies.txt",
            "https://raw.githubusercontent.com/Noctiro/getproxy/master/file/socks4.txt",
            "https://raw.githubusercontent.com/zevtyardt/proxy-list/main/socks4.txt",
            "https://raw.githubusercontent.com/yemixzy/proxy-list/main/proxies/socks4.txt",
            "https://raw.githubusercontent.com/ArrayIterator/proxy-lists/main/proxies/socks4.txt",
            "https://raw.githubusercontent.com/zenjahid/FreeProxy4u/master/socks4.txt",
            "https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/socks4.txt",
            "https://raw.githubusercontent.com/tuanminpay/live-proxy/master/socks4.txt",
            "https://raw.githubusercontent.com/BreakingTechFr/Proxy_Free/main/proxies/socks4.txt",
            "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks4.txt",
            "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks4.txt",
            "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks4.txt",
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt",
        ],
        "socks5": [
            # Original source (kept for consistency)  
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            # Additional GitHub sources
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
            "https://raw.githubusercontent.com/mzyui/proxy-list/refs/heads/main/socks5.txt",
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt",
            "https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks5_proxies.txt",
            "https://raw.githubusercontent.com/Noctiro/getproxy/master/file/socks5.txt",
            "https://raw.githubusercontent.com/zevtyardt/proxy-list/main/socks5.txt",
            "https://raw.githubusercontent.com/yemixzy/proxy-list/main/proxies/socks5.txt",
            "https://raw.githubusercontent.com/ArrayIterator/proxy-lists/main/proxies/socks5.txt",
            "https://raw.githubusercontent.com/zenjahid/FreeProxy4u/master/socks5.txt",
            "https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/socks5.txt",
            "https://raw.githubusercontent.com/tuanminpay/live-proxy/master/socks5.txt",
            "https://raw.githubusercontent.com/BreakingTechFr/Proxy_Free/main/proxies/socks5.txt",
            "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt",
            "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt",
            "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks5.txt",
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt",
        ],
        "http": [
            # Original source (kept for consistency)
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            # Additional GitHub sources
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
            "https://github.com/monosans/proxy-list/raw/main/proxies/http.txt",
            "https://raw.githubusercontent.com/mzyui/proxy-list/refs/heads/main/http.txt",
            "https://github.com/mmpx12/proxy-list/raw/master/http.txt",
            "https://github.com/mmpx12/proxy-list/raw/master/https.txt",
            "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/http.txt",
            "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
            "https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/http_proxies.txt",
            "https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/https_proxies.txt",
            "https://raw.githubusercontent.com/Noctiro/getproxy/master/file/http.txt",
            "https://raw.githubusercontent.com/Noctiro/getproxy/master/file/https.txt",
            "https://raw.githubusercontent.com/zevtyardt/proxy-list/main/http.txt",
            "https://raw.githubusercontent.com/yemixzy/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/ArrayIterator/proxy-lists/main/proxies/http.txt",
            "https://raw.githubusercontent.com/ArrayIterator/proxy-lists/main/proxies/https.txt",
            "https://raw.githubusercontent.com/zenjahid/FreeProxy4u/master/http.txt",
            "https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/Vann-Dev/proxy-list/main/proxies/https.txt",
            "https://raw.githubusercontent.com/tuanminpay/live-proxy/master/http.txt",
            "https://raw.githubusercontent.com/BreakingTechFr/Proxy_Free/main/proxies/http.txt",
            "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt",
            "https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/https.txt",
            "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt",
            "https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt",
            "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/http.txt",
            "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/https.txt",
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
            "https://raw.githubusercontent.com/aslisk/proxyhttps/main/https.txt",
            "https://raw.githubusercontent.com/saisuiu/uiu/main/free.txt",
            "https://raw.githubusercontent.com/berkay-digital/Proxy-Scraper/main/proxies.txt",
            "https://raw.githubusercontent.com/MrMarble/proxy-list/main/all.txt",
        ]
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

        # Initialize statistics tracking with enhanced timing
        self.stats = ScrapingStats(start_time=time.time())
        self.failed_proxies = []
        self.timeout_proxies = []

        # Progress tracking for live updates
        self.last_progress_update = time.time()
        self.progress_update_interval = 5  # seconds

        # Create output directory if it doesn't exist
        ProxyScraperConfig.OUTPUT_DIR.mkdir(exist_ok=True)
        logger.info(f"Created output directory: {ProxyScraperConfig.OUTPUT_DIR}")

    @property
    def proxy_sources(self) -> List[Dict]:
        sources = []
        for proxy_type in self.proxy_types:
            proxy_type_lower = proxy_type.lower()
            if proxy_type_lower in ProxyScraperConfig.ALL_PROXY_SOURCES:
                for url in ProxyScraperConfig.ALL_PROXY_SOURCES[proxy_type_lower]:
                    sources.append({
                        "url": url,
                        "type": proxy_type_lower
                    })
        return sources

    def _create_proxy_record(self, address: str, port: int, proxy_type: str) -> ProxyRecord:
        jd_proxy_type = ProxyScraperConfig.PROXY_TYPE_MAP.get(proxy_type.lower(), "NONE")

        preferences = ProxyPreferences(
            address=address,
            port=port,
            type=jd_proxy_type,
            response_time=0.0
        )

        return ProxyRecord(proxy=preferences, response_time=0.0)

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def format_eta(self, eta_seconds: float) -> str:
        """Format ETA in human-readable format"""
        if eta_seconds <= 0:
            return "Unknown"
        return self.format_duration(eta_seconds)

    async def _test_proxy(self, proxy_url: str, session: aiohttp.ClientSession) -> Tuple[bool, float, str]:
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
                    return True, response_time, "success"
        except asyncio.TimeoutError:
            return False, 0, "timeout"
        except Exception as e:
            return False, 0, f"error: {type(e).__name__}"

    async def _validate_proxy(self, proxy: ProxyRecord, session: aiohttp.ClientSession) -> Optional[ProxyRecord]:
        async with self.semaphore:  # Control concurrent connections
            proxy_type = proxy.proxy.type.lower()
            proxy_url = f"{proxy_type}://{proxy.proxy.address}:{proxy.proxy.port}"
            proxy_key = f"{proxy.proxy.address}:{proxy.proxy.port}"

            if proxy_key in self.valid_proxies:
                return None

            success, response_time, status = await self._test_proxy(proxy_url, session)

            # Track statistics
            self.stats.proxies_tested += 1
            if status == "timeout":
                self.stats.timeouts += 1
                self.timeout_proxies.append(proxy_key)
            elif not success:
                self.failed_proxies.append(proxy_key)

            if success and response_time <= ProxyScraperConfig.MAX_RESPONSE_TIME:
                self.valid_proxies.add(proxy_key)
                proxy.response_time = response_time
                proxy.proxy.response_time = response_time
                self.stats.proxies_passed += 1
                return proxy
            else:
                self.stats.proxies_failed += 1
                return None

    async def validate_proxies(self, proxies: List[ProxyRecord]) -> List[ProxyRecord]:
        total_proxies = len(proxies)
        logger.info(f"Starting validation of {total_proxies:,} unique proxies...")

        # Start validation timing
        self.stats.timing.validation_start_time = time.time()
        self.stats.timing.validation_total_batches = (total_proxies + ProxyScraperConfig.BATCH_SIZE - 1) // ProxyScraperConfig.BATCH_SIZE

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
                batch_start_time = time.time()
                batch = tasks[i:i + ProxyScraperConfig.BATCH_SIZE]
                results = await asyncio.gather(*batch, return_exceptions=True)

                valid_batch = [r for r in results if r is not None and not isinstance(r, Exception)]
                valid_proxies.extend(valid_batch)

                # Update batch progress
                self.stats.timing.validation_batches_completed += 1
                batch_time = time.time() - batch_start_time

                # Calculate progress and ETA
                proxies_processed = min(i + len(batch), total_proxies)
                progress = (proxies_processed / total_proxies) * 100

                # Calculate rates and ETA
                processing_rate = self.stats.timing.get_processing_rate(proxies_processed)
                eta_seconds = self.stats.timing.get_validation_eta(proxies_processed, total_proxies)

                # Enhanced progress logging with timing info
                current_time = time.time()
                if current_time - self.last_progress_update >= self.progress_update_interval:
                    avg_response_time = sum(p.response_time for p in valid_proxies) / len(valid_proxies) if valid_proxies else 0

                    elapsed = current_time - self.stats.timing.validation_start_time

                    logger.info(f"VALIDATION: {progress:.1f}% | "
                              f"Valid: {len(valid_proxies):,} | "
                              f"Rate: {processing_rate:.1f} p/s | "
                              f"Elapsed: {self.format_duration(elapsed)} | "
                              f"ETA: {self.format_eta(eta_seconds)} | "
                              f"Batch: {batch_time:.1f}s | "
                              f"Avg RT: {avg_response_time:.2f}s")

                    self.last_progress_update = current_time

            # End validation timing
            self.stats.timing.validation_end_time = time.time()
            validation_duration = self.stats.timing.validation_duration

            # Calculate performance statistics
            if valid_proxies:
                response_times = [p.response_time for p in valid_proxies]
                self.stats.fastest_response_time = min(response_times)
                self.stats.slowest_response_time = max(response_times)
                self.stats.average_response_time = sum(response_times) / len(response_times)

            # Final validation summary
            final_rate = total_proxies / validation_duration if validation_duration > 0 else 0
            logger.info(f"VALIDATION COMPLETE: {len(valid_proxies):,}/{total_proxies:,} valid | "
                       f"Duration: {self.format_duration(validation_duration)} | "
                       f"Rate: {final_rate:.1f} p/s | "
                       f"Success: {self.stats.success_rate:.1f}%")

            return sorted(valid_proxies, key=lambda x: x.response_time)

    def fetch_proxies_from_url(self, source: Dict) -> List[ProxyRecord]:
        source_type = source['type']
        source_url = source['url']
        self.stats.sources_attempted += 1

        fetch_start = time.time()

        try:
            logger.info(f"FETCHING: {source_type} from {source_url.split('/')[-1]}")
            response = self.session.get(source_url, timeout=ProxyScraperConfig.TIMEOUT)
            response.raise_for_status()

            seen_proxies = set()
            proxy_list = []
            raw_count = 0

            for line in response.text.splitlines():
                if not line.strip() or line.startswith('#'):
                    continue

                raw_count += 1
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

            # Update statistics
            fetch_duration = time.time() - fetch_start
            duplicates_in_source = raw_count - len(proxy_list)
            if source_type not in self.stats.raw_proxies_fetched:
                self.stats.raw_proxies_fetched[source_type] = 0
            self.stats.raw_proxies_fetched[source_type] += len(proxy_list)
            self.stats.sources_successful += 1

            logger.info(f"FETCHED: {len(proxy_list):,} {source_type} proxies in {fetch_duration:.1f}s "
                       f"({duplicates_in_source} dupes removed)")
            return proxy_list

        except Exception as e:
            fetch_duration = time.time() - fetch_start
            logger.error(f"FETCH ERROR: {source_type} from {source_url.split('/')[-1]} "
                        f"in {fetch_duration:.1f}s - {e}")
            self.stats.sources_failed += 1
            if source_type not in self.stats.raw_proxies_fetched:
                self.stats.raw_proxies_fetched[source_type] = 0
            return []

    def _save_jdownloader_file(self, proxies: List[ProxyRecord], filename: Path, proxy_type_filter: str = None):
        """Save proxies in JDownloader2 format with optional type filtering"""
        if proxy_type_filter:
            filtered_proxies = [p for p in proxies if p.proxy.type.upper() == proxy_type_filter.upper()]
        else:
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

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        self.stats.files_created.append(str(filename))
        logger.info(f"SAVED: {len(filtered_proxies):,} {proxy_type_filter or 'total'} proxies to {filename.name}")

    def _save_megabasterd_file(self, proxies: List[ProxyRecord], filename: Path, proxy_type_filter: str = None):
        """Save proxies in MegaBasterd format with optional type filtering"""
        if proxy_type_filter:
            filtered_proxies = [p for p in proxies if p.proxy.type.upper() == proxy_type_filter.upper()]
        else:
            filtered_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not filtered_proxies:
            logger.warning(f"No {proxy_type_filter or 'valid'} proxies to save to {filename}")
            return

        proxy_lines = []
        for proxy in filtered_proxies:
            proxy_line = f"{proxy.proxy.address}:{proxy.proxy.port}"
            proxy_lines.append(proxy_line)

        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(proxy_lines))

        self.stats.files_created.append(str(filename))
        logger.info(f"SAVED: {len(filtered_proxies):,} {proxy_type_filter or 'total'} proxies to {filename.name}")

    def save_all_proxy_files(self, proxies: List[ProxyRecord]):
        """Save proxies in both JDownloader2 and MegaBasterd formats (8 files total)"""
        self.stats.timing.saving_start_time = time.time()

        valid_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not valid_proxies:
            logger.error("No valid proxies to save!")
            return

        logger.info("\n" + "="*80)
        logger.info("SAVING ALL PROXY FILES TO OUTPUT FOLDER")
        logger.info("="*80)

        # Count proxies by type for final statistics
        type_stats = defaultdict(int)
        for proxy in valid_proxies:
            type_stats[proxy.proxy.type] += 1

        # Update final statistics
        self.stats.final_valid_proxies = dict(type_stats)
        self.stats.total_valid_proxies = len(valid_proxies)

        logger.info("\nFinal Proxy Distribution:")
        for proxy_type, count in sorted(type_stats.items()):
            logger.info(f"   {proxy_type}: {count:,} proxies")
        logger.info(f"   TOTAL: {len(valid_proxies):,} valid proxies")

        # Save JDownloader2 files (4 files)
        logger.info("\nSaving JDownloader2 Files:")
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_COMBINED_FILENAME)
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_HTTP_FILENAME, "HTTP")
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_SOCKS4_FILENAME, "SOCKS4")
        self._save_jdownloader_file(valid_proxies, ProxyScraperConfig.JD_SOCKS5_FILENAME, "SOCKS5")

        # Save MegaBasterd files (4 files)
        logger.info("\nSaving MegaBasterd Files:")
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_COMBINED_FILENAME)
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_HTTP_FILENAME, "HTTP")
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_SOCKS4_FILENAME, "SOCKS4")
        self._save_megabasterd_file(valid_proxies, ProxyScraperConfig.MB_SOCKS5_FILENAME, "SOCKS5")

        self.stats.timing.saving_end_time = time.time()
        saving_duration = self.stats.timing.saving_duration
        logger.info(f"\nFile saving completed in {self.format_duration(saving_duration)}")

    def generate_comprehensive_report(self):
        """Generate detailed JSON and text reports with enhanced timing information - FIXED UNICODE"""
        self.stats.timing.reporting_start_time = time.time()
        self.stats.end_time = time.time()
        self.stats.timing.total_end_time = self.stats.end_time

        # Calculate final statistics
        self.stats.total_raw_proxies = sum(self.stats.raw_proxies_fetched.values())

        # Count total sources for each type
        total_sources_by_type = {}
        for proxy_type in self.proxy_types:
            if proxy_type in ProxyScraperConfig.ALL_PROXY_SOURCES:
                total_sources_by_type[proxy_type] = len(ProxyScraperConfig.ALL_PROXY_SOURCES[proxy_type])

        # Create comprehensive JSON report with timing details
        report_data = {
            "scraping_session": {
                "timestamp": datetime.now().isoformat(),
                "duration_seconds": round(self.stats.total_duration, 2),
                "proxy_types_requested": self.proxy_types,
                "total_sources_by_type": total_sources_by_type,
                "configuration": {
                    "timeout": ProxyScraperConfig.TIMEOUT,
                    "max_response_time": ProxyScraperConfig.MAX_RESPONSE_TIME,
                    "batch_size": ProxyScraperConfig.BATCH_SIZE,
                    "max_concurrent_tasks": ProxyScraperConfig.MAX_CONCURRENT_TASKS,
                    "test_endpoint": ProxyScraperConfig.TEST_URL
                }
            },
            "timing_breakdown": {
                "total_duration": round(self.stats.timing.total_duration, 2),
                "fetching_duration": round(self.stats.timing.fetching_duration, 2),
                "deduplication_duration": round(self.stats.timing.deduplication_duration, 2),
                "validation_duration": round(self.stats.timing.validation_duration, 2),
                "saving_duration": round(self.stats.timing.saving_duration, 2),
                "reporting_duration": 0.0,  # Will be updated after report generation
            },
            "processing_rates": {
                "total_proxies_per_second": round(self.stats.total_raw_proxies / self.stats.timing.total_duration, 2) if self.stats.timing.total_duration > 0 else 0,
                "validation_proxies_per_second": round(self.stats.proxies_tested / self.stats.timing.validation_duration, 2) if self.stats.timing.validation_duration > 0 else 0,
                "sources_per_second": round(self.stats.sources_attempted / self.stats.timing.fetching_duration, 2) if self.stats.timing.fetching_duration > 0 else 0
            },
            "source_statistics": {
                "sources_attempted": self.stats.sources_attempted,
                "sources_successful": self.stats.sources_successful,
                "sources_failed": self.stats.sources_failed,
                "raw_proxies_by_type": self.stats.raw_proxies_fetched,
                "total_raw_proxies": self.stats.total_raw_proxies
            },
            "validation_statistics": {
                "proxies_tested": self.stats.proxies_tested,
                "proxies_passed": self.stats.proxies_passed,
                "proxies_failed": self.stats.proxies_failed,
                "timeouts": self.stats.timeouts,
                "success_rate_percent": round(self.stats.success_rate, 2),
                "filter_efficiency_percent": round(self.stats.filter_efficiency, 2)
            },
            "performance_statistics": {
                "fastest_response_time": round(self.stats.fastest_response_time, 3) if self.stats.fastest_response_time else 0,
                "slowest_response_time": round(self.stats.slowest_response_time, 3) if self.stats.slowest_response_time else 0,
                "average_response_time": round(self.stats.average_response_time, 3) if self.stats.average_response_time else 0
            },
            "output_statistics": {
                "final_valid_proxies_by_type": self.stats.final_valid_proxies,
                "total_valid_proxies": self.stats.total_valid_proxies,
                "files_created": self.stats.files_created,
                "total_files_created": len(self.stats.files_created)
            }
        }

        # Save JSON report with UTF-8 encoding - FIXED
        with open(ProxyScraperConfig.REPORT_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        # Create enhanced human-readable summary with detailed timing - NO UNICODE EMOJIS
        summary_lines = [
            "="*80,
            "ENHANCED PROXY SCRAPING PERFORMANCE REPORT",
            "="*80,
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Total Duration: {self.format_duration(self.stats.timing.total_duration)}",
            f"Proxy Types: {', '.join(self.proxy_types)}",
            "",
            "TIMING BREAKDOWN",
            "-" * 50,
            f"Source Fetching: {self.format_duration(self.stats.timing.fetching_duration)}",
            f"Cross-Source Deduplication: {self.format_duration(self.stats.timing.deduplication_duration)}",
            f"Proxy Validation: {self.format_duration(self.stats.timing.validation_duration)}",
            f"File Saving: {self.format_duration(self.stats.timing.saving_duration)}",
            f"Report Generation: {self.format_duration(self.stats.timing.reporting_duration)}",
            "",
            "PROCESSING RATES",
            "-" * 50,
            f"Overall Rate: {self.stats.total_raw_proxies / self.stats.timing.total_duration:.1f} proxies/second" if self.stats.timing.total_duration > 0 else "Overall Rate: N/A",
            f"Validation Rate: {self.stats.proxies_tested / self.stats.timing.validation_duration:.1f} proxies/second" if self.stats.timing.validation_duration > 0 else "Validation Rate: N/A",
            f"Source Fetching Rate: {self.stats.sources_attempted / self.stats.timing.fetching_duration:.1f} sources/second" if self.stats.timing.fetching_duration > 0 else "Source Fetching Rate: N/A",
            "",
            "SOURCE STATISTICS (GitHub Sources Only)",
            "-" * 50,
            f"Sources Attempted: {self.stats.sources_attempted}",
            f"Sources Successful: {self.stats.sources_successful}",
            f"Sources Failed: {self.stats.sources_failed}",
        ]

        # Add source breakdown by type
        for proxy_type in self.proxy_types:
            if proxy_type in total_sources_by_type:
                summary_lines.append(f"{proxy_type.upper()} sources available: {total_sources_by_type[proxy_type]}")

        summary_lines.extend([
            "",
            "RAW PROXY STATISTICS",
            "-" * 40,
        ])

        for proxy_type, count in sorted(self.stats.raw_proxies_fetched.items()):
            summary_lines.append(f"{proxy_type.upper()} proxies fetched: {count:,}")

        summary_lines.extend([
            f"Total Raw Proxies: {self.stats.total_raw_proxies:,}",
            "",
            "VALIDATION STATISTICS", 
            "-" * 40,
            f"Proxies Tested: {self.stats.proxies_tested:,}",
            f"Proxies Passed: {self.stats.proxies_passed:,}",
            f"Proxies Failed: {self.stats.proxies_failed:,}",
            f"Timeouts: {self.stats.timeouts:,}",
            f"Success Rate: {self.stats.success_rate:.1f}%",
            f"Filter Efficiency: {self.stats.filter_efficiency:.1f}%",
            "",
            "PERFORMANCE STATISTICS",
            "-" * 40,
        ])

        if self.stats.total_valid_proxies > 0:
            summary_lines.extend([
                f"Fastest Response: {self.stats.fastest_response_time:.3f}s",
                f"Slowest Response: {self.stats.slowest_response_time:.3f}s", 
                f"Average Response: {self.stats.average_response_time:.3f}s",
            ])
        else:
            summary_lines.append("No performance data (no valid proxies)")

        summary_lines.extend([
            "",
            "OUTPUT STATISTICS",
            "-" * 40,
        ])

        for proxy_type, count in sorted(self.stats.final_valid_proxies.items()):
            summary_lines.append(f"Final {proxy_type} proxies: {count:,}")

        summary_lines.extend([
            f"Total Valid Proxies: {self.stats.total_valid_proxies:,}",
            f"Files Created: {len(self.stats.files_created)}",
            "",
            "FILES CREATED",
            "-" * 40,
        ])

        for file_path in sorted(self.stats.files_created):
            file_size = Path(file_path).stat().st_size if Path(file_path).exists() else 0
            summary_lines.append(f"{Path(file_path).name}: {file_size:,} bytes")

        summary_lines.extend([
            "",
            "="*80,
            "ENHANCED WITH PERFORMANCE MONITORING",
            f"Total GitHub sources used: {sum(total_sources_by_type.values()) if total_sources_by_type else 0}",
            "Live ETA, processing rates, and detailed timing provided!",
            "",
            "Report files saved:",
            f"- {ProxyScraperConfig.REPORT_FILENAME} (Detailed JSON)",
            f"- {ProxyScraperConfig.REPORT_SUMMARY_FILENAME} (Human-readable)",
            "="*80
        ])

        summary_text = "\n".join(summary_lines)

        # Save text summary with UTF-8 encoding - FIXED
        with open(ProxyScraperConfig.REPORT_SUMMARY_FILENAME, 'w', encoding='utf-8') as f:
            f.write(summary_text)

        self.stats.timing.reporting_end_time = time.time()

        # Update JSON report with final reporting duration
        report_data["timing_breakdown"]["reporting_duration"] = round(self.stats.timing.reporting_duration, 2)
        with open(ProxyScraperConfig.REPORT_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        # Also log the summary to console (condensed version) - NO UNICODE EMOJIS
        logger.info(f"\n" + "="*80)
        logger.info("SCRAPING COMPLETED - PERFORMANCE SUMMARY")
        logger.info("="*80)
        logger.info(f"Total Duration: {self.format_duration(self.stats.timing.total_duration)}")
        logger.info(f"Validation: {self.format_duration(self.stats.timing.validation_duration)} "
                   f"({self.stats.proxies_tested / self.stats.timing.validation_duration:.1f} p/s)" if self.stats.timing.validation_duration > 0 else "")
        logger.info(f"Results: {self.stats.total_valid_proxies:,}/{self.stats.total_raw_proxies:,} proxies "
                   f"({self.stats.filter_efficiency:.1f}% efficiency)")
        logger.info(f"Files: {len(self.stats.files_created)} created in Output/")
        logger.info(f"Reports: {ProxyScraperConfig.REPORT_FILENAME.name}, {ProxyScraperConfig.REPORT_SUMMARY_FILENAME.name}")
        logger.info("="*80)

def parse_arguments():
    parser = argparse.ArgumentParser(description='Enhanced Multi-Source Proxy Generator with Performance Monitoring')
    parser.add_argument('-type', '--proxy-type',
                        choices=['http', 'socks4', 'socks5', 'all'],
                        default='all',
                        help='Type of proxies to fetch')
    return parser.parse_args()

async def main():
    args = parse_arguments()

    proxy_types = list(ProxyScraperConfig.ALL_PROXY_SOURCES.keys()) if args.proxy_type == 'all' else [args.proxy_type]

    # Count total sources
    total_sources = sum(len(ProxyScraperConfig.ALL_PROXY_SOURCES[pt]) for pt in proxy_types)

    logger.info("="*80)
    logger.info("ENHANCED MULTI-SOURCE PROXY SCRAPER WITH PERFORMANCE MONITORING")
    logger.info("="*80)
    logger.info(f"Target: {', '.join(proxy_types)} proxies")
    logger.info(f"Total GitHub sources: {total_sources}")
    logger.info(f"Output folder: {ProxyScraperConfig.OUTPUT_DIR}")
    logger.info(f"Expected files: 10 total (8 proxy files + 2 reports)")
    logger.info(f"Batch size: {ProxyScraperConfig.BATCH_SIZE} | Max concurrent: {ProxyScraperConfig.MAX_CONCURRENT_TASKS}")
    logger.info("="*80)

    scraper = ProxyScraper(proxy_types)

    # STAGE 1: Fetch proxies from all sources with timing
    logger.info("\nSTAGE 1: FETCHING PROXIES FROM SOURCES")
    scraper.stats.timing.fetching_start_time = time.time()

    all_proxies = []
    for source in scraper.proxy_sources:
        proxies = scraper.fetch_proxies_from_url(source)
        all_proxies.extend(proxies)

    scraper.stats.timing.fetching_end_time = time.time()
    fetching_duration = scraper.stats.timing.fetching_duration

    logger.info(f"\nSTAGE 1 COMPLETE: {len(all_proxies):,} proxies fetched in {scraper.format_duration(fetching_duration)}")
    logger.info(f"Fetching rate: {len(all_proxies) / fetching_duration:.1f} proxies/second")

    # STAGE 2: Cross-source deduplication with timing
    logger.info("\nSTAGE 2: CROSS-SOURCE DEDUPLICATION")
    scraper.stats.timing.deduplication_start_time = time.time()

    seen_global_proxies = set()
    unique_proxies = []

    for proxy in all_proxies:
        proxy_key = f"{proxy.proxy.address}:{proxy.proxy.port}"
        if proxy_key not in seen_global_proxies:
            seen_global_proxies.add(proxy_key)
            unique_proxies.append(proxy)

    scraper.stats.timing.deduplication_end_time = time.time()
    deduplication_duration = scraper.stats.timing.deduplication_duration
    duplicates_removed = len(all_proxies) - len(unique_proxies)

    logger.info(f"\nSTAGE 2 COMPLETE: {duplicates_removed:,} duplicates removed in {scraper.format_duration(deduplication_duration)}")
    logger.info(f"Remaining unique proxies: {len(unique_proxies):,}")
    logger.info(f"Deduplication rate: {len(all_proxies) / deduplication_duration:.1f} proxies/second" if deduplication_duration > 0 else "")

    # STAGE 3: Validate all proxies with enhanced progress tracking
    logger.info("\nSTAGE 3: PROXY VALIDATION WITH LIVE PROGRESS")
    valid_proxies = await scraper.validate_proxies(unique_proxies)

    # STAGE 4: Save all proxy files with timing
    logger.info("\nSTAGE 4: SAVING PROXY FILES")
    scraper.save_all_proxy_files(valid_proxies)

    # STAGE 5: Generate comprehensive reports
    logger.info("\nSTAGE 5: GENERATING PERFORMANCE REPORTS")
    scraper.generate_comprehensive_report()

    # Final summary
    total_duration = scraper.stats.timing.total_duration
    logger.info(f"\nENHANCED MULTI-SOURCE SCRAPING COMPLETED!")
    logger.info(f"Check the 'Output' folder for all {len(scraper.stats.files_created)} files including detailed performance reports.")

if __name__ == "__main__":
    asyncio.run(main())
