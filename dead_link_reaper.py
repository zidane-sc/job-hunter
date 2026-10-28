import sqlite3
import urllib.request
import urllib.error
import concurrent.futures
import re
import time

DB_PATH = '/data/workspace/tools/job-hunter/jobs.db'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,id;q=0.8'
}

DEAD_BODY_PATTERNS = [
    r'no longer available',
    r'job listing is no longer available',
    r'this job has expired',
    r'this position has been filled',
    r'this job is closed',
    r'no longer accepting applications',
    r'this job posting has closed',
    r'job opening is closed',
    r'this job is no longer active',
    r'404 - page not found',
    r'page not found',
    r'this role is closed',
    r'this posting has been closed',
    r'could not be found',
    r'this role has been closed',
    r'this role is no longer active',
    r'opening is no longer available',
    r'sorry, this job has expired',
    r'loker ini sudah ditutup',
    r'lowongan ini sudah tidak aktif',
    r'job is closed'
]

DEAD_REGEX = re.compile('|'.join(DEAD_BODY_PATTERNS), re.I)

def check_single_url(job_id, url):
    clean_url = url.split('?')[0].strip()
    try:
        req = urllib.request.Request(clean_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            status = resp.status
            final_url = resp.geturl()
            
            # If redirected to root domain or 404/closed page
            if final_url.rstrip('/') in ['https://wellfound.com', 'https://jobs.lever.co', 'https://www.workatastartup.com']:
                return job_id, True, f"Redirected to homepage ({status})"
                
            # Read first 25KB
            content = resp.read(25000).decode('utf-8', errors='ignore')
            m = DEAD_REGEX.search(content)
            if m:
                return job_id, True, f"Dead marker: '{m.group(0)}'"
                
            return job_id, False, "Alive"
    except urllib.error.HTTPError as e:
        if e.code in [404, 410, 500, 502, 503]:
            return job_id, True, f"HTTP {e.code}"
        # If 403 or 429, don't immediately kill unless proven dead
        return job_id, False, f"HTTP {e.code} (Keep)"
    except Exception as e:
        err_msg = str(e)
        if "Name or service not known" in err_msg or "Connection refused" in err_msg:
            return job_id, True, f"Network error: {err_msg[:40]}"
        return job_id, False, f"Timeout/Error: {err_msg[:30]}"

def run_reaper():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Skip all score=0 jobs
    c.execute("""
        UPDATE jobs 
        SET is_skipped = 1, 
            skip_reason = CASE WHEN score_reason != '' THEN score_reason ELSE 'Score 0 / Auto-rejected' END,
            skipped_at = CURRENT_TIMESTAMP
        WHERE score = 0 AND is_skipped = 0
    """)
    skipped_zero = conn.total_changes
    conn.commit()
    print(f"[*] Skipped {skipped_zero} jobs with score = 0.")
    
    # 2. Query all remaining active jobs with score > 0
    c.execute("""
        SELECT id, url, title, company, job_type 
        FROM jobs 
        WHERE is_skipped = 0 AND score > 0
    """)
    active_jobs = c.fetchall()
    print(f"[*] Checking HTTP liveness for {len(active_jobs)} active jobs with 15 concurrent threads...")
    
    dead_jobs = []
    alive_count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(check_single_url, j[0], j[1]): j for j in active_jobs}
        for future in concurrent.futures.as_completed(futures):
            job_info = futures[future]
            try:
                jid, is_dead, reason = future.result()
                if is_dead:
                    dead_jobs.append((jid, reason, job_info[2], job_info[3]))
                    print(f"[-] DEAD: [{reason}] {job_info[3]} - {job_info[2]}")
                else:
                    alive_count += 1
            except Exception as e:
                pass

    print(f"\n[*] Liveness verification complete!")
    print(f"  - Alive & working links: {alive_count}")
    print(f"  - Dead / Closed / 404 / 410: {len(dead_jobs)}")
    
    # 3. Update DB to mark dead jobs as skipped
    for jid, reason, title, comp in dead_jobs:
        c.execute("""
            UPDATE jobs 
            SET is_skipped = 1, 
                skip_reason = ?, 
                skipped_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (f"Loker Ditutup / Link 404 ({reason})", jid))
        
    conn.commit()
    
    # Breakdown of remaining active alive jobs
    c.execute("""
        SELECT job_type, COUNT(*) 
        FROM jobs 
        WHERE is_skipped = 0 AND score > 0
        GROUP BY job_type
    """)
    print("\n[+] GENUINELY ACTIVE & ALIVE JOBS IN DB:")
    for r in c.fetchall():
        print(f"  - {r[0]}: {r[1]} jobs")

if __name__ == '__main__':
    run_reaper()
