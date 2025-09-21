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
from datetime import datetime

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

    def __post_init__(self):
        if self.raw_proxies_fetched is None:
            self.raw_proxies_fetched = {}
        if self.final_valid_proxies is None:
            self.final_valid_proxies = {}
        if self.files_created is None:
            self.files_created = []

    @property
    def total_duration(self) -> float:
        return self.end_time - self.start_time

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

        # Initialize statistics tracking
        self.stats = ScrapingStats(start_time=time.time())
        self.failed_proxies = []
        self.timeout_proxies = []

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
        logger.info(f"🚀 Starting validation of {len(proxies)} unique proxies...")

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

            # Calculate performance statistics
            if valid_proxies:
                response_times = [p.response_time for p in valid_proxies]
                self.stats.fastest_response_time = min(response_times)
                self.stats.slowest_response_time = max(response_times)
                self.stats.average_response_time = sum(response_times) / len(response_times)

            return sorted(valid_proxies, key=lambda x: x.response_time)

    def fetch_proxies_from_url(self, source: Dict) -> List[ProxyRecord]:
        source_type = source['type']
        self.stats.sources_attempted += 1

        try:
            logger.info(f"📥 Fetching {source_type} proxies from {source['url']}")
            response = self.session.get(source['url'], timeout=ProxyScraperConfig.TIMEOUT)
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
            duplicates_in_source = raw_count - len(proxy_list)
            self.stats.raw_proxies_fetched[source_type] = len(proxy_list)
            self.stats.sources_successful += 1

            logger.info(f"✅ Fetched {len(proxy_list)} unique {source_type} proxies ({duplicates_in_source} duplicates removed)")
            return proxy_list

        except Exception as e:
            logger.error(f"❌ Error fetching {source_type} proxies: {e}")
            self.stats.sources_failed += 1
            self.stats.raw_proxies_fetched[source_type] = 0
            return []

    def _save_jdownloader_file(self, proxies: List[ProxyRecord], filename: Path, proxy_type_filter: str = None):
        """Save proxies in JDownloader2 format with optional type filtering"""
        if proxy_type_filter:
            filtered_proxies = [p for p in proxies if p.proxy.type.upper() == proxy_type_filter.upper()]
        else:
            filtered_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not filtered_proxies:
            logger.warning(f"⚠️ No {proxy_type_filter or 'valid'} proxies to save to {filename}")
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

        self.stats.files_created.append(str(filename))
        logger.info(f"✅ Saved {len(filtered_proxies)} {proxy_type_filter or 'total'} proxies to {filename}")

    def _save_megabasterd_file(self, proxies: List[ProxyRecord], filename: Path, proxy_type_filter: str = None):
        """Save proxies in MegaBasterd format with optional type filtering"""
        if proxy_type_filter:
            filtered_proxies = [p for p in proxies if p.proxy.type.upper() == proxy_type_filter.upper()]
        else:
            filtered_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not filtered_proxies:
            logger.warning(f"⚠️ No {proxy_type_filter or 'valid'} proxies to save to {filename}")
            return

        proxy_lines = []
        for proxy in filtered_proxies:
            proxy_line = f"{proxy.proxy.address}:{proxy.proxy.port}"
            proxy_lines.append(proxy_line)

        with open(filename, 'w') as f:
            f.write('\n'.join(proxy_lines))

        self.stats.files_created.append(str(filename))
        logger.info(f"✅ Saved {len(filtered_proxies)} {proxy_type_filter or 'total'} proxies to {filename}")

    def save_all_proxy_files(self, proxies: List[ProxyRecord]):
        """Save proxies in both JDownloader2 and MegaBasterd formats (8 files total)"""
        valid_proxies = [p for p in proxies if p.proxy.type != "NONE"]

        if not valid_proxies:
            logger.error("❌ No valid proxies to save!")
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

        logger.info("\n📊 Final Proxy Distribution:")
        for proxy_type, count in sorted(type_stats.items()):
            logger.info(f"   • {proxy_type}: {count} proxies")
        logger.info(f"   • TOTAL: {len(valid_proxies)} valid proxies")

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

    def generate_comprehensive_report(self):
        """Generate detailed JSON and text reports"""
        self.stats.end_time = time.time()

        # Calculate final statistics
        self.stats.total_raw_proxies = sum(self.stats.raw_proxies_fetched.values())

        # Create comprehensive JSON report
        report_data = {
            "scraping_session": {
                "timestamp": datetime.now().isoformat(),
                "duration_seconds": round(self.stats.total_duration, 2),
                "proxy_types_requested": self.proxy_types,
                "configuration": {
                    "timeout": ProxyScraperConfig.TIMEOUT,
                    "max_response_time": ProxyScraperConfig.MAX_RESPONSE_TIME,
                    "batch_size": ProxyScraperConfig.BATCH_SIZE,
                    "max_concurrent_tasks": ProxyScraperConfig.MAX_CONCURRENT_TASKS,
                    "test_endpoint": ProxyScraperConfig.TEST_URL
                }
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

        # Save JSON report
        with open(ProxyScraperConfig.REPORT_FILENAME, 'w') as f:
            json.dump(report_data, f, indent=2)

        # Create human-readable summary
        summary_lines = [
            "="*80,
            "PROXY SCRAPING SUMMARY REPORT",
            "="*80,
            f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"⏱️  Total Duration: {self.stats.total_duration:.1f} seconds",
            f"🎯 Proxy Types: {', '.join(self.proxy_types)}",
            "",
            "📡 SOURCE STATISTICS",
            "-" * 40,
            f"Sources Attempted: {self.stats.sources_attempted}",
            f"Sources Successful: {self.stats.sources_successful}",
            f"Sources Failed: {self.stats.sources_failed}",
            "",
            "📊 RAW PROXY STATISTICS",
            "-" * 40,
        ]

        for proxy_type, count in sorted(self.stats.raw_proxies_fetched.items()):
            summary_lines.append(f"{proxy_type.upper()} proxies fetched: {count:,}")

        summary_lines.extend([
            f"Total Raw Proxies: {self.stats.total_raw_proxies:,}",
            "",
            "🧪 VALIDATION STATISTICS", 
            "-" * 40,
            f"Proxies Tested: {self.stats.proxies_tested:,}",
            f"Proxies Passed: {self.stats.proxies_passed:,}",
            f"Proxies Failed: {self.stats.proxies_failed:,}",
            f"Timeouts: {self.stats.timeouts:,}",
            f"Success Rate: {self.stats.success_rate:.1f}%",
            f"Filter Efficiency: {self.stats.filter_efficiency:.1f}%",
            "",
            "🚀 PERFORMANCE STATISTICS",
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
            "📁 OUTPUT STATISTICS",
            "-" * 40,
        ])

        for proxy_type, count in sorted(self.stats.final_valid_proxies.items()):
            summary_lines.append(f"Final {proxy_type} proxies: {count:,}")

        summary_lines.extend([
            f"Total Valid Proxies: {self.stats.total_valid_proxies:,}",
            f"Files Created: {len(self.stats.files_created)}",
            "",
            "📂 FILES CREATED",
            "-" * 40,
        ])

        for file_path in sorted(self.stats.files_created):
            file_size = Path(file_path).stat().st_size if Path(file_path).exists() else 0
            summary_lines.append(f"{Path(file_path).name}: {file_size:,} bytes")

        summary_lines.extend([
            "",
            "="*80,
            "Report files saved:",
            f"• {ProxyScraperConfig.REPORT_FILENAME} (Detailed JSON)",
            f"• {ProxyScraperConfig.REPORT_SUMMARY_FILENAME} (Human-readable)",
            "="*80
        ])

        summary_text = "\n".join(summary_lines)

        # Save text summary
        with open(ProxyScraperConfig.REPORT_SUMMARY_FILENAME, 'w') as f:
            f.write(summary_text)

        # Also log the summary to console
        logger.info("\n" + summary_text)

        logger.info(f"\n📋 Detailed reports saved:")
        logger.info(f"   • JSON Report: {ProxyScraperConfig.REPORT_FILENAME}")
        logger.info(f"   • Summary Report: {ProxyScraperConfig.REPORT_SUMMARY_FILENAME}")

def parse_arguments():
    parser = argparse.ArgumentParser(description='Complete Proxy Generator with Detailed Reporting')
    parser.add_argument('-type', '--proxy-type',
                        choices=['http', 'socks4', 'socks5', 'all'],
                        default='all',
                        help='Type of proxies to fetch')
    return parser.parse_args()

async def main():
    args = parse_arguments()

    proxy_types = list(ProxyScraperConfig.ALL_PROXY_SOURCES.keys()) if args.proxy_type == 'all' else [args.proxy_type]

    logger.info("="*80)
    logger.info("COMPLETE PROXY SCRAPER WITH DETAILED REPORTING")
    logger.info("="*80)
    logger.info(f"🎯 Target: {', '.join(proxy_types)} proxies")
    logger.info(f"📁 Output folder: {ProxyScraperConfig.OUTPUT_DIR}")
    logger.info(f"📊 Expected files: 10 total (8 proxy files + 2 reports)")

    scraper = ProxyScraper(proxy_types)

    # Fetch proxies from all sources
    all_proxies = []
    for source in scraper.proxy_sources:
        proxies = scraper.fetch_proxies_from_url(source)
        all_proxies.extend(proxies)

    # Validate all proxies
    valid_proxies = await scraper.validate_proxies(all_proxies)

    # Save all proxy files
    scraper.save_all_proxy_files(valid_proxies)

    # Generate comprehensive reports
    scraper.generate_comprehensive_report()

    logger.info(f"\n🎉 Process completed! Check the 'Output' folder for all files.")

if __name__ == "__main__":
    asyncio.run(main())
