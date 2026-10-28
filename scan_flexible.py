import os
import sys
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import time
from datetime import datetime, timezone, timedelta

sys.path.append('/data/workspace/tools/job-hunter')
import hunter

def log(msg):
    print(f"[*] {msg}", flush=True)

# 1. DEALLS API
def scan_dealls_flexible():
    log("Scanning Dealls for Part-Time, Freelance & Intern...")
    jobs = []
    queries = ["part-time", "part time", "freelance", "intern", "magang"]
    for q in queries:
        try:
            res = hunter.scrape_dealls(q, limit=50)
            log(f"  Dealls '{q}': found {len(res)}")
            jobs.extend(res)
        except Exception as e:
            log(f"  Dealls '{q}' error: {e}")
    return jobs

# 2. KALIBRR API
def scan_kalibrr_flexible():
    log("Scanning Kalibrr for Part-Time, Freelance & Intern...")
    jobs = []
    queries = ["part time", "freelance", "intern software", "intern backend"]
    for q in queries:
        try:
            res = hunter.scrape_kalibrr(q, limit=50)
            log(f"  Kalibrr '{q}': found {len(res)}")
            jobs.extend(res)
        except Exception as e:
            log(f"  Kalibrr '{q}' error: {e}")
    return jobs

# 3. WEWORKREMOTELY RSS
def scan_wwr_flexible():
    log("Scanning WeWorkRemotely for Contract / Part-Time...")
    urls = [
        'https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss',
        'https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss',
        'https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss'
    ]
    jobs = []
    for u in urls:
        try:
            req = urllib.request.Request(u, headers=hunter.HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
                for item in root.findall('.//item'):
                    title = item.find('title').text if item.find('title') is not None else ''
                    link = item.find('link').text if item.find('link') is not None else ''
                    region_el = item.find('{https://weworkremotely.com}region') or item.find('region')
                    region = region_el.text if region_el is not None else ''
                    type_el = item.find('{https://weworkremotely.com}type') or item.find('type')
                    jtype = type_el.text if type_el is not None else ''
                    pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ''
                    
                    reg_low = region.lower()
                    is_geo_ok = any(g in reg_low for g in ['anywhere in the world', 'apac', 'asia', 'worldwide', 'indonesia'])
                    
                    # Target: contract, freelance, part-time, or intern
                    t_low = jtype.lower()
                    title_low = title.lower()
                    is_type_ok = any(t in t_low for t in ['contract', 'freelance', 'part-time', 'part_time', 'intern']) or any(t in title_low for t in ['part-time', 'part time', 'contract', 'freelance', 'intern'])
                    
                    if is_geo_ok and is_type_ok:
                        comp = title.split(':')[0].strip() if ':' in title else 'WWR Partner'
                        clean_title = title.split(':', 1)[1].strip() if ':' in title else title
                        jobs.append({
                            'source': 'weworkremotely',
                            'title': clean_title,
                            'company': comp,
                            'location': region,
                            'url': link,
                            'posted_at': pub_date,
                            'employment_type': jtype,
                            'extra': f"{clean_title} {comp} {region} {jtype}"
                        })
        except Exception as e:
            log(f"  WWR error: {e}")
    log(f"  WWR flexible found: {len(jobs)}")
    return jobs

# 4. REMOTEOK API
def scan_remoteok_flexible():
    log("Scanning RemoteOK for Part-Time, Freelance & Intern...")
    jobs = []
    try:
        url = 'https://remoteok.com/api'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for j in data[1:]:
                pos = j.get('position') or ''
                loc = j.get('location') or ''
                tags = [t.lower() for t in j.get('tags', [])]
                comp = j.get('company') or 'RemoteOK Partner'
                url_job = j.get('url') or ''
                
                pos_low = pos.lower()
                loc_low = loc.lower()
                
                # Check tech
                is_eng = any(k in pos_low for k in ['engineer', 'developer', 'backend', 'full stack', 'fullstack', 'golang', 'node', 'software', 'programmer', 'web', 'frontend'])
                if not is_eng:
                    continue
                
                # Geo check: empty loc on remoteOK means worldwide!
                is_geo_ok = loc == '' or any(g in loc_low for g in ['worldwide', 'anywhere', 'indonesia', 'apac', 'asia'])
                if any(bad in loc_low for bad in ['united states', 'usa', 'us only', 'canada', 'uk only', 'europe only', 'germany', 'brazil', 'latam only']):
                    is_geo_ok = False
                
                if not is_geo_ok:
                    continue
                
                # Check employment type
                is_target_type = any(t in tags for t in ['contract', 'freelance', 'part time', 'part-time', 'intern', 'internship']) or any(t in pos_low for t in ['contract', 'freelance', 'part-time', 'part time', 'intern'])
                
                if is_target_type:
                    emp_type = 'Part-Time' if any(t in tags or t in pos_low for t in ['part time', 'part-time']) else ('Internship' if 'intern' in pos_low or 'intern' in tags else 'Contract')
                    jobs.append({
                        'source': 'remoteok',
                        'title': pos,
                        'company': comp,
                        'location': loc if loc else 'Worldwide',
                        'url': url_job,
                        'employment_type': emp_type,
                        'extra': f"{pos} {comp} {loc} {emp_type} {' '.join(tags)}"
                    })
    except Exception as e:
        log(f"  RemoteOK error: {e}")
    log(f"  RemoteOK flexible found: {len(jobs)}")
    return jobs

# 5. EXA NEURAL SEARCH
def scan_exa_targeted():
    log("Scanning Exa Neural Search for targeted Part-Time, Freelance & Intern roles...")
    jobs = []
    queries = [
        # Part-Time priorities
        ("Part-time Software Engineer remote (Indonesia OR APAC OR Worldwide)", "(site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:jobs.lever.co)", "ashby"),
        ("Part-time Backend Engineer remote (Indonesia OR APAC OR Worldwide)", "(site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:jobs.lever.co)", "ashby"),
        ("Part-time Full Stack Engineer remote (Indonesia OR APAC OR Worldwide)", "(site:wellfound.com/jobs OR site:workatastartup.com/companies)", "wellfound"),
        ("Part-time web developer remote Indonesia", "(site:wellfound.com/jobs OR site:jobs.lever.co OR site:jobs.ashbyhq.com)", "wellfound"),
        
        # Freelance / Contract
        ("Contract Software Engineer remote (Indonesia OR Worldwide)", "(site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:jobs.lever.co)", "ashby"),
        ("Freelance Backend Developer Golang Node.js remote Worldwide", "(site:jobs.ashbyhq.com OR site:jobs.lever.co OR site:boards.greenhouse.io)", "greenhouse"),
        ("Contract Full Stack Developer remote APAC OR Worldwide", "(site:wellfound.com/jobs OR site:workatastartup.com/companies)", "wellfound"),
        
        # Internships
        ("Software Engineer Intern remote (Indonesia OR APAC OR Worldwide)", "(site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:jobs.lever.co)", "ashby"),
        ("Backend Engineer Intern remote Worldwide", "(site:wellfound.com/jobs OR site:workatastartup.com/companies)", "wellfound"),
        ("Software Engineering Intern remote Indonesia", "(site:wellfound.com/jobs OR site:jobs.lever.co OR site:jobs.ashbyhq.com)", "wellfound"),
    ]
    
    for q_text, site_f, src in queries:
        try:
            res = hunter.scrape_exa_jobs(q_text, default_source=src, site_filter=site_f, max_results=15)
            log(f"  Exa '{q_text[:35]}...': found {len(res)}")
            jobs.extend(res)
            time.sleep(0.3)
        except Exception as e:
            log(f"  Exa error '{q_text}': {e}")
            
    log(f"  Exa flexible total found: {len(jobs)}")
    return jobs

def main():
    log("=== STARTING TARGETED FLEXIBLE JOB RADAR ===")
    all_scraped = []
    all_scraped.extend(scan_dealls_flexible())
    all_scraped.extend(scan_kalibrr_flexible())
    all_scraped.extend(scan_wwr_flexible())
    all_scraped.extend(scan_remoteok_flexible())
    all_scraped.extend(scan_exa_targeted())
    
    log(f"Total raw jobs collected across sources: {len(all_scraped)}")
    
    # Ingest into DB
    log("Ingesting and scoring jobs into jobs.db...")
    inserted_count = hunter.ingest_jobs(all_scraped)
    log(f"New jobs inserted or updated in jobs.db: {inserted_count}")
    
    # Query summary from DB
    conn = hunter.get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT job_type, COUNT(*) 
        FROM jobs 
        WHERE is_skipped = 0 AND score > 0
        GROUP BY job_type
    """)
    log("Active jobs in DB by job_type:")
    for row in c.fetchall():
        log(f"  - {row[0]}: {row[1]} jobs")

if __name__ == '__main__':
    main()
