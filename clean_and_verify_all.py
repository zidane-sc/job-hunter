import sqlite3
import re
import urllib.request
import urllib.error
import concurrent.futures

DB_PATH = '/data/workspace/tools/job-hunter/jobs.db'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9,id;q=0.8'
}

def clean_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Skip Wellfound jobs with IDs < 4700000 (they are all stale / >1 month old and closed)
    c.execute("SELECT id, url, title, company FROM jobs WHERE url LIKE '%wellfound.com/jobs/%' AND is_skipped = 0")
    wf_jobs = c.fetchall()
    wf_skipped = 0
    for jid, url, title, comp in wf_jobs:
        m = re.search(r'/jobs/(\d+)', url)
        if m and int(m.group(1)) < 4700000:
            c.execute("""
                UPDATE jobs 
                SET is_skipped = 1, skip_reason = 'Lowongan Lama / Ditutup (Wellfound ID Expired)', skipped_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (jid,))
            wf_skipped += 1
    conn.commit()
    print(f"[*] Skipped {wf_skipped} stale Wellfound jobs (< 4.7M ID).")

    # 2. Skip all Nodeflair jobs that are 404
    c.execute("SELECT id, url FROM jobs WHERE source = 'nodeflair' AND is_skipped = 0")
    nf_jobs = c.fetchall()
    nf_skipped = 0
    for jid, url in nf_jobs:
        c.execute("""
            UPDATE jobs 
            SET is_skipped = 1, skip_reason = 'Nodeflair job expired / 404', skipped_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (jid,))
        nf_skipped += 1
    conn.commit()
    print(f"[*] Skipped {nf_skipped} stale Nodeflair jobs.")

    # 3. Check liveness on all remaining active jobs
    c.execute("""
        SELECT id, url, title, company, job_type 
        FROM jobs 
        WHERE is_skipped = 0 AND score > 0
    """)
    remaining = c.fetchall()
    print(f"[*] Checking HTTP liveness on remaining {len(remaining)} jobs...")
    
    def check_liveness(row):
        jid, url, title, comp, jtype = row
        clean_url = url.split('?')[0].strip()
        try:
            req = urllib.request.Request(clean_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=6) as resp:
                content = resp.read(25000).decode('utf-8', errors='ignore')
                final_url = resp.geturl()
                
                # Check redirect
                if final_url.rstrip('/') in ['https://wellfound.com', 'https://jobs.lever.co', 'https://www.workatastartup.com']:
                    return jid, True, f"Redirect to home ({resp.status})"
                    
                dead_markers = [
                    'no longer available', 'job listing is no longer available',
                    'this position has been filled', 'this job has expired',
                    'this job is closed', 'no longer accepting applications',
                    'this job posting has closed', 'job opening is closed',
                    'this job is no longer active', '404 - page not found',
                    'could not be found', 'page not found', 'this posting has been closed',
                    'this role is closed', 'this role has been closed'
                ]
                for dm in dead_markers:
                    if dm in content.lower():
                        return jid, True, f"Dead text: '{dm}'"
                return jid, False, "Alive"
        except urllib.error.HTTPError as e:
            if e.code in [404, 410]:
                return jid, True, f"HTTP {e.code}"
            return jid, False, f"HTTP {e.code}"
        except Exception as e:
            return jid, False, f"Err: {str(e)[:25]}"

    dead_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(check_liveness, r): r for r in remaining}
        for f in concurrent.futures.as_completed(futures):
            jid, is_dead, reason = f.result()
            if is_dead:
                c.execute("""
                    UPDATE jobs 
                    SET is_skipped = 1, skip_reason = ?, skipped_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (f"Loker Ditutup / Link 404 ({reason})", jid))
                dead_count += 1
                
    conn.commit()
    print(f"[*] Liveness check complete! Marked {dead_count} dead jobs as skipped.")

    # 4. Final summary of strictly active, alive jobs
    c.execute("""
        SELECT job_type, COUNT(*) 
        FROM jobs 
        WHERE is_skipped = 0 AND score > 0
        GROUP BY job_type
    """)
    print("\n[+] GENUINELY ACTIVE, ALIVE & TESTED JOBS:")
    for r in c.fetchall():
        print(f"  - {r[0]}: {r[1]} jobs")

if __name__ == '__main__':
    clean_database()
