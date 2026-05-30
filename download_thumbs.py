"""Download missing thumbnails from animadex API to local cache."""
import hashlib, os, httpx
from pathlib import Path

CACHE_DIR = Path("cache/thumbs")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
EXISTING = set(f.stem for f in CACHE_DIR.glob("*.webp"))
print(f"已有 {len(EXISTING)} 张缩略图")

client = httpx.Client(verify=False, timeout=15)
page, total = 1, 0
downloaded = 0

while True:
    r = client.get(f"https://animadex.net/api/characters/search?page={page}&sort=count")
    if r.status_code != 200:
        break
    data = r.json()
    results = data.get("results", [])
    if not results:
        break

    for ch in results:
        url = ch.get("thumb_url", "")
        if not url:
            continue
        # Remove cache buster
        url_clean = url.split("?v=")[0] if "?v=" in url else url
        fname = hashlib.md5(url_clean.encode()).hexdigest() + ".webp"
        if fname in EXISTING:
            continue
        try:
            resp = client.get(url_clean, timeout=10)
            if resp.status_code == 200:
                (CACHE_DIR / fname).write_bytes(resp.content)
                downloaded += 1
                if downloaded % 100 == 0:
                    print(f"  已下载 {downloaded}")
        except:
            pass

    total = data.get("total", 0)
    print(f"  第 {page} 页 / 共 {data.get('pages',1)} 页", end="\r")
    page += 1

print(f"\n完成！新下载 {downloaded} 张，共 {len(list(CACHE_DIR.glob('*.webp')))} 张")
