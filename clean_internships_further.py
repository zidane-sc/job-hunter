import sqlite3
import re

conn = sqlite3.connect('/data/workspace/tools/job-hunter/jobs.db')

def regexp(expr, item):
    if not item:
        return False
    reg = re.compile(expr, re.I)
    return reg.search(item) is not None

conn.create_function("REGEXP", 2, regexp)
c = conn.cursor()

skip_criteria = [
    (r"unque cloudbook", "Severe underpay (3.5k INR / ~Rp 600rb/bln)"),
    (r"sentio", "Web3/Crypto analytics platform"),
    (r"helloviza", "Flutter/Mobile role"),
    (r"pluralis research|yotta labs", "AI Research / ML Scientist, not SWE"),
    (r"getwingapp", "Duplicate: already applied to Wing Assistant"),
    (r"binance.*(mobile|fe2b0bf9)", "Duplicate or Mobile role"),
    (r"marketeq digital", "Marketing agency frontend"),
    (r"soundsync|nightup", "Mobile React Native app"),
    (r"buimb research", "Academic web dev unpaid"),
    (r"exiro enterprises", "Generic agency unpaid"),
]

for pattern, reason in skip_criteria:
    c.execute("""
        UPDATE jobs 
        SET is_skipped = 1, skip_reason = ?, skipped_at = CURRENT_TIMESTAMP 
        WHERE job_type = 'INTERNSHIP' AND is_skipped = 0 AND (title REGEXP ? OR company REGEXP ? OR url REGEXP ?)
    """, (reason, pattern, pattern, pattern))

conn.commit()

c.execute("""
    SELECT job_url FROM applications WHERE job_url IS NOT NULL
""")
applied_urls = set(r[0].split('?')[0].strip() for r in c.fetchall())

c.execute("""
    SELECT id, title, company, location, url, score, score_reason, employment_type 
    FROM jobs 
    WHERE job_type = 'INTERNSHIP' AND is_skipped = 0
    ORDER BY score DESC, title ASC
""")
rows = c.fetchall()
unapplied = [r for r in rows if r[4].split('?')[0].strip() not in applied_urls]

print(f"Cleaned! High-Quality, Tech-Aligned Unapplied Internships: {len(unapplied)}")
for i, r in enumerate(unapplied):
    print(f"{i+1}. [{r[5]} pts] {r[2]} - {r[1]} | {r[3]} | {r[4]}")
