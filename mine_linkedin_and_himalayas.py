import urllib.request
import urllib.parse
import json
import time
import re
import sys
import sqlite3

sys.path.append('/data/workspace/tools/job-hunter')
import hunter

def log(msg):
    print(f"[*] {msg}", flush=True)

# 1. LINKEDIN GUEST SCRAPER
def scrape_linkedin_filtered(keywords, location, job_type_code, max_pages=3):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9,id;q=0.8'
    }
    jobs = []
    emp_type_label = "PART-TIME" if job_type_code == "P" else ("FREELANCE_CONTRACT" if job_type_code == "C" else "INTERNSHIP")
    
    for page in range(max_pages):
        start = page * 25
        params = {
            'keywords': keywords,
            'location': location,
            'f_WT': '2',          # Remote only
            'f_JT': job_type_code, # P=Part-time, C=Contract, I=Internship
            'f_TPR': 'r2592000',  # past 30 days
            'start': str(start)
        }
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                html = r.read().decode('utf-8', errors='ignore')
            cards = html.split('<div class="base-card')
            if len(cards) <= 1:
                break
                
            for c in cards[1:]:
                title_m = re.search(r'base-search-card__title[^>]*>([^<]+)</h3>', c)
                comp_m = re.search(r'base-search-card__subtitle[^>]*>[\s\n]*<a[^>]*>([^<]+)</a>', c) or re.search(r'base-search-card__subtitle[^>]*>([^<]+)</h4>', c)
                loc_m = re.search(r'job-search-card__location[^>]*>([^<]+)</span>', c)
                link_m = re.search(r'<a[^>]*base-card__full-link[^>]*href=\"([^\"]+)\"', c)
                time_m = re.search(r'<time[^>]*datetime="([^"]+)"[^>]*>', c)
                
                if not title_m or not link_m:
                    continue
                    
                title = title_m.group(1).strip()
                company = comp_m.group(1).strip() if comp_m else "Company via LinkedIn"
                loc = loc_m.group(1).strip() if loc_m else location
                raw_url = link_m.group(1).split('?')[0].strip()
                pub_date = time_m.group(1).strip() if time_m else None
                
                # Check tech filter
                t_low = title.lower()
                if any(bad in t_low for bad in ["sales", "marketing", "account executive", "recruiter", "hr", "customer service", "data analyst", "business analyst", "seo"]):
                    continue
                if not any(k in t_low for k in ["engineer", "developer", "programmer", "backend", "fullstack", "full stack", "web", "software", "golang", "node"]):
                    continue
                    
                jobs.append({
                    'source': 'linkedin',
                    'title': title,
                    'company': company,
                    'location': f"{loc} (Remote)",
                    'url': raw_url,
                    'posted_at': pub_date,
                    'employment_type': emp_type_label,
                    'extra': f"{title} {company} {loc} {emp_type_label} remote"
                })
            time.sleep(0.5)
        except Exception as e:
            log(f"  LinkedIn notice ({keywords} {location} p{page}): {e}")
            break
            
    return jobs

# 2. HIMALAYAS API PAGINATION
def scrape_himalayas_targeted(max_pages=20):
    log("Scanning Himalayas API for Worldwide / APAC / Indonesia flexible roles...")
    jobs = []
    limit = 50
    offset = 0
    keywords = ['engineer', 'developer', 'backend', 'full stack', 'fullstack', 'golang', 'node', 'software', 'programmer', 'web', 'typescript', 'react']
    
    for page in range(max_pages):
        url = f"https://himalayas.app/jobs/api?limit={limit}&offset={offset}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                job_list = data.get('jobs', [])
                if not job_list:
                    break
                    
                for j in job_list:
                    title = j.get('title', '')
                    emp_type = j.get('employmentType', '')
                    locs = [l.lower() for l in j.get('locationRestrictions', [])]
                    
                    # Must be flexible
                    is_target_type = emp_type in ['Part-time', 'Contractor', 'Internship'] or any(k in title.lower() for k in ['part-time', 'part time', 'contract', 'intern'])
                    if not is_target_type:
                        continue
                        
                    # Must be tech
                    is_eng = any(k in title.lower() for k in keywords) and not any(bad in title.lower() for bad in ['sales', 'marketing', 'support', 'writer', 'seo', 'recruiter'])
                    if not is_eng:
                        continue
                        
                    # Must be open to ID / APAC / Worldwide
                    is_geo_ok = len(locs) == 0 or any(g in locs for g in ['worldwide', 'anywhere', 'indonesia', 'apac', 'asia', 'singapore'])
                    if any(bad in ' '.join(locs) for bad in ['united states', 'usa', 'canada', 'uk', 'germany', 'france', 'latin america']):
                        if not any(good in locs for good in ['indonesia', 'apac', 'worldwide']):
                            is_geo_ok = False
                            
                    if is_geo_ok:
                        mapped_type = "PART-TIME" if emp_type == "Part-time" or "part" in title.lower() else ("INTERNSHIP" if emp_type == "Internship" or "intern" in title.lower() else "FREELANCE_CONTRACT")
                        loc_str = "Worldwide / Remote" if len(locs) == 0 else ', '.join(j.get('locationRestrictions', []))
                        app_link = j.get('applicationLink') or f"https://himalayas.app/companies/{j.get('companySlug')}/jobs/{j.get('guid')}"
                        
                        jobs.append({
                            'source': 'himalayas',
                            'title': title,
                            'company': j.get('companyName') or 'Himalayas Partner',
                            'location': loc_str,
                            'url': app_link,
                            'posted_at': j.get('pubDate'),
                            'employment_type': mapped_type,
                            'salary': f"{j.get('currency')} {j.get('minSalary')}-{j.get('maxSalary')}/{j.get('salaryPeriod')}" if j.get('minSalary') else None,
                            'extra': f"{title} {j.get('companyName')} {loc_str} {mapped_type}"
                        })
            offset += limit
            time.sleep(0.2)
        except Exception as e:
            log(f"  Himalayas error p{page}: {e}")
            break
            
    log(f"Himalayas flexible found: {len(jobs)}")
    return jobs

def main():
    log("=== RUNNING LINKEDIN + HIMALAYAS ADVANCED EXPANSION ===")
    existing_urls = set()
    with hunter.get_db() as conn:
        for r in conn.execute("SELECT url FROM jobs").fetchall():
            existing_urls.add(r['url'].split('?')[0].strip())
    log(f"Current existing URLs in DB: {len(existing_urls)}")
    
    collected = []
    
    # 1. LinkedIn searches (Focus on Part-time first, then Contract & Intern)
    li_targets = [
        # Keywords, Location, TypeCode (P=Part-time, C=Contract, I=Internship)
        ("Backend Engineer", "Indonesia", "P"),
        ("Full Stack Engineer", "Indonesia", "P"),
        ("Software Engineer", "Indonesia", "P"),
        ("Golang Developer", "Indonesia", "P"),
        ("Node.js Developer", "Indonesia", "P"),
        
        ("Software Engineer", "Singapore", "P"),
        ("Backend Engineer", "Singapore", "P"),
        ("Full Stack Developer", "Singapore", "P"),
        
        ("Backend Engineer", "Indonesia", "C"),
        ("Full Stack Developer", "Indonesia", "C"),
        ("Golang Engineer", "Indonesia", "C"),
        
        ("Software Engineer", "Indonesia", "I"),
        ("Backend Engineer", "Indonesia", "I"),
        ("Full Stack Developer", "Indonesia", "I"),
    ]
    
    for kw, loc, tc in li_targets:
        log(f"Scraping LinkedIn: '{kw}' in {loc} [TypeCode: {tc}]...")
        res = scrape_linkedin_filtered(kw, loc, tc, max_pages=2)
        log(f"  LinkedIn returned: {len(res)} jobs")
        for item in res:
            if item['url'] not in existing_urls:
                existing_urls.add(item['url'])
                collected.append(item)
                
    # 2. Himalayas targeted scan
    hima_res = scrape_himalayas_targeted(max_pages=25)
    for item in hima_res:
        if item['url'] not in existing_urls:
            existing_urls.add(item['url'])
            collected.append(item)
            
    log(f"Total new unique flexible jobs collected: {len(collected)}")
    
    # 3. Ingest into jobs.db
    now_iso = hunter.datetime.datetime.now(hunter.TZ_JAKARTA).isoformat()
    inserted = 0
    updated = 0
    with hunter.get_db() as conn:
        for c in collected:
            clean_url = c["url"].split("?")[0].strip()
            jid = hunter.hash_url(clean_url)
            emp_type = c["employment_type"]
            score, reason, jtype = hunter.score_job(c["title"], c["company"], c["location"], c.get("extra", ""), emp_type)
            
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
                    INSERT INTO jobs (id, source, title, company, location, url, score, score_reason, is_notified, created_at, employment_type, job_type, salary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """, (jid, c["source"], c["title"], c["company"], c["location"], clean_url, score, reason, now_iso, emp_type, jtype, c.get("salary")))
                inserted += 1
            except sqlite3.IntegrityError:
                conn.execute("""
                    UPDATE jobs
                    SET score = ?, score_reason = ?, job_type = ?, location = ?, employment_type = ?, salary = COALESCE(salary, ?)
                    WHERE id = ?
                """, (score, reason, jtype, c["location"], emp_type, c.get("salary"), jid))
                updated += 1
        conn.commit()
        
    log(f"Ingest complete! New: {inserted}, Updated: {updated}")

if __name__ == '__main__':
    main()
