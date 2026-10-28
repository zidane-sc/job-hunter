CREATE TABLE jobs (
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
                notified_at TEXT
            , posted_at TEXT, salary TEXT, employment_type TEXT, job_type TEXT, is_skipped INTEGER DEFAULT 0, skip_reason TEXT DEFAULT '', skipped_at TEXT DEFAULT NULL);

CREATE INDEX idx_is_notified ON jobs(is_notified);

CREATE INDEX idx_score ON jobs(score);

CREATE INDEX idx_job_type ON jobs(job_type);

CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    job_url TEXT,
    salary_or_rate TEXT,
    job_type TEXT DEFAULT 'FULLTIME',
    status TEXT DEFAULT 'applied',
    outreach_status TEXT DEFAULT 'none',
    outreach_contacts TEXT DEFAULT '[]',
    applied_date TEXT,
    last_activity TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_app_status ON applications(status);

CREATE INDEX idx_app_company ON applications(company);

CREATE INDEX idx_app_job_type ON applications(job_type);

CREATE TABLE activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER,
    company TEXT,
    role TEXT,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(application_id) REFERENCES applications(id) ON DELETE CASCADE
);

CREATE INDEX idx_log_app_id ON activity_logs(application_id);

CREATE INDEX idx_log_created_at ON activity_logs(created_at);

CREATE INDEX idx_jobs_is_skipped ON jobs(is_skipped);
