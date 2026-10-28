#!/usr/bin/env python3
"""
Career Radar & Job Application Tracker Server
Connects to SQLite (/data/workspace/tools/job-hunter/jobs.db)
Provides REST API + Dashboard Web UI on port 8095
"""

import sys
import os
import json
import sqlite3
import datetime
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "jobs.db"
STATIC_DIR = BASE_DIR / "static"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            job_url TEXT,
            salary_or_rate TEXT,
            job_type TEXT DEFAULT 'FULLTIME',
            status TEXT DEFAULT 'wishlist',
            outreach_status TEXT DEFAULT 'none',
            outreach_contacts TEXT DEFAULT '[]',
            applied_date TEXT,
            last_activity TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_company ON applications(company);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_job_type ON applications(job_type);")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER,
            company TEXT,
            role TEXT,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_log_app_id ON activity_logs(application_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_log_created_at ON activity_logs(created_at);")

        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(jobs)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col, col_type, default in [("is_skipped", "INTEGER", "0"), ("skip_reason", "TEXT", "''"), ("skipped_at", "TEXT", "NULL")]:
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type} DEFAULT {default}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_is_skipped ON jobs(is_skipped);")

        conn.commit()

class TrackerHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        self.send_json({"error": message, "success": False}, status=status)

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        # Static files & Favicon
        if path == "/" or path == "/index.html":
            index_file = STATIC_DIR / "index.html"
            if index_file.exists():
                content = index_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_error_json("index.html not found", 404)
                return
        elif path == "/favicon.ico" or path == "/favicon.svg":
            svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0f172a"/><path d="M 7 7.5 L 25 7.5 L 25 11 L 13.8 21 L 25 21 L 25 24.5 L 7 24.5 L 7 21 L 18.2 11 L 7 11 Z" fill="#38bdf8"/></svg>'.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(svg)))
            self.end_headers()
            self.wfile.write(svg)
            return

        # APIs
        if path == "/api/stats":
            self.handle_stats()
        elif path == "/api/jobs":
            self.handle_jobs(qs)
        elif path == "/api/applications":
            self.handle_applications(qs)
        elif path == "/api/sources":
            self.handle_sources()
        elif path == "/api/logs":
            self.handle_get_logs(qs)
        elif path.startswith("/api/applications/") and path.endswith("/logs"):
            app_id = path.replace("/api/applications/", "").replace("/logs", "").strip()
            self.handle_get_application_logs(app_id)
        elif path.startswith("/api/applications/"):
            app_id = path.replace("/api/applications/", "").strip()
            self.handle_single_application(app_id)
        else:
            self.send_error_json("Endpoint not found", 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode('utf-8') if length > 0 else "{}"
        try:
            body = json.loads(raw_body)
        except Exception:
            self.send_error_json("Invalid JSON body", 400)
            return

        if path == "/api/applications":
            self.handle_create_application(body)
        elif path == "/api/logs":
            self.handle_create_manual_log(body)
        elif path.startswith("/api/applications/") and path.endswith("/outreach"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                app_id = parts[2]
                self.handle_add_outreach(app_id, body)
            else:
                self.send_error_json("Invalid URL", 400)
        elif path.startswith("/api/applications/") and path.endswith("/logs"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                app_id = parts[2]
                self.handle_create_application_log(app_id, body)
            else:
                self.send_error_json("Invalid URL", 400)
        elif path.startswith("/api/jobs/") and path.endswith("/skip"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                job_id = parts[2]
                self.handle_skip_job(job_id, body)
            else:
                self.send_error_json("Invalid URL", 400)
        elif path.startswith("/api/jobs/") and path.endswith("/unskip"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                job_id = parts[2]
                self.handle_unskip_job(job_id)
            else:
                self.send_error_json("Invalid URL", 400)
        else:
            self.send_error_json("Endpoint not found", 404)

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode('utf-8') if length > 0 else "{}"
        try:
            body = json.loads(raw_body)
        except Exception:
            self.send_error_json("Invalid JSON body", 400)
            return

        if path.startswith("/api/applications/"):
            app_id = path.replace("/api/applications/", "").strip()
            self.handle_update_application(app_id, body)
        else:
            self.send_error_json("Endpoint not found", 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/applications/"):
            app_id = path.replace("/api/applications/", "").strip()
            self.handle_delete_application(app_id)
        else:
            self.send_error_json("Endpoint not found", 404)

    # ── HANDLERS ─────────────────────────────────────────────────────────────

    def handle_stats(self):
        with get_db() as conn:
            c = conn.cursor()
            
            # Jobs stats
            c.execute("SELECT COUNT(*) FROM jobs")
            total_jobs = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM jobs WHERE score >= 60")
            high_match_jobs = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'INTERNSHIP'")
            intern_jobs = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'FULLTIME'")
            fulltime_jobs = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM jobs WHERE job_type = 'FREELANCE_PARTTIME'")
            freelance_jobs = c.fetchone()[0]

            # Regional breakdown
            c.execute("""
                SELECT COUNT(*) FROM jobs 
                WHERE location LIKE '%Indonesia%' 
                   OR location LIKE '%Jakarta%' 
                   OR location LIKE '%Bandung%' 
                   OR location LIKE '%Tangerang%' 
                   OR location LIKE '%Bali%' 
                   OR location LIKE '%Surabaya%' 
                   OR source IN ('glints', 'kalibrr', 'dealls', 'jobstreet')
            """)
            indo_jobs = c.fetchone()[0]
            global_jobs = max(0, total_jobs - indo_jobs)

            # Skipped jobs count
            c.execute("SELECT COUNT(*) FROM jobs WHERE is_skipped = 1")
            skipped_jobs = c.fetchone()[0]

            # Application stats
            c.execute("SELECT COUNT(*) FROM applications")
            total_apps = c.fetchone()[0]

            c.execute("SELECT status, COUNT(*) FROM applications GROUP BY status")
            status_counts = dict(c.fetchall())

            c.execute("SELECT outreach_status, COUNT(*) FROM applications GROUP BY outreach_status")
            outreach_counts = dict(c.fetchall())

            # Activity log count
            c.execute("SELECT COUNT(*) FROM activity_logs")
            total_logs = c.fetchone()[0]

            data = {
                "jobs": {
                    "total": total_jobs,
                    "high_match": high_match_jobs,
                    "internships": intern_jobs,
                    "fulltime": fulltime_jobs,
                    "freelance": freelance_jobs,
                    "indonesia": indo_jobs,
                    "global": global_jobs,
                    "skipped": skipped_jobs
                },
                "applications": {
                    "total": total_apps,
                    "by_status": {
                        "wishlist": status_counts.get("wishlist", 0),
                        "applied": status_counts.get("applied", 0),
                        "screening": status_counts.get("screening", 0),
                        "interview_1": status_counts.get("interview_1", 0),
                        "interview_2": status_counts.get("interview_2", 0),
                        "study_case": status_counts.get("study_case", 0),
                        "offering": status_counts.get("offering", 0),
                        "rejected": status_counts.get("rejected", 0),
                        "withdrawn": status_counts.get("withdrawn", 0),
                    },
                    "by_outreach": {
                        "none": outreach_counts.get("none", 0),
                        "sent": outreach_counts.get("sent", 0),
                        "connected": outreach_counts.get("connected", 0),
                        "replied": outreach_counts.get("replied", 0),
                        "ghosted": outreach_counts.get("ghosted", 0),
                    }
                },
                "activity_logs": {
                    "total": total_logs
                }
            }
            self.send_json(data)

    def handle_sources(self):
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT source, COUNT(*) as count FROM jobs GROUP BY source ORDER BY count DESC")
            sources = [{"source": r["source"], "count": r["count"]} for r in c.fetchall()]
            self.send_json({"sources": sources})

    def handle_jobs(self, qs):
        search = qs.get("search", [""])[0].strip()
        job_type = qs.get("job_type", ["ALL"])[0].strip()
        source = qs.get("source", ["ALL"])[0].strip()
        min_score = int(qs.get("min_score", [0])[0])
        limit = min(int(qs.get("limit", [40])[0]), 100)
        offset = int(qs.get("offset", [0])[0])
        
        # New filters: apply_status, region & skip_status
        apply_status = qs.get("apply_status", ["ALL"])[0].strip() # ALL, APPLIED, UNAPPLIED
        region = qs.get("region", ["ALL"])[0].strip()             # ALL, INDONESIA, GLOBAL
        skip_status = qs.get("skip_status", ["ACTIVE"])[0].strip() # ACTIVE (default), SKIPPED, ALL

        where_clauses = ["1=1"]
        params = []

        if search:
            where_clauses.append("(j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ? OR j.score_reason LIKE ? OR j.skip_reason LIKE ?)")
            pat = f"%{search}%"
            params.extend([pat, pat, pat, pat, pat])

        if job_type != "ALL":
            where_clauses.append("j.job_type = ?")
            params.append(job_type)

        if source != "ALL":
            where_clauses.append("j.source = ?")
            params.append(source)

        if min_score > 0:
            where_clauses.append("j.score >= ?")
            params.append(min_score)

        if skip_status == "ACTIVE":
            where_clauses.append("(j.is_skipped = 0 OR j.is_skipped IS NULL)")
        elif skip_status == "SKIPPED":
            where_clauses.append("j.is_skipped = 1")

        if apply_status == "APPLIED":
            where_clauses.append("a.id IS NOT NULL")
        elif apply_status == "UNAPPLIED":
            where_clauses.append("a.id IS NULL")

        if region == "INDONESIA":
            where_clauses.append("""(
                j.location LIKE '%Indonesia%' 
                OR j.location LIKE '%Jakarta%' 
                OR j.location LIKE '%Bandung%' 
                OR j.location LIKE '%Tangerang%' 
                OR j.location LIKE '%Bali%' 
                OR j.location LIKE '%Surabaya%' 
                OR j.source IN ('glints', 'kalibrr', 'dealls', 'jobstreet')
            )""")
        elif region == "GLOBAL":
            where_clauses.append("""NOT (
                j.location LIKE '%Indonesia%' 
                OR j.location LIKE '%Jakarta%' 
                OR j.location LIKE '%Bandung%' 
                OR j.location LIKE '%Tangerang%' 
                OR j.location LIKE '%Bali%' 
                OR j.location LIKE '%Surabaya%' 
                OR j.source IN ('glints', 'kalibrr', 'dealls')
            )""")

        where_sql = " AND ".join(where_clauses)

        with get_db() as conn:
            c = conn.cursor()
            
            # Count total
            count_query = f"""
                SELECT COUNT(*) 
                FROM jobs j
                LEFT JOIN applications a ON j.id = a.job_id
                WHERE {where_sql}
            """
            c.execute(count_query, params)
            total = c.fetchone()[0]

            # Query items
            query = f"""
                SELECT 
                    j.id, j.source, j.title, j.company, j.location, j.url,
                    j.score, j.score_reason, j.posted_at, j.salary, j.employment_type,
                    j.job_type, j.created_at, j.is_skipped, j.skip_reason, j.skipped_at,
                    a.id AS application_id, a.status AS application_status, a.outreach_status AS application_outreach
                FROM jobs j
                LEFT JOIN applications a ON j.id = a.job_id
                WHERE {where_sql}
                ORDER BY j.score DESC, j.created_at DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])
            c.execute(query, params)
            jobs = [dict(r) for r in c.fetchall()]

            self.send_json({
                "jobs": jobs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": (offset + limit) < total
            })

    def handle_applications(self, qs):
        search = qs.get("search", [""])[0].strip()
        status = qs.get("status", ["ALL"])[0].strip()
        outreach_status = qs.get("outreach_status", ["ALL"])[0].strip()
        job_type = qs.get("job_type", ["ALL"])[0].strip()

        where_clauses = ["1=1"]
        params = []

        if search:
            where_clauses.append("(a.company LIKE ? OR a.role LIKE ? OR a.notes LIKE ? OR a.outreach_contacts LIKE ?)")
            pat = f"%{search}%"
            params.extend([pat, pat, pat, pat])

        if status != "ALL":
            where_clauses.append("a.status = ?")
            params.append(status)

        if outreach_status != "ALL":
            where_clauses.append("a.outreach_status = ?")
            params.append(outreach_status)

        if job_type != "ALL":
            where_clauses.append("a.job_type = ?")
            params.append(job_type)

        where_sql = " AND ".join(where_clauses)

        with get_db() as conn:
            c = conn.cursor()
            query = f"""
                SELECT 
                    a.*,
                    j.score AS job_score,
                    j.score_reason AS job_score_reason,
                    j.source AS job_source
                FROM applications a
                LEFT JOIN jobs j ON a.job_id = j.id
                WHERE {where_sql}
                ORDER BY 
                    CASE a.status 
                        WHEN 'offering' THEN 1
                        WHEN 'interview_2' THEN 2
                        WHEN 'interview_1' THEN 3
                        WHEN 'study_case' THEN 4
                        WHEN 'screening' THEN 5
                        WHEN 'applied' THEN 6
                        WHEN 'wishlist' THEN 7
                        WHEN 'rejected' THEN 8
                        WHEN 'withdrawn' THEN 9
                        ELSE 10
                    END,
                    a.updated_at DESC
            """
            c.execute(query, params)
            raw_apps = [dict(r) for r in c.fetchall()]

            # Parse JSON outreach_contacts
            for app in raw_apps:
                try:
                    app["outreach_contacts"] = json.loads(app["outreach_contacts"] or "[]")
                except Exception:
                    app["outreach_contacts"] = []

            self.send_json({"applications": raw_apps, "total": len(raw_apps)})

    def handle_single_application(self, app_id):
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT a.*, j.score AS job_score, j.score_reason AS job_score_reason, j.source AS job_source
                FROM applications a
                LEFT JOIN jobs j ON a.job_id = j.id
                WHERE a.id = ?
            """, (app_id,))
            row = c.fetchone()
            if not row:
                self.send_error_json("Application not found", 404)
                return
            app = dict(row)
            try:
                app["outreach_contacts"] = json.loads(app["outreach_contacts"] or "[]")
            except Exception:
                app["outreach_contacts"] = []
            self.send_json(app)

    def handle_create_application(self, body):
        company = (body.get("company") or "").strip()
        role = (body.get("role") or "").strip()

        if not company or not role:
            self.send_error_json("Company and Role are required", 400)
            return

        job_id = body.get("job_id")
        job_url = (body.get("job_url") or "").strip()
        salary_or_rate = (body.get("salary_or_rate") or "").strip()
        job_type = (body.get("job_type") or "FULLTIME").strip()
        status = (body.get("status") or "wishlist").strip()
        outreach_status = (body.get("outreach_status") or "none").strip()
        outreach_contacts = json.dumps(body.get("outreach_contacts") or [])
        applied_date = (body.get("applied_date") or "").strip()
        last_activity = datetime.date.today().isoformat()
        notes = (body.get("notes") or "").strip()
        now_iso = datetime.datetime.now().isoformat()

        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO applications (
                    job_id, company, role, job_url, salary_or_rate, job_type,
                    status, outreach_status, outreach_contacts, applied_date,
                    last_activity, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id, company, role, job_url, salary_or_rate, job_type,
                status, outreach_status, outreach_contacts, applied_date,
                last_activity, notes, now_iso, now_iso
            ))
            app_id = c.lastrowid

            # Auto-log creation event
            c.execute("""
                INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                VALUES (?, ?, ?, 'created', ?, ?, ?)
            """, (
                app_id, company, role,
                f"Lamaran {company} ditambahkan ke sistem",
                f"Posisi: {role} · Status: {status} · Kompensasi: {salary_or_rate or 'N/A'}",
                now_iso
            ))
            conn.commit()

        self.send_json({"success": True, "id": app_id, "message": "Application created successfully!"})

    def handle_update_application(self, app_id, body):
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
            existing = c.fetchone()
            if not existing:
                self.send_error_json("Application not found", 404)
                return

            company = body.get("company", existing["company"])
            role = body.get("role", existing["role"])
            job_url = body.get("job_url", existing["job_url"])
            salary_or_rate = body.get("salary_or_rate", existing["salary_or_rate"])
            job_type = body.get("job_type", existing["job_type"])
            status = body.get("status", existing["status"])
            outreach_status = body.get("outreach_status", existing["outreach_status"])
            
            if "outreach_contacts" in body:
                outreach_contacts = json.dumps(body["outreach_contacts"])
            else:
                outreach_contacts = existing["outreach_contacts"]

            applied_date = body.get("applied_date", existing["applied_date"])
            last_activity = datetime.date.today().isoformat()
            notes = body.get("notes", existing["notes"])
            now_iso = datetime.datetime.now().isoformat()

            c.execute("""
                UPDATE applications
                SET company = ?, role = ?, job_url = ?, salary_or_rate = ?, job_type = ?,
                    status = ?, outreach_status = ?, outreach_contacts = ?, applied_date = ?,
                    last_activity = ?, notes = ?, updated_at = ?
                WHERE id = ?
            """, (
                company, role, job_url, salary_or_rate, job_type,
                status, outreach_status, outreach_contacts, applied_date,
                last_activity, notes, now_iso, app_id
            ))

            # Auto-log status change
            if status != existing["status"]:
                status_labels = {
                    "wishlist": "Wishlist", "applied": "Applied (Form)", "screening": "Screening / HR",
                    "interview_1": "Technical / Test", "interview_2": "User / Final Round",
                    "offering": "Offering 🎉", "rejected": "Rejected", "withdrawn": "Withdrawn"
                }
                old_lbl = status_labels.get(existing["status"], existing["status"])
                new_lbl = status_labels.get(status, status)
                c.execute("""
                    INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                    VALUES (?, ?, ?, 'status_change', ?, ?, ?)
                """, (
                    app_id, company, role,
                    f"Status {company} berubah: {old_lbl} ➔ {new_lbl}",
                    f"Diperbarui pada tanggal {datetime.date.today().isoformat()}",
                    now_iso
                ))

            # Auto-log outreach status change
            if outreach_status != existing["outreach_status"]:
                outreach_labels = {
                    "none": "Belum Outreach", "sent": "Outreach Terkirim", "connected": "Terhubung di LinkedIn",
                    "replied": "Dibalas / Diskusi", "ghosted": "No Response / Ghosted"
                }
                old_o = outreach_labels.get(existing["outreach_status"], existing["outreach_status"])
                new_o = outreach_labels.get(outreach_status, outreach_status)
                ev_type = 'outreach_reply' if outreach_status in ['replied', 'connected'] else 'status_change'
                c.execute("""
                    INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    app_id, company, role, ev_type,
                    f"Status Outreach {company} diubah: {old_o} ➔ {new_o}",
                    f"Diperbarui pada tanggal {datetime.date.today().isoformat()}",
                    now_iso
                ))

            # Auto-log notes update if significant
            if notes != existing["notes"] and len(notes) > len(existing["notes"] or ""):
                c.execute("""
                    INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                    VALUES (?, ?, ?, 'note_added', ?, ?, ?)
                """, (
                    app_id, company, role,
                    f"Catatan baru ditambahkan untuk {company}",
                    notes[:200] + ("..." if len(notes) > 200 else ""),
                    now_iso
                ))

            conn.commit()

        self.send_json({"success": True, "message": "Application updated successfully!"})

    def handle_add_outreach(self, app_id, body):
        name = body.get("name", "").strip()
        if not name:
            self.send_error_json("Contact name is required", 400)
            return

        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
            row = c.fetchone()
            if not row:
                self.send_error_json("Application not found", 404)
                return

            try:
                contacts = json.loads(row["outreach_contacts"] or "[]")
            except Exception:
                contacts = []

            title_role = (body.get("title") or "").strip()
            channel = (body.get("channel") or "LinkedIn InMail").strip()
            contact_status = (body.get("status") or "Terkirim").strip()
            notes = (body.get("notes") or "").strip()

            new_contact = {
                "id": len(contacts) + 1,
                "name": name,
                "title": title_role,
                "channel": channel,
                "contact_link": (body.get("contact_link") or "").strip(),
                "date": body.get("date", datetime.date.today().isoformat()),
                "status": contact_status,
                "notes": notes
            }
            contacts.append(new_contact)

            new_outreach_status = row["outreach_status"]
            if new_outreach_status in ["none", ""]:
                new_outreach_status = "sent"
            if contact_status in ["Dibalas", "Terhubung"]:
                new_outreach_status = "replied"

            now_iso = datetime.datetime.now().isoformat()
            c.execute("""
                UPDATE applications
                SET outreach_contacts = ?, outreach_status = ?, last_activity = ?, updated_at = ?
                WHERE id = ?
            """, (json.dumps(contacts), new_outreach_status, datetime.date.today().isoformat(), now_iso, app_id))

            # Auto-log outreach event
            event_type = 'outreach_reply' if contact_status in ['Dibalas', 'Terhubung'] else 'outreach_sent'
            log_title = f"Outreach ({channel}): {name}" + (f" - {title_role}" if title_role else "") + f" @ {row['company']}"
            log_details = f"Status: {contact_status} · Tanggal: {new_contact['date']}\nCatatan: {notes or 'Pesan outreach terkirim'}"
            
            c.execute("""
                INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (app_id, row["company"], row["role"], event_type, log_title, log_details, now_iso))

            conn.commit()

        self.send_json({"success": True, "contact": new_contact, "message": "Outreach contact added & logged!"})

    def handle_delete_application(self, app_id):
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT company, role FROM applications WHERE id = ?", (app_id,))
            row = c.fetchone()
            if row:
                now_iso = datetime.datetime.now().isoformat()
                c.execute("""
                    INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                    VALUES (NULL, ?, ?, 'status_change', ?, 'Dihapus dari pipeline lamaran', ?)
                """, (row["company"], row["role"], f"Lamaran {row['company']} dihapus", now_iso))
            
            c.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            c.execute("DELETE FROM activity_logs WHERE application_id = ?", (app_id,))
            conn.commit()
        self.send_json({"success": True, "message": "Application deleted!"})

    def handle_skip_job(self, job_id, body):
        reason = body.get("reason", "Tidak relevan / khusus kampus tertentu").strip()
        now_iso = datetime.datetime.now().isoformat()
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT company, title FROM jobs WHERE id = ?", (job_id,))
            job = c.fetchone()
            if not job:
                self.send_error_json("Job not found", 404)
                return
            c.execute("""
                UPDATE jobs 
                SET is_skipped = 1, skip_reason = ?, skipped_at = ?
                WHERE id = ?
            """, (reason, now_iso, job_id))

            c.execute("""
                INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                VALUES (NULL, ?, ?, 'job_skipped', ?, ?, ?)
            """, (
                job["company"], job["title"],
                f"Loker {job['company']} ditandai 'Tidak Perlu Diapply' (Skipped)",
                f"Alasan: {reason}",
                now_iso
            ))
            conn.commit()
        self.send_json({"success": True, "message": f"Job {job_id} skipped."})

    def handle_unskip_job(self, job_id):
        now_iso = datetime.datetime.now().isoformat()
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT company, title FROM jobs WHERE id = ?", (job_id,))
            job = c.fetchone()
            if not job:
                self.send_error_json("Job not found", 404)
                return
            c.execute("""
                UPDATE jobs 
                SET is_skipped = 0, skip_reason = '', skipped_at = NULL
                WHERE id = ?
            """, (job_id,))

            c.execute("""
                INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                VALUES (NULL, ?, ?, 'job_unskipped', ?, 'Loker dipulihkan kembali ke radar aktif', ?)
            """, (
                job["company"], job["title"],
                f"Loker {job['company']} dipulihkan (Unskipped)",
                now_iso
            ))
            conn.commit()
        self.send_json({"success": True, "message": f"Job {job_id} unskipped/restored."})

    # ── LOGS ENDPOINTS ────────────────────────────────────────────────────────

    def handle_get_logs(self, qs):
        limit = min(int(qs.get("limit", [50])[0]), 150)
        offset = int(qs.get("offset", [0])[0])
        event_type = qs.get("event_type", ["ALL"])[0].strip()
        search = qs.get("search", [""])[0].strip()

        where_clauses = ["1=1"]
        params = []

        if event_type != "ALL":
            where_clauses.append("event_type = ?")
            params.append(event_type)

        if search:
            where_clauses.append("(company LIKE ? OR role LIKE ? OR title LIKE ? OR details LIKE ?)")
            pat = f"%{search}%"
            params.extend([pat, pat, pat, pat])

        where_sql = " AND ".join(where_clauses)

        with get_db() as conn:
            c = conn.cursor()
            c.execute(f"SELECT COUNT(*) FROM activity_logs WHERE {where_sql}", params)
            total = c.fetchone()[0]

            c.execute(f"""
                SELECT * FROM activity_logs
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, params + [limit, offset])
            logs = [dict(r) for r in c.fetchall()]

        self.send_json({"logs": logs, "total": total, "limit": limit, "offset": offset})

    def handle_get_application_logs(self, app_id):
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT * FROM activity_logs
                WHERE application_id = ?
                ORDER BY created_at DESC
            """, (app_id,))
            logs = [dict(r) for r in c.fetchall()]
        self.send_json({"logs": logs, "total": len(logs)})

    def handle_create_application_log(self, app_id, body):
        try:
            body["application_id"] = int(app_id)
        except Exception:
            pass
        self.handle_create_manual_log(body)

    def handle_create_manual_log(self, body):
        app_id = body.get("application_id")
        company = (body.get("company") or "").strip()
        role = (body.get("role") or "").strip()
        title = (body.get("title") or "").strip()
        event_type = (body.get("event_type") or "custom").strip()
        details = (body.get("details") or "").strip()
        now_iso = datetime.datetime.now().isoformat()

        if not title:
            self.send_error_json("Title is required", 400)
            return

        with get_db() as conn:
            c = conn.cursor()
            if app_id:
                c.execute("SELECT company, role FROM applications WHERE id = ?", (app_id,))
                row = c.fetchone()
                if row:
                    company = company or row["company"]
                    role = role or row["role"]
                    c.execute("UPDATE applications SET last_activity = ?, updated_at = ? WHERE id = ?",
                              (datetime.date.today().isoformat(), now_iso, app_id))

            c.execute("""
                INSERT INTO activity_logs (application_id, company, role, event_type, title, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (app_id, company, role, event_type, title, details, now_iso))
            conn.commit()

        self.send_json({"success": True, "message": "Activity log recorded!"})

def run(port=8095):
    init_db()
    server_address = ("0.0.0.0", port)
    httpd = ThreadingHTTPServer(server_address, TrackerHandler)
    print(f"🚀 Career Radar & Tracker Server running at http://0.0.0.0:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8095
    run(port)
