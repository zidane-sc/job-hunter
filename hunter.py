#!/usr/bin/env python3
"""
hunter.py - Multi-Source Tech Job Radar & Scorer (20+ Platforms)
Platforms:
  - Direct ATS: AshbyHQ, Greenhouse, Lever
  - Elite Startup Hubs: Wellfound (AngelList), YC (WorkAtAStartup)
  - Web3 & Fintech: Cryptocurrency Jobs, Web3.career, CryptoJobsList
  - Singapore & APAC: NodeFlair, eFinancialCareers
  - Indonesia Local: Dealls, Kalibrr, Jobstreet, Indeed, Glints, Tech in Asia
  - Social & Community: Facebook, X/Twitter
  - Global Remote APIs: LinkedIn, Jobicy, Remotive, RemoteOK, WeWorkRemotely

Storage: SQLite (jobs.db) with strict deduplication & notification tracking.
"""

import argparse
import datetime
import email.utils
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "jobs.db"
TZ_JAKARTA = ZoneInfo("Asia/Jakarta")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                url TEXT UNIQUE NOT NULL,
                score INTEGER DEFAULT 0,
                score_reason TEXT,
                is_notified INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                notified_at TEXT,
                posted_at TEXT,
                salary TEXT,
                employment_type TEXT
            )
        """)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(jobs)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col, col_type in [("posted_at", "TEXT"), ("salary", "TEXT"), ("employment_type", "TEXT"), ("job_type", "TEXT"), ("is_skipped", "INTEGER"), ("skip_reason", "TEXT"), ("skipped_at", "TEXT")]:
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_is_notified ON jobs(is_notified)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_score ON jobs(score)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_job_type ON jobs(job_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_is_skipped ON jobs(is_skipped)")
        conn.commit()


def hash_url(url: str) -> str:
    clean = url.split("?")[0].strip()
    return hashlib.sha256(clean.encode()).hexdigest()[:16]


def get_exa_key() -> str:
    for env_path in ["/data/workspace/tools/.env", str(Path.home() / ".hermes/.env"), str(Path.home() / ".bashrc")]:
        p = Path(env_path)
        if p.exists():
            for line in p.read_text().splitlines():
                if "EXA_API_KEY=" in line:
                    val = line.split("EXA_API_KEY=", 1)[1].strip().strip('"\'')
                    if val.startswith("export "):
                        val = val.replace("export ", "").strip()
                    return val.split(" ")[0].strip('"\'')
    return os.environ.get("EXA_API_KEY", "")


def is_within_days(date_str: str, max_days: int = 30) -> bool:
    if not date_str:
        return True
    try:
        clean_d = str(date_str).replace("Z", "+00:00")
        if "T" in clean_d:
            dt = datetime.datetime.fromisoformat(clean_d)
        elif len(clean_d) == 10 and clean_d.count("-") == 2:
            dt = datetime.datetime.strptime(clean_d, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        else:
            dt = email.utils.parsedate_to_datetime(clean_d)
        now = datetime.datetime.now(datetime.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        delta = (now - dt).total_seconds()
        return -172800 <= delta <= max_days * 86400
    except Exception:
        return True


def format_date_relative(date_str: str) -> str:
    if not date_str:
        return "Tidak dicantumkan"
    try:
        clean_d = str(date_str).replace("Z", "+00:00")
        if "T" in clean_d:
            dt = datetime.datetime.fromisoformat(clean_d)
        elif len(clean_d) == 10 and clean_d.count("-") == 2:
            dt = datetime.datetime.strptime(clean_d, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        else:
            dt = email.utils.parsedate_to_datetime(clean_d)
        now = datetime.datetime.now(datetime.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        diff = now - dt
        days = diff.days
        if days <= 0:
            hours = diff.seconds // 3600
            return f"Hari ini ({hours} jam lalu)" if hours > 0 else "Hari ini"
        elif days == 1:
            return f"Kemarin ({dt.strftime('%d %b %Y')})"
        elif days > 1:
            return f"{days} hari lalu ({dt.strftime('%d %b %Y')})"
        return dt.strftime("%d %b %Y")
    except Exception:
        return str(date_str)[:10]


def format_scraped_at(iso_str: str) -> str:
    if not iso_str:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        return dt.strftime("%d %b %Y, %H:%M WIB")
    except Exception:
        return str(iso_str)[:16]


# ── 3-TIER CLASSIFICATION & SCORING ENGINE ──────────────────────────────────
def classify_job_type(title: str, text: str = "", employment_type: str = "") -> str:
    combined = f"{title} {employment_type} {text}".lower()
    # 1. Internship (Magang)
    if any(k in combined for k in [
        "intern", "internship", "magang", "praktik kerja", "pkl", "msib", "apprentice", "apprenticeship"
    ]):
        return "INTERNSHIP"
    # 2. Freelance / Part-time / Contract
    if any(k in combined for k in [
        "freelance", "part-time", "part time", "parttime", "contract", "kontrak", 
        "project-based", "project based", "hourly", "consultant"
    ]):
        return "FREELANCE_PARTTIME"
    # 3. Default: Full-time
    return "FULLTIME"


# Tech Stacks & Architecture Boosts
POS_KEYWORDS = {
    # Core Languages & Frameworks
    "golang": 25,
    "go ": 20,
    "backend": 20,
    "fullstack": 20,
    "full stack": 20,
    "software engineer": 15,
    "nodejs": 20,
    "node.js": 20,
    "node ": 20,
    "typescript": 20,
    "php": 20,
    "laravel": 20,
    "python": 15,
    "dart": 20,
    "flutter": 20,
    "kotlin": 15,
    "android": 15,
    "nextjs": 15,
    "next.js": 15,
    "react": 15,
    "vue": 10,
    # Architecture, Systems & Queues
    "distributed": 15,
    "microservice": 15,
    "clean architecture": 15,
    "kafka": 15,
    "bullmq": 15,
    "redis": 10,
    "postgresql": 10,
    "postgres": 10,
    "mysql": 10,
    "mongodb": 10,
    "elasticsearch": 15,
    "elastic": 10,
    "websocket": 10,
    "grpc": 10,
    "docker": 10,
    "kubernetes": 10,
    # Seniority / Work mode
    "remote": 15,
    "wfh": 15,
    "flexible": 15,
    "fleksibel": 15,
    "staff": 20,
    "lead": 20,
    "principal": 20,
    "senior": 10,
}

NON_TECH_REJECT = [
    "wordpress", "qa engineer", "manual tester", "quality assurance",
    "data entry", "sales", "marketing", "driver", "kurir", "spg",
    "telemarketing", "customer service", "admin gudang",
    "finance intern", "accounting intern", "hr intern", "marketing intern",
    "graphic design", "content creator", "admin intern"
]

REJECT_AI_TITLE_REGEX = re.compile(
    r"\b(ml|ai|machine learning|data science|data scientist|prompt)\s+(engineer|developer|researcher|scientist|specialist)\b|\b(ai|ml)\b\s*/\s*\b(ai|ml)\b",
    re.I
)


def score_job(title: str, company: str, location: str, extra: str = "", employment_type: str = "") -> tuple[int, str, str]:
    text = f"{title} {company} {location} {extra} {employment_type}".lower()
    title_lower = title.lower()

    jtype = classify_job_type(title, text, employment_type)

    # 1. Reject ML / AI Role Title
    if REJECT_AI_TITLE_REGEX.search(title_lower):
        return 0, "Auto-reject: ML/AI role title", jtype

    # 1b. Reject Internship (Disabled: user interning at current company)
    if jtype == "INTERNSHIP":
        return 0, "Auto-reject: Internship disabled (interning at current company)", jtype

    # 2. Reject non-tech roles
    for neg in NON_TECH_REJECT:
        if re.search(rf"\b{re.escape(neg)}\b", text):
            return 0, f"Auto-reject: matched non-tech '{neg}'", jtype

    # 3. Handle by Job Type
    if jtype == "FULLTIME":
        # Fulltime hard reject junior/entry level/fresh grad
        for neg in ["junior", "entry level", "fresh graduate"]:
            if re.search(rf"\b{re.escape(neg)}\b", text):
                return 0, f"Auto-reject: matched fulltime '{neg}'", jtype
        # Title must have software/backend/web/engineering keyword
        tech_title_keywords = [
            "engineer", "developer", "architect", "programmer", "lead", 
            "backend", "software", "sde", "sdm", "fullstack", "full stack", "web",
            "golang", "go", "php", "laravel", "nodejs", "node"
        ]
        if not any(k in title_lower for k in tech_title_keywords):
            return 0, "Title is not a software/web/backend engineering role", jtype

    elif jtype == "INTERNSHIP":
        # Internship MUST be technical (software/web/backend/developer/engineer/mobile)
        tech_intern_keywords = [
            "backend", "software", "developer", "engineer", "fullstack", "full stack",
            "web", "it intern", "tech intern", "programmer", "golang", "laravel", "node",
            "mobile", "frontend", "flutter", "android"
        ]
        if not any(k in title_lower for k in tech_intern_keywords):
            return 0, "Not a technical/software engineering internship", jtype

    elif jtype == "FREELANCE_PARTTIME":
        tech_keywords = [
            "backend", "software", "developer", "engineer", "fullstack", "full stack",
            "web", "programmer", "golang", "laravel", "node", "mobile", "frontend", "architect"
        ]
        if not any(k in title_lower for k in tech_keywords):
            return 0, "Not a software/web/backend role", jtype

    # 4. Calculate score
    score = 0
    matched_reasons = []

    # Category bonuses
    if jtype == "INTERNSHIP":
        # User invariant: "cari yang remote + flexibel ada ga ya"
        is_remote_flex = any(k in text for k in ["remote", "wfh", "fleksibel", "flexible", "online", "hybrid"])
        if is_remote_flex:
            score += 35
            matched_reasons.append("remote/flexible intern (+35)")
            if any(k in text for k in ["remote", "wfh"]):
                score += 15
                matched_reasons.append("full remote (+15)")
        else:
            score += 10
            matched_reasons.append("on-site intern")

    elif jtype == "FREELANCE_PARTTIME":
        if any(k in text for k in ["remote", "wfh", "fleksibel", "flexible"]):
            score += 25
            matched_reasons.append("remote/flexible freelance (+25)")
        else:
            score += 10

    # Tech stack matching
    for kw, points in POS_KEYWORDS.items():
        if kw in text:
            score += points
            matched_reasons.append(kw.strip())

    # Internships without remote/flexible cap at 50 to prevent notifying non-remote internships
    if jtype == "INTERNSHIP" and not any(k in text for k in ["remote", "wfh", "fleksibel", "flexible", "online"]):
        score = min(score, 50)
    else:
        score = min(score, 100)

    reason = ", ".join(matched_reasons) if matched_reasons else f"General {jtype.lower()} match"
    return score, reason, jtype


# ── NATIVE API SCRAPERS ──────────────────────────────────────────────────────

# 1. DEALLS
def scrape_dealls(query="golang", limit=50) -> list[dict]:
    url = f"https://api.sejutacita.id/v1/explore-job/job?search={urllib.parse.quote(query)}&limit={limit}"
    req = urllib.request.Request(url, headers={
        "User-Agent": HEADERS["User-Agent"],
        "Origin": "https://dealls.com",
        "Referer": "https://dealls.com/",
    })
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        for doc in data.get("data", {}).get("docs", []):
            comp = doc.get("company", {})
            cname = comp.get("name", "Unknown") if isinstance(comp, dict) else "Unknown"
            city = doc.get("city", {}).get("name", "Indonesia") if isinstance(doc.get("city"), dict) else "Indonesia"
            slug = doc.get("slug")
            wpt = doc.get("workplaceType", "onSite")
            if not slug:
                continue

            pub_date = doc.get("publishedAt") or doc.get("createdAt")
            if not is_within_days(pub_date, 30):
                continue

            skills_list = []
            if isinstance(doc.get("skills"), list):
                for s in doc.get("skills"):
                    if isinstance(s, dict):
                        skills_list.append(s.get("name", ""))
                    elif isinstance(s, str):
                        skills_list.append(s)

            salary_str = None
            sr = doc.get("salaryRange")
            if isinstance(sr, dict) and sr.get("start") and sr.get("end"):
                s_min = sr.get("start")
                s_max = sr.get("end")
                salary_str = f"IDR {s_min:,} - {s_max:,}"

            emp_types = doc.get("employmentTypes")
            emp_type_str = ", ".join(emp_types) if isinstance(emp_types, list) else None

            jobs.append({
                "source": "dealls",
                "title": doc.get("role", "Software Engineer"),
                "company": cname,
                "location": f"{city} ({wpt})",
                "url": f"https://dealls.com/loker/{slug}",
                "extra": " ".join(skills_list),
                "posted_at": pub_date,
                "salary": salary_str,
                "employment_type": emp_type_str,
            })
    except Exception as e:
        print(f"[-] Dealls scrape notice ({query}): {e}")
    return jobs


# 2. KALIBRR
def scrape_kalibrr(query="golang", limit=50) -> list[dict]:
    url = f"https://www.kalibrr.com/api/job_board/search?text={urllib.parse.quote(query)}&limit={limit}"
    req = urllib.request.Request(url, headers=HEADERS)
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        for j in data.get("jobs", []):
            comp = j.get("company", {})
            cname = comp.get("name", "Unknown") if isinstance(comp, dict) else "Unknown"
            code = comp.get("code", "") if isinstance(comp, dict) else ""
            jid = j.get("id")
            slug = j.get("slug")
            if not jid or not slug:
                continue

            pub_date = j.get("activation_date") or j.get("created_at")
            if not is_within_days(pub_date, 30):
                continue

            salary_str = None
            b_sal = j.get("base_salary")
            m_sal = j.get("maximum_salary")
            if b_sal or m_sal:
                curr = j.get("salary_currency", "IDR")
                interval = j.get("salary_interval", "month")
                if b_sal and m_sal:
                    salary_str = f"{curr} {b_sal:,} - {m_sal:,} / {interval}"
                elif b_sal:
                    salary_str = f"{curr} {b_sal:,} / {interval}"
                elif m_sal:
                    salary_str = f"Up to {curr} {m_sal:,} / {interval}"

            jobs.append({
                "source": "kalibrr",
                "title": j.get("name", ""),
                "company": cname,
                "location": "Indonesia",
                "url": f"https://www.kalibrr.com/c/{code}/jobs/{jid}/{slug}",
                "extra": (j.get("teaser") or "") + " " + " ".join(j.get("skills", [])),
                "posted_at": pub_date,
                "salary": salary_str,
                "employment_type": j.get("tenure"),
            })
    except Exception as e:
        print(f"[-] Kalibrr scrape notice ({query}): {e}")
    return jobs


# 3. LINKEDIN
def scrape_linkedin(keywords="Golang Backend", location="Indonesia", remote_only=False, pages=2) -> list[dict]:
    jobs = []
    for page in range(pages):
        start = page * 25
        params = {
            "keywords": keywords,
            "location": location,
            "start": str(start),
            "f_TPR": "r2592000"  # past 30 days
        }
        if remote_only:
            params["f_WT"] = "2"

        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[-] LinkedIn notice ({keywords} - {location} page {page+1}): {e}")
            break

        cards = html.split('<div class="base-card')
        if len(cards) <= 1:
            break

        for c in cards[1:]:
            title_m = re.search(r"base-search-card__title[^>]*>([^<]+)</h3>", c)
            company_m = re.search(r"base-search-card__subtitle[^>]*>[\s\n]*<a[^>]*>([^<]+)</a>", c) or re.search(r"base-search-card__subtitle[^>]*>([^<]+)</h4>", c)
            loc_m = re.search(r"job-search-card__location[^>]*>([^<]+)</span>", c)
            link_m = re.search(r"<a[^>]*base-card__full-link[^>]*href=\"([^\"]+)\"", c)
            time_m = re.search(r'<time[^>]*datetime="([^"]+)"[^>]*>', c)
            salary_m = re.search(r'job-search-card__salary-info[^>]*>([^<]+)</span>', c)

            if not title_m or not link_m:
                continue

            raw_link = link_m.group(1).split("?")[0].strip()
            pub_date = time_m.group(1).strip() if time_m else None
            salary_val = re.sub(r"\s+", " ", salary_m.group(1)).strip() if salary_m else None

            jobs.append({
                "source": "linkedin",
                "title": title_m.group(1).strip(),
                "company": company_m.group(1).strip() if company_m else "Unknown",
                "location": loc_m.group(1).strip() if loc_m else location,
                "url": raw_link,
                "posted_at": pub_date,
                "salary": salary_val,
                "employment_type": None,
            })
    return jobs


# 4. JOBICY
def scrape_jobicy(tag="golang", count=30) -> list[dict]:
    url = f"https://jobicy.com/api/v2/remote-jobs?tag={tag}&count={count}"
    req = urllib.request.Request(url, headers=HEADERS)
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        for j in data.get("jobs", []):
            pub_date = j.get("pubDate")
            if not is_within_days(pub_date, 30):
                continue

            salary_val = None
            if j.get("salaryMin") and j.get("salaryMax"):
                curr = j.get("salaryCurrency", "$")
                period = j.get("salaryPeriod", "year")
                salary_val = f"{curr} {j.get('salaryMin'):,} - {j.get('salaryMax'):,} / {period}"

            jobs.append({
                "source": "jobicy",
                "title": j.get("jobTitle", "").strip(),
                "company": j.get("companyName", "Unknown").strip(),
                "location": j.get("jobGeo", "Remote").strip(),
                "url": j.get("url", "").split("?")[0].strip(),
                "extra": " ".join(j.get("jobIndustry", [])) + " " + (j.get("jobExcerpt") or ""),
                "posted_at": pub_date,
                "salary": salary_val,
                "employment_type": j.get("jobType"),
            })
    except Exception as e:
        print(f"[-] Jobicy scrape notice ({tag}): {e}")
    return jobs


# 5. REMOTIVE
def scrape_remotive(search="golang") -> list[dict]:
    url = f"https://remotive.com/api/remote-jobs?category=software-dev&search={search}"
    req = urllib.request.Request(url, headers=HEADERS)
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode())
        for j in data.get("jobs", []):
            pub_date = j.get("publication_date")
            if not is_within_days(pub_date, 30):
                continue
            jobs.append({
                "source": "remotive",
                "title": j.get("title", "").strip(),
                "company": j.get("company_name", "Unknown").strip(),
                "location": j.get("candidate_required_location", "Remote").strip(),
                "url": j.get("url", "").split("?")[0].strip(),
                "extra": " ".join(j.get("tags", [])) + " " + (j.get("description") or "")[:400],
                "posted_at": pub_date,
                "salary": j.get("salary") or None,
                "employment_type": j.get("job_type"),
            })
    except Exception as e:
        print(f"[-] Remotive scrape notice ({search}): {e}")
    return jobs


# 6. REMOTEOK
def scrape_remoteok(tag="golang") -> list[dict]:
    url = f"https://remoteok.com/api?tag={tag}"
    req = urllib.request.Request(url, headers=HEADERS)
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        for item in data[1:]:
            if not item.get("position") or not item.get("url"):
                continue
            pub_date = item.get("date")
            if not is_within_days(pub_date, 30):
                continue
            salary_val = None
            if item.get("salary_min") and item.get("salary_max"):
                salary_val = f"${item.get('salary_min'):,} - ${item.get('salary_max'):,}"

            jobs.append({
                "source": "remoteok",
                "title": item.get("position", "").strip(),
                "company": item.get("company", "Unknown").strip(),
                "location": item.get("location", "Remote Worldwide").strip(),
                "url": item.get("url", "").split("?")[0].strip(),
                "extra": " ".join(item.get("tags", [])) + " " + (item.get("description") or "")[:500],
                "posted_at": pub_date,
                "salary": salary_val,
                "employment_type": None,
            })
    except Exception as e:
        print(f"[-] RemoteOK scrape notice ({tag}): {e}")
    return jobs


# 7. WEWORKREMOTELY
def scrape_weworkremotely() -> list[dict]:
    url = "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss"
    req = urllib.request.Request(url, headers=HEADERS)
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            root = ET.fromstring(r.read())
        for item in root.findall(".//item"):
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pub_elem = item.find("pubDate")

            if title_elem is None or link_elem is None:
                continue

            pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else None
            if not is_within_days(pub_date, 30):
                continue

            full_title = title_elem.text or ""
            company = "Unknown"
            title = full_title
            if ":" in full_title:
                company, title = full_title.split(":", 1)

            jobs.append({
                "source": "weworkremotely",
                "title": title.strip(),
                "company": company.strip(),
                "location": "Remote",
                "url": link_elem.text.split("?")[0].strip(),
                "extra": (desc_elem.text or "")[:500] if desc_elem is not None else "",
                "posted_at": pub_date,
                "salary": None,
                "employment_type": None,
            })
    except Exception as e:
        print(f"[-] WeWorkRemotely scrape notice: {e}")
    return jobs


# ── EXA NEURAL SEARCH CONNECTOR ──────────────────────────────────────────────
def scrape_exa_jobs(query: str, default_source: str = "web", site_filter: str = "", max_results: int = 25) -> list[dict]:
    api_key = get_exa_key()
    if not api_key:
        return []

    url = "https://api.exa.ai/search"
    full_query = f"{query} {site_filter}".strip()
    two_weeks_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)).strftime("%Y-%m-%dT00:00:00.000Z")
    payload = {
        "query": full_query,
        "numResults": max_results,
        "type": "neural",
        "startPublishedDate": two_weeks_ago
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"x-api-key": api_key, "Content-Type": "application/json"}
    )
    jobs = []
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode())
        for item in res.get("results", []):
            raw_title = item.get("title", "")
            raw_url = item.get("url", "")
            pub_date = item.get("publishedDate")
            if not raw_url or not raw_title:
                continue

            source = default_source
            u_low = raw_url.lower()
            if "ashbyhq" in u_low:
                source = "ashby"
            elif "greenhouse" in u_low:
                source = "greenhouse"
            elif "lever.co" in u_low:
                source = "lever"
            elif "wellfound" in u_low:
                source = "wellfound"
            elif "workatastartup" in u_low:
                source = "yc"
            elif "cryptocurrencyjobs" in u_low or "web3.career" in u_low or "cryptojobslist" in u_low:
                source = "web3"
            elif "nodeflair" in u_low:
                source = "nodeflair"
            elif "efinancialcareers" in u_low:
                source = "efinancial"
            elif "jobstreet" in u_low:
                source = "jobstreet"
            elif "indeed" in u_low:
                source = "indeed"
            elif "facebook" in u_low:
                source = "facebook"
            elif "glints" in u_low:
                source = "glints"
            elif "techinasia" in u_low:
                source = "techinasia"
            elif "twitter.com" in u_low or "x.com" in u_low:
                source = "twitter"
            elif "maganghub" in u_low or "kemnaker" in u_low or "kampusmerdeka" in u_low or "dinoku" in u_low:
                source = "maganghub"

            clean_title = raw_title
            company = f"Posting via {source.capitalize()}"
            if " - " in raw_title:
                parts = raw_title.split(" - ")
                if any(k in parts[-1].lower() for k in ["engineer", "developer", "hiring", "architect"]):
                    clean_title = parts[-1]
                    company = parts[0]
                else:
                    clean_title = parts[0]
                    company = parts[-1]
            if " | " in clean_title:
                clean_title = clean_title.split(" | ")[0]
            if " at " in clean_title:
                tp = clean_title.split(" at ")
                clean_title = tp[0]
                company = tp[1]
            if " @ " in clean_title:
                tp = clean_title.split(" @ ")
                clean_title = tp[0]
                company = tp[1]

            clean_title = re.sub(r"^\[.*?\]\s*", "", clean_title)
            clean_title = re.sub(r"(?i)^(we'?re\s+hiring[:\s\-]+|dicari[:\s\-]+|loker[:\s\-]+)", "", clean_title)

            jobs.append({
                "source": source,
                "title": clean_title.strip(),
                "company": company.strip(),
                "location": "Remote / Worldwide / APAC",
                "url": raw_url.split("?")[0].strip(),
                "posted_at": pub_date,
                "salary": None,
                "employment_type": None,
            })
    except Exception as e:
        print(f"[-] Exa notice for '{query[:30]}...': {e}")
    return jobs


# ── DATABASE INGEST & DEDUP ──────────────────────────────────────────────────
def ingest_jobs(jobs_list: list[dict]) -> int:
    inserted = 0
    now_iso = datetime.datetime.now(TZ_JAKARTA).isoformat()

    with get_db() as conn:
        for j in jobs_list:
            clean_url = j["url"].split("?")[0].strip()
            jid = hash_url(clean_url)
            extra = j.get("extra", "")
            emp_type = j.get("employment_type") or ""
            score, reason, jtype = score_job(j["title"], j["company"], j["location"], extra, emp_type)

            posted_at = j.get("posted_at")
            salary = j.get("salary")

            try:
                conn.execute("""
                    INSERT INTO jobs (id, source, title, company, location, url, score, score_reason, is_notified, created_at, posted_at, salary, employment_type, job_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """, (jid, j["source"], j["title"], j["company"], j["location"], clean_url, score, reason, now_iso, posted_at, salary, emp_type, jtype))
                inserted += 1
            except sqlite3.IntegrityError:
                conn.execute("""
                    UPDATE jobs 
                    SET score = ?, score_reason = ?, job_type = ?,
                        posted_at = COALESCE(posted_at, ?),
                        salary = COALESCE(salary, ?),
                        employment_type = COALESCE(employment_type, ?)
                    WHERE id = ?
                """, (score, reason, jtype, posted_at, salary, emp_type, jid))
                continue
        conn.commit()
    return inserted


def rescore_all_jobs() -> int:
    """Re-score existing jobs in DB against the new algorithm."""
    updated = 0
    with get_db() as conn:
        rows = conn.execute("SELECT id, title, company, location, employment_type, score_reason FROM jobs").fetchall()
        for r in rows:
            emp_type = r["employment_type"] or ""
            score, reason, jtype = score_job(r["title"], r["company"], r["location"] or "", r["score_reason"] or "", emp_type)
            conn.execute("UPDATE jobs SET score = ?, score_reason = ?, job_type = ? WHERE id = ?", (score, reason, jtype, r["id"]))
            updated += 1
        conn.commit()
    return updated


# ── TELEGRAM NOTIFIER ────────────────────────────────────────────────────────
def get_telegram_config():
    env_file = Path.home() / ".hermes" / ".env"
    token = None
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"\'')
    return token


def send_telegram_card(job: dict, bot_token: str, chat_id: str, thread_id: str = None) -> bool:
    source_labels = {
        "ashby": "🚀 [Ashby Direct]",
        "greenhouse": "🏢 [Greenhouse Direct]",
        "lever": "💼 [Lever Direct]",
        "wellfound": "🦄 [Wellfound / AngelList]",
        "yc": "🔶 [YC / WorkAtAStartup]",
        "web3": "🪙 [Web3 / Crypto]",
        "nodeflair": "🇸🇬 [NodeFlair SG]",
        "efinancial": "🏦 [eFinancialCareers]",
        "dealls": "🤝 [Dealls]",
        "kalibrr": "🎯 [Kalibrr]",
        "jobstreet": "🏢 [Jobstreet]",
        "indeed": "🔍 [Indeed]",
        "facebook": "👥 [Facebook]",
        "glints": "🚀 [Glints]",
        "techinasia": "🌏 [TechInAsia]",
        "twitter": "🐦 [X / Twitter]",
        "linkedin": "💼 [LinkedIn]",
        "jobicy": "🌐 [Jobicy]",
        "remotive": "💻 [Remotive]",
        "remoteok": "🌐 [RemoteOK]",
        "weworkremotely": "⚡ [WWR]",
        "maganghub": "🇮🇩 [MagangHub / Kemnaker]",
    }
    label = source_labels.get(job["source"], f"📌 [{job['source'].capitalize()}]")

    type_badges = {
        "FULLTIME": "💼 **[FULL-TIME OPPORTUNITY]**",
        "FREELANCE_PARTTIME": "⚡ **[FREELANCE / PART-TIME (FLEKSIBEL)]**",
        "INTERNSHIP": "🎓 **[INTERNSHIP / MAGANG (REMOTE / FLEKSIBEL)]**"
    }
    jtype = job.get("job_type") or classify_job_type(job["title"], job.get("score_reason", ""), job.get("employment_type", ""))
    type_badge = type_badges.get(jtype, "💼 **[FULL-TIME OPPORTUNITY]**")

    lines = [
        f"🎯 {type_badge}",
        f"**{job['title']}**",
        f"🏢 **Company**: {job['company']}",
        f"📍 **Location**: {job['location']} | {label}",
    ]

    if job.get("employment_type"):
        lines.append(f"💼 **Type**: {job['employment_type']}")

    if job.get("salary") and job["salary"] != "Not disclosed":
        lines.append(f"💰 **Salary**: `{job['salary']}`")
    else:
        lines.append(f"💰 **Salary**: _Not disclosed_")

    posted_text = format_date_relative(job.get("posted_at"))
    scraped_text = format_scraped_at(job.get("created_at"))
    lines.append(f"📅 **Posted**: {posted_text}")
    lines.append(f"🕒 **Scraped**: {scraped_text}")
    lines.append(f"🧠 **Match Score**: `{job['score']}%` ({job['score_reason']})")
    lines.append(f"🔗 [Apply / Lihat Lowongan]({job['url']})")

    text = "\n".join(lines)

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    if thread_id:
        payload["message_thread_id"] = int(thread_id)

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"[-] Telegram delivery failed: {e}")
        return False


def notify_pending(min_score: int = 60, limit: int = 10, target: str = None, filter_type: str = None) -> int:
    token = get_telegram_config()
    if not token:
        print("[-] TELEGRAM_BOT_TOKEN not found in ~/.hermes/.env")
        return 0

    chat_id = "-1004484793861"
    thread_id = "10578"
    if target:
        parts = target.replace("telegram:", "").split(":")
        chat_id = parts[0]
        if len(parts) > 1:
            thread_id = parts[1]

    notified = 0
    with get_db() as conn:
        if filter_type:
            rows = conn.execute("""
                SELECT * FROM jobs 
                WHERE is_notified = 0 AND score >= ? AND job_type = ? AND (is_skipped = 0 OR is_skipped IS NULL)
                ORDER BY score DESC, created_at DESC
                LIMIT ?
            """, (min_score, filter_type.upper(), limit)).fetchall()
        else:
            # Smart multi-tier mix: ensures FULLTIME, FREELANCE, and INTERNSHIP are all represented
            types = ["FULLTIME", "FREELANCE_PARTTIME", "INTERNSHIP"]
            collected_ids = set()
            rows = []
            per_cat_limit = max(2, limit // 3)
            for jt in types:
                cat_rows = conn.execute("""
                    SELECT * FROM jobs
                    WHERE is_notified = 0 AND score >= ? AND job_type = ? AND (is_skipped = 0 OR is_skipped IS NULL)
                    ORDER BY score DESC, created_at DESC
                    LIMIT ?
                """, (min_score, jt, per_cat_limit)).fetchall()
                for cr in cat_rows:
                    if cr["id"] not in collected_ids:
                        collected_ids.add(cr["id"])
                        rows.append(cr)
            
            # Fill remaining quota up to limit with highest overall score
            if len(rows) < limit:
                extra_rows = conn.execute("""
                    SELECT * FROM jobs
                    WHERE is_notified = 0 AND score >= ?
                    ORDER BY score DESC, created_at DESC
                    LIMIT ?
                """, (min_score, limit * 2)).fetchall()
                for er in extra_rows:
                    if er["id"] not in collected_ids:
                        collected_ids.add(er["id"])
                        rows.append(er)
                    if len(rows) >= limit:
                        break

        for row in rows:
            job = dict(row)
            success = send_telegram_card(job, token, chat_id, thread_id)
            if success:
                now_iso = datetime.datetime.now(TZ_JAKARTA).isoformat()
                conn.execute("UPDATE jobs SET is_notified = 1, notified_at = ? WHERE id = ?", (now_iso, job["id"]))
                conn.commit()
                notified += 1
                time.sleep(1.5)
    return notified


# ── FULL SWEEP PIPELINE ──────────────────────────────────────────────────────
def run_scan():
    print("[*] Running multi-source job sweep across 20+ platforms (Timerange: Past 30 Days)...")
    all_jobs = []

    # 1. Direct ATS (Ashby, Greenhouse, Lever)
    print("  ├─ [1/11] Direct ATS (AshbyHQ, Greenhouse, Lever)...")
    all_jobs.extend(scrape_exa_jobs(
        "Golang Backend Engineer remote", 
        default_source="ashby", 
        site_filter="(site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:jobs.lever.co)",
        max_results=25
    ))
    all_jobs.extend(scrape_exa_jobs(
        "Software Engineer Fullstack PHP Laravel remote", 
        default_source="ashby", 
        site_filter="(site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:jobs.lever.co)",
        max_results=20
    ))

    # 2. Elite Startups & YC (Wellfound, WorkAtAStartup)
    print("  ├─ [2/11] Elite Startup Hubs (Wellfound, YC)...")
    all_jobs.extend(scrape_exa_jobs(
        "Golang Backend Engineer remote", 
        default_source="wellfound", 
        site_filter="(site:wellfound.com/jobs OR site:workatastartup.com/companies)",
        max_results=20
    ))
    all_jobs.extend(scrape_exa_jobs(
        "Software Engineer Part-Time Fullstack remote", 
        default_source="wellfound", 
        site_filter="(site:wellfound.com/jobs OR site:workatastartup.com/companies)",
        max_results=20
    ))

    # 3. Direct ATS Flexible & High-Paying Roles
    print("  ├─ [3/11] Direct ATS Part-time & Contract (Ashby, Greenhouse, Lever)...")
    all_jobs.extend(scrape_exa_jobs(
        "Golang Backend Engineer part-time OR contract remote", 
        default_source="ashby", 
        site_filter="(site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:jobs.lever.co)",
        max_results=20
    ))

    # 4. Singapore & APAC Hub (NodeFlair, eFinancialCareers)
    print("  ├─ [4/11] Singapore & APAC Hub (NodeFlair, eFinancialCareers)...")
    all_jobs.extend(scrape_exa_jobs(
        "Golang Backend Engineer", 
        default_source="nodeflair", 
        site_filter="(site:nodeflair.com/jobs OR site:efinancialcareers.sg OR site:efinancialcareers.com)",
        max_results=20
    ))

    # 5. Indonesia Local (Dealls REST API)
    print("  ├─ [5/11] Dealls (Official REST API)...")
    for q in ["golang", "backend", "fullstack", "php", "laravel", "software engineer", "part time backend", "freelance backend"]:
        all_jobs.extend(scrape_dealls(q, limit=50))

    # 6. Indonesia Local (Kalibrr REST API)
    print("  ├─ [6/11] Kalibrr (Official REST API)...")
    for q in ["golang", "backend engineer", "fullstack", "php laravel", "part time software engineer"]:
        all_jobs.extend(scrape_kalibrr(q, limit=50))

    # 7. Jobstreet & Indeed
    print("  ├─ [7/11] Jobstreet & Indeed...")
    all_jobs.extend(scrape_exa_jobs(
        "Golang Backend Engineer developer job", 
        default_source="jobstreet", 
        site_filter="(site:id.jobstreet.com/id/job/ OR site:jobstreet.co.id/id/job/ OR site:id.indeed.com/viewjob OR site:indeed.com/viewjob)",
        max_results=25
    ))

    # 8. Glints & Tech in Asia
    print("  ├─ [8/11] Glints & Tech in Asia...")
    all_jobs.extend(scrape_exa_jobs(
        "Backend developer fullstack lowongan kerja", 
        default_source="glints", 
        site_filter="(site:glints.com/id/opportunities/jobs/ OR site:techinasia.com/jobs/)",
        max_results=25
    ))

    # 9. Social Networks (Facebook, X/Twitter)
    print("  ├─ [9/11] Social Networks (Facebook & X/Twitter)...")
    all_jobs.extend(scrape_exa_jobs("Golang backend engineer (loker OR hiring OR lowongan) site:facebook.com", default_source="facebook", max_results=20))
    all_jobs.extend(scrape_exa_jobs("Golang Backend Engineer (hiring OR loker) site:x.com", default_source="twitter", max_results=20))

    # 10. LinkedIn (ID & Global)
    print("  ├─ [10/11] LinkedIn (Guest API - Indonesia & Global Remote)...")
    all_jobs.extend(scrape_linkedin("Golang Backend", "Indonesia", pages=2))
    all_jobs.extend(scrape_linkedin("Fullstack Engineer Laravel", "Indonesia", pages=2))
    all_jobs.extend(scrape_linkedin("Software Engineer Intern", "Indonesia", pages=2))
    all_jobs.extend(scrape_linkedin("Staff Golang Backend", "Worldwide", remote_only=True, pages=2))

    # 11. Global Remote APIs (Jobicy, Remotive, RemoteOK, WWR)
    print("  ├─ [11/11] Global Remote APIs (Jobicy, Remotive, RemoteOK, WWR)...")
    all_jobs.extend(scrape_jobicy("golang", count=30))
    all_jobs.extend(scrape_jobicy("backend", count=30))
    all_jobs.extend(scrape_jobicy("fullstack", count=30))
    all_jobs.extend(scrape_remotive("golang"))
    all_jobs.extend(scrape_remotive("fullstack"))
    all_jobs.extend(scrape_remotive("laravel"))
    all_jobs.extend(scrape_remoteok("golang"))
    all_jobs.extend(scrape_remoteok("dev"))
    all_jobs.extend(scrape_weworkremotely())

    # 12. MagangHub & Remote Tech Internships (Kemnaker / Kampus Merdeka / Remote)
    print("  ├─ [12/13] MagangHub & Remote Tech Internships (Kemnaker / MagangHub / Remote)...")
    all_jobs.extend(scrape_exa_jobs(
        "MagangHub lowongan magang software engineer backend",
        default_source="maganghub",
        site_filter="(site:maganghub.id OR site:magang.kemnaker.go.id OR site:kampusmerdeka.kemdikbud.go.id OR site:dinoku.com)",
        max_results=20
    ))
    all_jobs.extend(scrape_exa_jobs(
        "lowongan magang backend software engineer web developer remote fleksibel",
        default_source="maganghub",
        max_results=20
    ))
    all_jobs.extend(scrape_exa_jobs(
        "remote software engineer intern flexible hours",
        default_source="wellfound",
        max_results=20
    ))
    all_jobs.extend(scrape_dealls("intern backend remote", limit=30))
    all_jobs.extend(scrape_dealls("intern software remote", limit=30))
    all_jobs.extend(scrape_kalibrr("intern backend remote", limit=30))

    # 13. Freelance & Part-time Remote Tech
    print("  ├─ [13/13] Freelance & Part-time Remote Roles...")
    all_jobs.extend(scrape_exa_jobs(
        "freelance contract backend developer golang laravel remote",
        default_source="web",
        site_filter="(site:apply.workable.com OR site:freelancermap.com OR site:upwork.com OR site:collective.work)",
        max_results=20
    ))
    all_jobs.extend(scrape_dealls("freelance backend", limit=30))
    all_jobs.extend(scrape_dealls("freelance fullstack", limit=30))
    all_jobs.extend(scrape_kalibrr("freelance web developer", limit=30))

    inserted = ingest_jobs(all_jobs)
    print(f"[+] Full sweep selesai. Total valid parsed: {len(all_jobs)}, Lowongan baru tersimpan: {inserted}")
    return inserted


def print_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        notified = conn.execute("SELECT COUNT(*) FROM jobs WHERE is_notified = 1").fetchone()[0]
        high_match = conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 60").fetchone()[0]
        by_source = conn.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source ORDER BY COUNT(*) DESC").fetchall()

        print("=== Multi-Source Job Radar Database Statistics ===")
        print(f"Total jobs recorded : {total}")
        print(f"High-match (>=60%)   : {high_match}")
        print(f"Already notified    : {notified}")
        print(f"Pending alert       : {max(0, high_match - notified)}")
        print(f"Active platforms    : {len(by_source)}")
        by_type = conn.execute("SELECT COALESCE(job_type, 'FULLTIME'), COUNT(*), SUM(CASE WHEN score >= 60 THEN 1 ELSE 0 END) FROM jobs GROUP BY job_type").fetchall()
        print("\nBreakdown per Opportunity Type:")
        for jt, cnt, hm in by_type:
            print(f"  • {jt:<20}: {cnt} total ({hm or 0} high-match >=60%)")
        print("\nBreakdown per source/platform:")
        for s, count in by_source:
            print(f"  • {s:<18}: {count}")


def main():
    init_db()
    parser = argparse.ArgumentParser(description="Multi-Source Tech Job Hunter (20+ Platforms)")
    parser.add_argument("--scan", action="store_true", help="Scrape new jobs from all sources")
    parser.add_argument("--notify", action="store_true", help="Send high-match jobs to Telegram")
    parser.add_argument("--target", default="telegram:-1004484793861:10578", help="Telegram destination (chat:thread)")
    parser.add_argument("--min-score", type=int, default=60, help="Minimum score to notify (default: 60)")
    parser.add_argument("--limit", type=int, default=10, help="Max jobs to notify in one run (default: 10)")
    parser.add_argument("--run", action="store_true", help="Scan and notify immediately")
    parser.add_argument("--stats", action="store_true", help="Show database stats")
    parser.add_argument("--rescore", action="store_true", help="Recalculate match scores for all recorded jobs")
    parser.add_argument("--type", choices=["fulltime", "freelance", "intern"], help="Filter notification by opportunity type")

    args = parser.parse_args()

    if args.rescore:
        c = rescore_all_jobs()
        print(f"[+] Successfully rescored {c} jobs in database.")
        print_stats()
        return

    if args.stats:
        print_stats()
        return

    if args.scan or args.run:
        run_scan()

    if args.notify or args.run:
        type_mapping = {"fulltime": "FULLTIME", "freelance": "FREELANCE_PARTTIME", "intern": "INTERNSHIP"}
        selected_type = type_mapping.get(args.type) if args.type else None
        notified = notify_pending(min_score=args.min_score, limit=args.limit, target=args.target, filter_type=selected_type)
        print(f"[+] Notified {notified} jobs to Telegram.")


if __name__ == "__main__":
    main()
