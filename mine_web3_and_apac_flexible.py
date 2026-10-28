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

# Specific queries for Web3, APAC, and Global Remote Part-time / Freelance / Intern
QUERIES = [
    # Part-time APAC & Global
    ("part-time backend engineer remote Singapore OR Indonesia OR APAC", "PART-TIME"),
    ("part-time fullstack engineer remote Singapore OR APAC", "PART-TIME"),
    ("part-time software engineer remote Australia OR New Zealand OR APAC", "PART-TIME"),
    ("part time web developer remote Southeast Asia", "PART-TIME"),
    ("part-time Go engineer remote worldwide", "PART-TIME"),
    ("part-time Node developer remote worldwide", "PART-TIME"),
    ("part-time TypeScript engineer remote worldwide", "PART-TIME"),
    
    # Freelance & Contract Web3 & Fintech
    ("contract Golang developer remote Web3 OR Crypto", "FREELANCE_CONTRACT"),
    ("freelance backend developer remote Web3 OR Fintech", "FREELANCE_CONTRACT"),
    ("contract full stack developer remote Web3 OR DeFi", "FREELANCE_CONTRACT"),
    ("contract software engineer remote Singapore OR APAC", "FREELANCE_CONTRACT"),
    ("freelance software engineer remote Indonesia", "FREELANCE_CONTRACT"),
    
    # Internship Web3, APAC, and Global
    ("software engineer intern remote Singapore OR APAC", "INTERNSHIP"),
    ("backend engineering intern remote APAC", "INTERNSHIP"),
    ("full stack developer intern remote Southeast Asia", "INTERNSHIP"),
    ("software engineering intern remote Web3 OR Crypto", "INTERNSHIP"),
]

DOMAINS = [
    'jobs.ashbyhq.com',
    'boards.greenhouse.io',
    'jobs.lever.co',
    'wellfound.com',
    'workatastartup.com',
    'web3.career',
    'cryptocurrencyjobs.co',
    'cryptojobslist.com',
    'nodeflair.com'
]

def clean_company_title(raw_title, raw_url):
    title = raw_title
    for b in [
        "| Wellfound", "• Remote (Work from Home) | Wellfound", 
        "Y Combinator's Work at a Startup", "- Greenhouse", "Ashby", 
        "Lever", "- Job Board", "Web3 Jobs", "Cryptocurrency Jobs"
    ]:
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
        if any(k in parts[0].lower() for k in ["binance", "slash", "xendit", "anyone ai", "ttec", "monad", "simplview", "voodoo", "deepgram", "grab", "crypto.com", "okx"]):
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

def run():
    log("=== RUNNING ADVANCED APAC & WEB3 FLEXIBLE MINING ===")
    existing_urls = set()
    with hunter.get_db() as conn:
        for r in conn.execute("SELECT url FROM jobs").fetchall():
            existing_urls.add(r['url'].split('?')[0].strip())
    log(f"Current existing URLs in DB: {len(existing_urls)}")
    
    candidates = []
    
    for q, intended_type in QUERIES:
        log(f"Searching Exa: '{q}' [{intended_type}]...")
        payload = {
            'query': q,
            'numResults': 15,
            'type': 'neural',
            'includeDomains': DOMAINS,
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
                
                if not raw_url or not raw_title or raw_url in existing_urls:
                    continue
                
                if raw_url.endswith('/jobs') or '/role/l/' in raw_url or raw_url.endswith('.com') or raw_url.endswith('.co') or '/categories/' in raw_url:
                    continue
                
                t_low = raw_title.lower()
                txt_low = text.lower()
                
                # Role Filter
                reject_terms = [
                    "ai trainer", "language specialist", "translator", "voice actor",
                    "marketing", "sales", "account executive", "customer support",
                    "seo", "content writer", "copywriter", "legal", "hr", "recruiter",
                    "data annotator", "data labeling", "prompt engineer", "video editor",
                    "graphic designer", "community manager", "social media", "moderator"
                ]
                if any(re.search(rf"\b{re.escape(bad)}\b", t_low) for bad in reject_terms):
                    continue
                    
                tech_terms = [
                    "engineer", "developer", "programmer", "architect", "backend",
                    "fullstack", "full stack", "full-stack", "web", "golang", "go ",
                    "node", "python", "react", "typescript", "frontend", "front-end", "sde", "intern", "smart contract"
                ]
                if not any(k in t_low for k in tech_terms):
                    continue
                    
                # Location Filter (Remote Indonesia / APAC / Global)
                geo_rejects = [
                    "latam only", "latin america only", "argentina", "mexico only", "brazil only",
                    "united states only", "us only", "usa only", "u.s. only", "canada only",
                    "uk only", "europe only", "eu only", "germany only", "onsite only", "hybrid only"
                ]
                if any(re.search(rf"\b{re.escape(bad)}\b", t_low) or re.search(rf"\b{re.escape(bad)}\b", txt_low[:350]) for bad in geo_rejects):
                    if not any(good in txt_low for good in ["indonesia", "worldwide", "everywhere", "anywhere in the world", "apac", "asia"]):
                        continue
                        
                loc = "Worldwide / Remote"
                if any(k in txt_low or k in t_low for k in ["indonesia", "jakarta", "bali", "bandung"]):
                    loc = "Remote Indonesia"
                elif any(k in txt_low or k in t_low for k in ["apac", "asia", "singapore", "malaysia"]):
                    loc = "Remote APAC"
                elif any(k in txt_low for k in ["remote", "worldwide", "everywhere", "anywhere"]):
                    loc = "Worldwide / Remote"
                else:
                    loc = "Remote / Flexible"
                    
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
            
    log(f"Verified new candidates: {len(candidates)}")
    
    # Ingest into DB
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
        
    log(f"Batch completed! Ingested new: {inserted}, Updated: {updated}")

if __name__ == '__main__':
    run()
