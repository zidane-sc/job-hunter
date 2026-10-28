# 🎯 Job Hunter & Career Radar

> **High-Performance Multi-Source Job Radar, Liveness Auditor, and Application Tracker Dashboard.**  
> Self-hosted, zero external runtime dependencies (Python standard library + SQLite), designed to run lightweight (<5MB RAM) 24/7 on Linux / HP 1000 Server.

---

## 🚀 Overview

Job Hunter solves the biggest problem with public tech job boards: **stale postings, irrelevant roles, fake remote tags, and chaotic application tracking.**

It continuously scrapes, dedupes, scores, and tracks software engineering opportunities across 20+ sources, filtering strictly for **Remote Indonesia, APAC, and Global Worldwide** roles, while maintaining a real-time Kanban pipeline with outreach logging.

### ✨ Key Features
- **Zero-Dependency Architecture**: Built using pure Python standard library (`http.server`, `sqlite3`, `urllib`, `concurrent.futures`). No heavy frameworks (FastAPI/Django/Node) needed.
- **3-Tier Suitability Scoring**: Evaluates stack alignment (Go, Node.js/TypeScript, Python, PostgreSQL, React, Clean Architecture) and penalizes non-engineering / irrelevant tech.
- **Strict Geo & Workplace Filters**: Rejects US/EU-only walled gardens disguised as "Remote Everywhere".
- **Dead Link Reaper**: Automated concurrent HTTP checker that marks HTTP 404, 410, and expired listings as skipped.
- **Interactive Web Dashboard**: Single-page application with Kanban board, search filters, outreach tracker, activity audit logs, and one-click Skip/Track buttons.
- **Agentic / Headless Ready**: Modular Python API (`hunter.py`) ready to be invoked by autonomous AI agents (Hermes, Claude Code, cron jobs).

---

## 📂 Project Structure

```text
job-hunter/
├── hunter.py                     # Core radar engine, scraper, and scoring logic
├── server.py                     # HTTP REST API server (port 8095)
├── dead_link_reaper.py           # Multi-threaded HTTP liveness verifier
├── schema.sql                    # Complete SQLite schema definition
├── static/
│   └── index.html                # Modern Tailwind CSS SPA frontend dashboard
├── systemd/
│   └── job-tracker.service       # Systemd user service unit definition
├── .env.example                  # Environment variables template
├── .gitignore                    # Local databases and logs ignored
└── README.md                     # Documentation
```

---

## 🗄️ Database Schema (`jobs.db`)

The SQLite database contains 3 core tables:

### 1. `jobs` (Scraped & Scored Listings)
Stores every unique discovered opportunity with deduplication based on clean URL SHA-256 hash.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `TEXT PRIMARY KEY` | 16-character SHA-256 hash of normalized URL |
| `source` | `TEXT NOT NULL` | Scraper source (`ashby`, `greenhouse`, `lever`, `wellfound`, `linkedin`, etc.) |
| `title` | `TEXT NOT NULL` | Job title |
| `company` | `TEXT NOT NULL` | Company name |
| `location` | `TEXT` | Geographical constraint or Remote status |
| `url` | `TEXT UNIQUE NOT NULL` | Direct job application URL |
| `score` | `INTEGER DEFAULT 0` | Match score (0 to 100) |
| `score_reason` | `TEXT` | Keywords matched and scoring breakdown |
| `is_notified` | `INTEGER DEFAULT 0` | 1 if sent to Telegram, 0 otherwise |
| `created_at` | `TEXT NOT NULL` | ISO timestamp when ingested |
| `posted_at` | `TEXT` | Original post date if available |
| `salary` | `TEXT` | Stated compensation / rate |
| `employment_type`| `TEXT` | `Full-time`, `Part-Time`, `Contract`, `Internship` |
| `job_type` | `TEXT` | `FULLTIME`, `FREELANCE_PARTTIME`, `INTERNSHIP` |
| `is_skipped` | `INTEGER DEFAULT 0`| 1 if skipped / disqualified, 0 if active |
| `skip_reason` | `TEXT` | Reason why marked as skipped |
| `skipped_at` | `TEXT` | Timestamp when skipped |

### 2. `applications` (Personal Pipeline Tracker)
Tracks active job applications across their hiring lifecycle.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Unique application ID |
| `job_id` | `TEXT REFERENCES jobs(id)` | Associated job ID |
| `company` | `TEXT NOT NULL` | Target company |
| `role` | `TEXT NOT NULL` | Target role |
| `job_url` | `TEXT` | Link to job description |
| `salary_or_rate`| `TEXT` | Expected compensation / agreed rate |
| `job_type` | `TEXT DEFAULT 'FULLTIME'` | `FULLTIME`, `FREELANCE_PARTTIME`, `INTERNSHIP` |
| `status` | `TEXT DEFAULT 'applied'` | `wishlist`, `applied`, `screening`, `interview_1`, `interview_2`, `offering`, `rejected`, `withdrawn` |
| `outreach_status`| `TEXT DEFAULT 'none'` | `none`, `sent`, `connected`, `replied`, `ghosted` |
| `outreach_contacts`| `TEXT DEFAULT '[]'` | JSON array of contacted recruiters/engineers |
| `applied_date` | `TEXT` | Date submitted (YYYY-MM-DD) |
| `last_activity`| `TEXT` | Last updated date |
| `notes` | `TEXT` | Strategy notes, interview feedback, links |
| `created_at` | `TEXT NOT NULL` | Created timestamp |
| `updated_at` | `TEXT NOT NULL` | Last modified timestamp |

### 3. `activity_logs` (Audit Trail)
Immutable chronological event log for every action taken across applications.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Log event ID |
| `application_id`| `INTEGER REFERENCES applications(id)` | Associated application |
| `company` | `TEXT` | Company name |
| `role` | `TEXT` | Role name |
| `event_type` | `TEXT NOT NULL` | `created`, `status_change`, `outreach_sent`, `outreach_reply`, `custom` |
| `title` | `TEXT NOT NULL` | Log headline |
| `details` | `TEXT` | Log body / context |
| `created_at` | `TEXT NOT NULL` | Event timestamp |

---

## 🛠️ How to Run

### 1. Prerequisites
- Python 3.10+ (Standard library only, no `pip install` required)
- Optional: `EXA_API_KEY` in `.env` for neural search across direct ATS endpoints.

### 2. Quick Start (Manual Execution)
```bash
# Clone the repository
git clone https://github.com/zidane-sc/job-hunter.git
cd job-hunter

# Start the Web UI Server on port 8095
python3 server.py 8095
```
Open your browser at: `http://localhost:8095` (or `http://YOUR_SERVER_IP:8095`).

### 3. Running Scraper Manually
```bash
# Run multi-source radar sweep
python3 hunter.py --scan

# Re-score all existing jobs
python3 hunter.py --rescore

# View statistics
python3 hunter.py --stats
```

### 4. Running Dead Link Reaper
```bash
# Verify HTTP status codes and prune 404/410/expired links
python3 dead_link_reaper.py
```

### 5. Running as a Systemd Background Service (Linux Server)
To keep the server running 24/7 with automatic restart:
```bash
mkdir -p ~/.config/systemd/user/
cp systemd/job-tracker.service ~/.config/systemd/user/

# Enable and start service
systemctl --user daemon-reload
systemctl --user enable --now job-tracker.service

# Check status
systemctl --user status job-tracker.service
```

---

## 🤖 How to Prompt an AI / Agent to Scrape Jobs

You can instruct an AI agent (such as **Hermes**, **Claude Code**, or a scheduled **cron job**) to search, verify, and ingest jobs automatically into `jobs.db`.

### 📋 Standard Instruction Template for AI
Copy and send this prompt to your AI agent:

```text
Tolong carikan lowongan kerja baru untuk job tracker dengan kriteria ketat berikut:

1. Jenis Pekerjaan:
   - Prioritas 1: Part-Time (fleksibel jam kerja / asinkron)
   - Prioritas 2: Freelance / B2B Contractor
   - Prioritas 3: Internship (Magang untuk mahasiswa semester akhir)

2. Batasan Lokasi & Workplace:
   - Wajib 100% REMOTE.
   - Terbuka untuk domisili: Indonesia, APAC (Singapore/Malaysia), atau Worldwide / Global.
   - DILARANG menginput lowongan yang mewajibkan US/EU Citizen, visa kerja AS, atau "US Only".

3. Batasan Role & Tech Stack:
   - Role: Backend Engineer, Full-Stack Engineer, atau Software Engineer.
   - Tech Stack: Golang, Node.js / TypeScript, PostgreSQL, React / Next.js, Distributed Systems.
   - REJECT: Web3/Crypto tokenomics, pure Java/Spring, C#/.NET, pure Python Data Science/ML research, mobile native murni (Flutter/Android/iOS), sales, marketing, dan QA manual.

4. Verifikasi Link:
   - Pastikan link aktif (HTTP 200), bukan lowongan kadaluarsa (HTTP 404/410/Closed).

5. Format Penyimpanan:
   - Ingest langsung ke SQLite /data/workspace/tools/job-hunter/jobs.db menggunakan helper Python:
     from hunter import ingest_jobs
     ingest_jobs([
       {
         "source": "wellfound", # atau ashby, greenhouse, lever, weworkremotely
         "title": "Title",
         "company": "Company Name",
         "location": "Worldwide / Remote",
         "url": "https://...",
         "employment_type": "Part-Time", # atau Contract, Internship
         "salary": "$30/hr",
         "extra": "Keywords context..."
       }
     ])
```

---

## 🛡️ License

MIT License © 2026 Muhammad Zidane Sc. Built for personal autonomy and engineering career acceleration.
