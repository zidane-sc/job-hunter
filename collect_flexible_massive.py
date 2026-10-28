import urllib.request
import json
import time
import re
import sys
import sqlite3

sys.path.append('/data/workspace/tools/job-hunter')
import hunter

def log(msg):
    print(f"[*] {msg}", flush=True)

api_key = hunter.get_exa_key()

queries = [
    # --- PART-TIME (HIGHEST PRIORITY) ---
    ("part-time software engineer remote", "PART-TIME"),
    ("part-time backend developer remote", "PART-TIME"),
    ("part-time fullstack engineer remote", "PART-TIME"),
    ("part-time web developer remote", "PART-TIME"),
    ("part-time golang nodejs developer remote", "PART-TIME"),
    ("part-time react typescript developer remote", "PART-TIME"),
    ("part-time software engineer remote indonesia", "PART-TIME"),
    ("part-time developer remote apac", "PART-TIME"),
    
    # --- FREELANCE & CONTRACT ---
    ("freelance software engineer remote worldwide", "FREELANCE_CONTRACT"),
    ("freelance backend developer golang remote", "FREELANCE_CONTRACT"),
    ("freelance full stack engineer remote", "FREELANCE_CONTRACT"),
    ("contract software engineer remote worldwide", "FREELANCE_CONTRACT"),
    ("contract backend engineer remote apac", "FREELANCE_CONTRACT"),
    ("contract full stack developer remote indonesia", "FREELANCE_CONTRACT"),
    
    # --- INTERNSHIP ---
    ("software engineer intern remote worldwide", "INTERNSHIP"),
    ("software engineering intern remote apac", "INTERNSHIP"),
    ("software engineer intern remote indonesia", "INTERNSHIP"),
    ("backend engineer intern remote", "INTERNSHIP"),
    ("full stack developer intern remote", "INTERNSHIP"),
]

domains = [
    'jobs.ashbyhq.com',
    'boards.greenhouse.io',
    'jobs.lever.co',
    'wellfound.com',
    'workatastartup.com'
]

def clean_company_and_title(raw_title, raw_url):
    title = raw_title
    for brand in ["| Wellfound", "• Remote (Work from Home) | Wellfound", "Y Combinator's Work at a Startup", "- Greenhouse", "Ashby", "Lever"]:
        title = title.replace(brand, "").strip()
        
    company = "Startup"
    if " at " in title:
        parts = title.split(" at ")
        title = parts[0].strip()
        company = parts[1].split("•")[0].split("·")[0].split("|")[0].strip()
    elif " @ " in title:
        parts = title.split(" @ ")
        title = parts[0].strip()
        company = parts[1].split("•")[0].split("·")[0].split("|")[0].strip()
    elif " - " in title:
        parts = title.split(" - ")
        if any(k in parts[0].lower() for k in ["binance", "slash", "xendit", "anyone ai", "ttec", "monad"]):
            company = parts[0].strip()
            title = " - ".join(parts[1:]).strip()
        elif any(k in parts[-1].lower() for k in ["engineer", "developer", "intern"]):
            company = parts[0].strip()
            title = parts[-1].strip()
        else:
            title = parts[0].strip()
            company = parts[-1].strip()
            
    if company.lower() in ["startup", "jobs", "posting via web", ""]:
        m = re.search(r'https?://(?:jobs\.)?([^/]+)\.(?:com|io|co|app)', raw_url)
        if m:
            company = m.group(1).replace('-', ' ').title()
            
    return title.strip(), company.strip()

def run():
    log("Starting massive flexible job search via Exa Neural + Multi-Source...")
    seen_urls = set()
    candidates = []
    
    # 1. Exa Searches
    for q, intended_type in queries:
        log(f"Searching Exa: '{q}' ({intended_type})...")
        payload = {
            'query': q,
            'numResults': 15,
            'type': 'neural',
            'includeDomains': domains,
            'contents': {
                'text': {'maxCharacters': 1000}
            }
        }
        req = urllib.request.Request(
            "https://api.exa.ai/search",
            data=json.dumps(payload).encode(),
            headers={'x-api-key': api_key, 'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.loads(r.read().decode())
            results = res.get('results', [])
            log(f"  Got {len(results)} items")
            for item in results:
                raw_url = item.get('url', '').split('?')[0].strip()
                raw_title = item.get('title', '')
                text = item.get('text', '')
                
                if not raw_url or not raw_title or raw_url in seen_urls:
                    continue
                seen_urls.add(raw_url)
                
                # Exclude root/directory urls
                if raw_url.endswith('/jobs') or '/role/l/' in raw_url or raw_url.endswith('.com') or raw_url.endswith('.co') or '/categories/' in raw_url:
                    continue
                
                # Check tech role validity
                t_low = raw_title.lower()
                txt_low = text.lower()
                
                # Negative filter
                if any(re.search(rf"\b{re.escape(bad)}\b", t_low) for bad in [
                    "ai trainer", "language specialist", "translator", "voice actor",
                    "marketing", "sales", "account executive", "customer support",
                    "seo", "content writer", "copywriter", "legal", "hr", "recruiter",
                    "data annotator", "data labeling", "prompt engineer", "video editor"
                ]):
                    continue
                
                # Positive tech filter
                if not any(k in t_low for k in [
                    "engineer", "developer", "programmer", "architect", "backend",
                    "fullstack", "full stack", "full-stack", "web", "golang", "node",
                    "python", "react", "typescript", "frontend", "front-end", "sde", "intern"
                ]):
                    continue
                
                # Location check: Must be remote and open to Indonesia / APAC / Worldwide
                if any(bad in t_low or bad in txt_low[:350] for bad in [
                    "latam", "latin america", "argentina", "mexico", "brazil", "colombia",
                    "united states only", "us only", "usa only", "u.s. only", "canada only",
                    "uk only", "europe only", "eu only", "germany only", "onsite", "in-office"
                ]):
                    # Except if indonesia/worldwide is explicitly allowed
                    if not any(good in txt_low for good in ["indonesia", "worldwide", "everywhere", "anywhere in the world"]):
                        continue
                        
                loc = "Worldwide / Remote"
                if "indonesia" in txt_low or "indonesia" in t_low or "jakarta" in txt_low or "bali" in txt_low:
                    loc = "Remote Indonesia"
                elif "apac" in txt_low or "asia" in txt_low or "singapore" in txt_low:
                    loc = "Remote APAC"
                
                # Determine employment type
                emp_type = intended_type
                if "intern" in t_low or "intern" in txt_low:
                    emp_type = "INTERNSHIP"
                elif "part-time" in t_low or "part time" in t_low or "part-time" in txt_low or "part time" in txt_low:
                    emp_type = "PART-TIME"
                elif "contract" in t_low or "freelance" in t_low:
                    emp_type = "FREELANCE_CONTRACT"
                    
                clean_t, clean_c = clean_company_and_title(raw_title, raw_url)
                
                candidates.append({
                    'title': clean_t,
                    'company': clean_c,
                    'location': loc,
                    'url': raw_url,
                    'employment_type': emp_type,
                    'source': 'ashby' if 'ashbyhq' in raw_url else ('greenhouse' if 'greenhouse' in raw_url else ('lever' if 'lever' in raw_url else 'wellfound')),
                    'extra': f"{clean_t} {clean_c} {loc} {emp_type} {text[:300]}"
                })
            time.sleep(0.3)
        except Exception as e:
            log(f"  Error on '{q}': {e}")
            
    log(f"Total verified candidates from Exa: {len(candidates)}")
    
    # 2. Ingest into jobs.db
    log("Ingesting into SQLite jobs.db...")
    now_iso = hunter.datetime.datetime.now(hunter.TZ_JAKARTA).isoformat()
    inserted_count = 0
    updated_count = 0
    
    with hunter.get_db() as conn:
        for c in candidates:
            clean_url = c["url"].split("?")[0].strip()
            jid = hunter.hash_url(clean_url)
            emp_type = c["employment_type"]
            score, reason, jtype = hunter.score_job(c["title"], c["company"], c["location"], c["extra"], emp_type)
            
            # Map jtype if classified as FULLTIME but we verified it's flexible
            if emp_type == "PART-TIME" or emp_type == "FREELANCE_CONTRACT":
                jtype = "FREELANCE_PARTTIME"
                if score < 50:
                    score += 50
                    reason += ", verified flexible remote"
            elif emp_type == "INTERNSHIP":
                jtype = "INTERNSHIP"
                if score < 50:
                    score += 50
                    reason += ", verified intern remote"
                    
            try:
                conn.execute("""
                    INSERT INTO jobs (id, source, title, company, location, url, score, score_reason, is_notified, created_at, employment_type, job_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """, (jid, c["source"], c["title"], c["company"], c["location"], clean_url, score, reason, now_iso, emp_type, jtype))
                inserted_count += 1
            except sqlite3.IntegrityError:
                conn.execute("""
                    UPDATE jobs
                    SET score = ?, score_reason = ?, job_type = ?, location = ?, employment_type = ?
                    WHERE id = ?
                """, (score, reason, jtype, c["location"], emp_type, jid))
                updated_count += 1
        conn.commit()
        
    log(f"Ingest complete! Inserted new: {inserted_count}, Updated existing: {updated_count}")
    
    # Summary of flexible jobs in DB
    with hunter.get_db() as conn:
        rows = conn.execute("""
            SELECT id, title, company, location, job_type, employment_type, score, url
            FROM jobs
            WHERE job_type IN ('FREELANCE_PARTTIME', 'INTERNSHIP') AND score >= 60 AND is_skipped = 0
            ORDER BY score DESC, created_at DESC
        """).fetchall()
        
        log(f"TOTAL HIGH-MATCH FLEXIBLE JOBS IN DB: {len(rows)}")
        part_times = [r for r in rows if 'part' in (r['employment_type'] or '').lower() or 'part' in r['title'].lower() or r['job_type'] == 'FREELANCE_PARTTIME']
        interns = [r for r in rows if r['job_type'] == 'INTERNSHIP']
        log(f"  - Part-time & Freelance / Contract: {len(part_times)}")
        log(f"  - Internship: {len(interns)}")

if __name__ == '__main__':
    run()
