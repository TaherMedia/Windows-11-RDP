import json
import random
import shutil
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ===================== Configuration =====================
JSON_PATH    = Path("link.json")
TXT_PATH     = Path("link.txt")
DB_PATH      = Path("processed.db")
WAIT_SECONDS = 30          # <-- keep each window open for 30 seconds
MIN_DELAY    = 0.3
MAX_DELAY    = 1.0
CONCURRENCY  = 10

# ===================== Thread-safe helpers =====================
_print_lock = threading.Lock()
_driver_path_lock = threading.Lock()
_driver_path: str | None = None


def safe_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def get_driver_path() -> str:
    global _driver_path
    if _driver_path is not None:
        return _driver_path
    with _driver_path_lock:
        if _driver_path is None:
            _driver_path = ChromeDriverManager().install()
    return _driver_path


# ===================== SQLite =====================
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_index INTEGER UNIQUE,
            url TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def is_processed(index: int) -> bool:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        cur = conn.execute("SELECT 1 FROM processed WHERE account_index = ?", (index,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def mark_processed(index: int, url: str):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO processed (account_index, url) VALUES (?, ?)",
            (index, url),
        )
        conn.commit()
    finally:
        conn.close()


# ===================== Loaders =====================
def load_links_from_json():
    if not JSON_PATH.exists():
        return []
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    links = []
    for acc in data.get("accounts", []):
        idx = acc.get("index")
        url = acc.get("webapp_url")
        if idx is not None and url:
            links.append((idx, url))
    return links


def load_links_from_txt():
    if not TXT_PATH.exists():
        return []
    with open(TXT_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    links, current_index = [], None
    for line in lines:
        line = line.strip()
        if line.startswith("Account ") and ":" in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    current_index = int(parts[1].rstrip(":"))
                except ValueError:
                    current_index = None
        elif line.startswith("Link:") and current_index is not None:
            url = line[len("Link:"):].strip()
            if url:
                links.append((current_index, url))
                current_index = None
    return links


def choose_file():
    json_exists, txt_exists = JSON_PATH.exists(), TXT_PATH.exists()
    if json_exists and txt_exists:
        print("\nBoth link.json and link.txt found. Which one to use?")
        print("1: link.json")
        print("2: link.txt")
        choice = input("Enter 1 or 2: ").strip()
        return "json" if choice != "2" else "txt"
    if json_exists:
        return "json"
    if txt_exists:
        return "txt"
    return None


def get_user_range(links):
    if not links:
        return []
    indices = [idx for idx, _ in links]
    print(f"\nFound {len(links)} accounts with indices from {min(indices)} to {max(indices)}.")
    print("Enter the range you want to process:")
    print("  - 0                  : process all")
    print("  - <start> <end>      : process indices from start to end (inclusive)")
    print("  - <single>           : process only that single index")
    user_input = input("Your choice: ").strip()
    parts = user_input.split()

    if len(parts) == 1:
        if parts[0] == "0":
            return links[:]
        try:
            single = int(parts[0])
            start = end = single
        except ValueError:
            print("Invalid input. Please enter numbers only.")
            return []
    elif len(parts) == 2:
        try:
            start, end = int(parts[0]), int(parts[1])
        except ValueError:
            print("Invalid input. Please enter numbers only.")
            return []
    else:
        print("Invalid format. Please enter 0, two numbers, or a single number.")
        return []

    if start > end:
        print("Start index cannot be greater than end index.")
        return []

    filtered = [(idx, url) for idx, url in links if start <= idx <= end]
    if not filtered:
        print(f"No accounts found with indices between {start} and {end}.")
    else:
        print(f"Selected {len(filtered)} account(s) to process.")
    return filtered


# ===================== Worker =====================
def open_url(url: str, index: int) -> bool:
    if not url.startswith(("http://", "https://")):
        safe_print(f"[{index}] Warning: URL '{url}' does not start with http/https.")

    profile_dir = tempfile.mkdtemp(prefix=f"chrome_{index}_")

    options = Options()
    options.add_argument("--incognito")
    options.add_argument("--disable-cache")
    options.add_argument("--disk-cache-size=0")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-session-crashed-bubble")

    driver = None
    try:
        service = Service(get_driver_path())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(20)

        safe_print(f"[{index}] Opening: {url}")
        driver.get(url)
        safe_print(f"[{index}] Open. Keeping open for {WAIT_SECONDS}s...")
        time.sleep(WAIT_SECONDS)
        return True
    except Exception as e:
        safe_print(f"[{index}] Error: {e}")
        return False
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        shutil.rmtree(profile_dir, ignore_errors=True)
        safe_print(f"[{index}] Browser closed.")


def process_one(index: int, url: str) -> bool:
    success = open_url(url, index)
    if success:
        mark_processed(index, url)
        safe_print(f"[{index}] Marked as processed.")
    else:
        safe_print(f"[{index}] FAILED – not marked.")

    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    return success


# ===================== Main =====================
def main():
    print(f"=== Link Processor (concurrency={CONCURRENCY}, wait={WAIT_SECONDS}s) ===")
    init_db()

    file_type = choose_file()
    if file_type is None:
        print("No link file found (link.json or link.txt). Exiting.")
        return

    all_links = load_links_from_json() if file_type == "json" else load_links_from_txt()
    if not all_links:
        print(f"No valid links found in {file_type} file.")
        return

    links_to_process = get_user_range(all_links)
    if not links_to_process:
        print("Nothing to process. Exiting.")
        return

    pending = []
    for idx, url in links_to_process:
        if is_processed(idx):
            safe_print(f"Account {idx} already processed — skipping.")
        else:
            pending.append((idx, url))

    if not pending:
        print("All selected accounts already processed. Nothing to do.")
        return

    print(f"\nProcessing {len(pending)} account(s) with {CONCURRENCY} concurrent windows,")
    print(f"each open for {WAIT_SECONDS}s.\n")

    get_driver_path()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = {pool.submit(process_one, idx, url): (idx, url) for idx, url in pending}
        for fut in as_completed(futures):
            idx, url = futures[fut]
            try:
                fut.result()
            except Exception as e:
                safe_print(f"[{idx}] Unexpected error: {e}")

    print("\nAll selected accounts processed.")


if __name__ == "__main__":
    main()