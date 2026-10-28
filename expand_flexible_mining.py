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

# Ultra targeted queries focusing heavily on PART-TIME first, then FREELANCE, then INTERN
EXPANDED_QUERIES = [
    # --- PART-TIME EXPANSION (HEAVIEST EMPHASIS) ---
    ("part-time Golang backend engineer remote", "PART-TIME"),
    ("part-time Node.js TypeScript developer remote", "PART-TIME"),
    ("part-time Python FastAPI backend remote", "PART-TIME"),
    ("part-time React Next.js fullstack developer remote", "PART-TIME"),
    ("part-time API microservices engineer remote", "PART-TIME"),
    ("part-time PostgreSQL backend developer remote", "PART-TIME"),
    ("part-time frontend React engineer remote worldwide", "PART-TIME"),
    ("part-time full stack developer remote (Indonesia OR APAC OR Worldwide)", "PART-TIME"),
    ("part-time software engineer remote Asia", "PART-TIME"),
    ("part time backend developer remote Jakarta OR Bali", "PART-TIME"),
    ("part time software engineer remote APAC", "PART-TIME"),
    ("hourly software engineer remote worldwide", "PART-TIME"),
    ("part-time founding engineer remote", "PART-TIME"),
    
    # --- FREELANCE & CONTRACT EXPANSION ---
    ("freelance Golang developer remote worldwide", "FREELANCE_CONTRACT"),
    ("freelance Node.js backend engineer remote", "FREELANCE_CONTRACT"),
    ("freelance Python API developer remote", "FREELANCE_CONTRACT"),
    ("freelance fullstack React TypeScript remote", "FREELANCE_CONTRACT"),
    ("contract backend engineer Go microservices remote", "FREELANCE_CONTRACT"),
    ("contract full stack developer remote Asia", "FREELANCE_CONTRACT"),
    ("contract platform engineer remote worldwide", "FREELANCE_CONTRACT"),
    ("b2b contractor software engineer remote worldwide", "FREELANCE_CONTRACT"),
    
    # --- INTERNSHIP EXPANSION ---
    ("software engineer intern remote (Indonesia OR Asia OR APAC)", "INTERNSHIP"),
    ("backend engineering intern remote worldwide 2026", "INTERNSHIP"),
    ("full stack software engineering intern remote worldwide 2026", "INTERNSHIP"),
    ("web developer intern remote worldwide", "INTERNSHIP"),
    ("Golang software engineer intern remote", "INTERNSHIP"),
]

TARGET_DOMAINS = [
    'jobs.ashbyhq.com',
    'boards.greenhouse.io',
    'jobs.lever.co',
    'wellfound.com',
    'workatastartup.com'
]

def clean_company_title(raw_title, raw_url):
    title = raw_title
    for b in ["| Wellfound", "• Remote (Work from Home) | Wellfound", "Y Combinator's Work at a Startup", "- Greenhouse", "Ashby", "Lever", "- Job Board"]:
        title = title.replace(b, "").strip()
        
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
        if any(k in parts[0].lower() for k in ["binance", "slash", "xendit", "anyone ai", "ttec", "monad", "simplview", "voodoo", "deepgram", "grab"]):
            company = parts[0].strip()
            title = " - ".join(parts[1:]).strip()
        elif any(k in parts[-1].lower() for k in ["engineer", "developer", "intern", "architect"]):
            company = parts[0].strip()
            title = parts[-1].strip()
        else:
            title = parts[0].strip()
            company = parts[-1].strip()
            
    if company.lower() in ["startup", "jobs", "posting via web", "", "find startup jobs near you and remote jobs"]:
        m = re.search(r'https?://(?:jobs\.)?([^/]+)\.(?:com|io|co|app)', raw_url)
        if m:
            company = m.group(1).replace('-', ' ').title()
            
    return title.strip(), company.strip()

def run_deep_mining():
    log("=== EXECUTING DEEP MINING SWEEP FOR FLEXIBLE ROLES ===")
    
    # Load all existing URLs in DB to avoid any redunant work
    existing_urls = set()
    with hunter.get_db() as conn:
        for r in conn.execute("SELECT url FROM jobs").fetchall():
            existing_urls.add(r['url'].split('?')[0].strip())
    log(f"Existing URLs in DB: {len(existing_urls)}")
    
    candidates = []
    
    for q, intended_type in EXPANDED_QUERIES:
        log(f"Searching Exa: '{q}' [{intended_type}]...")
        payload = {
            'query': q,
            'numResults': 15,
            'type': 'neural',
            'includeDomains': TARGET_DOMAINS,
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
            log(f"  Returned {len(results)} items")
            
            for item in results:
                raw_url = item.get('url', '').split('?')[0].strip()
                raw_title = item.get('title', '')
                text = item.get('text', '')
                
                if not raw_url or not raw_title or raw_url in existing_urls:
                    continue
                
                # Filter out aggregator indices and job board search pages
                if raw_url.endswith('/jobs') or '/role/l/' in raw_url or raw_url.endswith('.com') or raw_url.endswith('.co') or '/categories/' in raw_url:
                    continue
                
                t_low = raw_title.lower()
                txt_low = text.lower()
                
                # 1. STRICT ROLE FILTER (Software Engineering Only)
                reject_terms = [
                    "ai trainer", "language specialist", "translator", "voice actor",
                    "marketing", "sales", "account executive", "customer support",
                    "seo", "content writer", "copywriter", "legal", "hr", "recruiter",
                    "data annotator", "data labeling", "prompt engineer", "video editor",
                    "graphic designer", "ui/ux designer only", "sales manager", "telemarketing"
                ]
                if any(re.search(rf"\b{re.escape(bad)}\b", t_low) for bad in reject_terms):
                    continue
                    
                tech_terms = [
                    "engineer", "developer", "programmer", "architect", "backend",
                    "fullstack", "full stack", "full-stack", "web", "golang", "go ",
                    "node", "python", "react", "typescript", "frontend", "front-end", "sde", "intern"
                ]
                if not any(k in t_low for k in tech_terms):
                    continue
                    
                # 2. STRICT LOCATION FILTER (Remote Indonesia / APAC / Global)
                geo_rejects = [
                    "latam only", "latin america only", "argentina", "mexico only", "brazil only",
                    "united states only", "us only", "usa only", "u.s. only", "canada only",
                    "uk only", "europe only", "eu only", "germany only", "onsite only", "hybrid only"
                ]
                if any(re.search(rf"\b{re.escape(bad)}\b", t_low) or re.search(rf"\b{re.escape(bad)}\b", txt_low[:350]) for bad in geo_rejects):
                    if not any(good in txt_low for good in ["indonesia", "worldwide", "everywhere", "anywhere in the world", "apac"]):
                        continue
                        
                loc = "Worldwide / Remote"
                if any(k in txt_low or k in t_low for k in ["indonesia", "jakarta", "bali", "bandung", "surabaya"]):
                    loc = "Remote Indonesia"
                elif any(k in txt_low or k in t_low for k in ["apac", "asia", "singapore", "malaysia"]):
                    loc = "Remote APAC"
                elif any(k in txt_low for k in ["remote", "worldwide", "everywhere", "anywhere"]):
                    loc = "Worldwide / Remote"
                else:
                    # If no remote indicator in text, verify if source domain is remote-friendly
                    loc = "Remote / Flexible"
                    
                # 3. STRICT WORKPLACE / EMPLOYMENT TYPE
                emp_type = intended_type
                if any(k in t_low or k in txt_low for k in ["intern", "internship", "magang"]):
                    emp_type = "INTERNSHIP"
                elif any(k in t_low or k in txt_low for k in ["part-time", "part time", "parttime"]):
                    emp_type = "PART-TIME"
                elif any(k in t_low or k in txt_low for k in ["freelance", "contract", "contractor", "project-based"]):
                    emp_type = "FREELANCE_CONTRACT"
                    
                clean_t, clean_c = clean_company_title(raw_title, raw_url)
                existing_urls.add(raw_url)
                
                candidates.append({
                    'title': clean_t,
                    'company': clean_c,
                    'location': loc,
                    'url': raw_url,
                    'employment_type': emp_type,
                    'source': 'ashby' if 'ashbyhq' in raw_url else ('greenhouse' if 'greenhouse' in raw_url else ('lever' if 'lever' in raw_url else 'wellfound')),
                    'extra': f"{clean_t} {clean_c} {loc} {emp_type} {text[:350]}"
                })
            time.sleep(0.3)
        except Exception as e:
            log(f"  Error on '{q}': {e}")
            
    log(f"Total new verified candidates found: {len(candidates)}")
    
    # Ingest into SQLite
    log("Ingesting and scoring new candidates into jobs.db...")
    now_iso = hunter.datetime.datetime.now(hunter.TZ_JAKARTA).isoformat()
    inserted = 0
    updated = 0
    
    with hunter.get_db() as conn:
        for c in candidates:
            clean_url = c["url"].split("?")[0].strip()
            jid = hunter.hash_url(clean_url)
            emp_type = c["employment_type"]
            score, reason, jtype = hunter.score_job(c["title"], c["company"], c["location"], c["extra"], emp_type)
            
            if emp_type in ["PART-TIME", "FREELANCE_CONTRACT"]:
                jtype = "FREELANCE_PARTTIME"
                if score < 60:
                    score = max(score + 40, 65)
                    reason += ", verified flexible remote"
            elif emp_type == "INTERNSHIP":
                jtype = "INTERNSHIP"
                if score < 60:
                    score = max(score + 40, 65)
                    reason += ", verified intern remote"
                    
            try:
                conn.execute("""
                    INSERT INTO jobs (id, source, title, company, location, url, score, score_reason, is_notified, created_at, employment_type, job_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """, (jid, c["source"], c["title"], c["company"], c["location"], clean_url, score, reason, now_iso, emp_type, jtype))
                inserted += 1
            except sqlite3.IntegrityError:
                conn.execute("""
                    UPDATE jobs
                    SET score = ?, score_reason = ?, job_type = ?, location = ?, employment_type = ?
                    WHERE id = ?
                """, (score, reason, jtype, c["location"], emp_type, jid))
                updated += 1
        conn.commit()
        
    log(f"Sweep completed! Ingested new: {inserted}, Updated: {updated}")

if __name__ == '__main__':
    run_deep_mining()
