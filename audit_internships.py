import sqlite3
import re
import sys

def audit_internships():
    conn = sqlite3.connect('/data/workspace/tools/job-hunter/jobs.db')
    c = conn.cursor()
    
    # 1. Get applied URLs
    c.execute("SELECT job_url FROM applications WHERE job_url IS NOT NULL")
    applied_urls = set(r[0].split('?')[0].strip() for r in c.fetchall())
    
    # 2. Get all active internships
    c.execute("""
        SELECT id, title, company, location, url, score, score_reason, employment_type 
        FROM jobs 
        WHERE job_type = 'INTERNSHIP' AND is_skipped = 0
    """)
    rows = c.fetchall()
    print(f"Total active internships in DB: {len(rows)}")
    
    skipped_count = 0
    valid_unapplied = []
    
    # Rules to reject:
    for r in rows:
        jid, title, comp, loc, url, score, reason, emp_type = r
        clean_url = url.split('?')[0].strip()
        t_low = title.lower()
        c_low = comp.lower()
        full_text = f"{title} {comp} {loc} {reason}".lower()
        
        # Check if already applied
        is_applied = clean_url in applied_urls
        if is_applied:
            continue
            
        skip_reason = None
        
        # A. Non-tech roles
        non_tech = [
            "recruitment", "employer branding", "esl teacher", "teacher", "business analyst", 
            "general affairs", "admin", "quality intern commercial", "tax intern", "pricing operations", 
            "internal auditor", "graphic design", "marketing", "sales", "curriculum", "content writer",
            "social media", "hr intern", "human resources", "talent acquisition"
        ]
        for nt in non_tech:
            if re.search(rf"\b{re.escape(nt)}\b", t_low):
                skip_reason = f"Non-tech role: {nt}"
                break
                
        # B. Web3 / Crypto / Blockchain
        if not skip_reason:
            web3_terms = ["web3", "crypto", "blockchain", "solana", "smart contract", "defi", "p2p crypto", "triton one", "ledger"]
            if any(w in t_low or w in c_low or w in full_text for w in web3_terms) or "web3.career" in url or "cryptojobs" in url:
                skip_reason = "Web3/Crypto role (not aligned with profile)"

        # C. Java-only / C# / .NET / C++ (without Go or Node)
        if not skip_reason:
            if re.search(r"\bjava\b", t_low) and not any(k in t_low for k in ["javascript", "golang", "go", "node", "typescript"]):
                skip_reason = "Java-only role (profile is Go/Node/TS)"
            elif re.search(r"\b(\.net|c#|c\+\+)\b", t_low):
                skip_reason = ".NET / C# / C++ role"

        # D. Forward Deployed Engineer (Client-facing solutions)
        if not skip_reason:
            if "forward deployed" in t_low or "fde" in t_low:
                skip_reason = "Forward Deployed Engineer (client-facing solutions consultant)"

        # E. Mobile-only (Android, iOS, Flutter native)
        if not skip_reason:
            if any(m in t_low for m in ["android", "ios", "flutter", "mobile programmer", "mobile intern", "react native intern"]) and not any(k in t_low for k in ["full stack", "fullstack", "backend"]):
                skip_reason = "Mobile-only role (profile is Backend/Fullstack Web)"

        # F. Pure Python without Go/Node/Web fullstack
        if not skip_reason:
            if "python" in t_low and not any(k in full_text for k in ["react", "node", "typescript", "fullstack", "full stack", "golang", "web"]):
                skip_reason = "Pure Python role without Go/Node/Fullstack"

        # G. Must be software / web / backend / fullstack
        if not skip_reason:
            tech_matches = ["software", "developer", "engineer", "backend", "fullstack", "full stack", "web", "mcp server", "api"]
            if not any(k in t_low for k in tech_matches):
                skip_reason = f"Title '{title}' does not match software/backend/fullstack engineering"

        if skip_reason:
            c.execute("""
                UPDATE jobs 
                SET is_skipped = 1, skip_reason = ?, skipped_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (skip_reason, jid))
            skipped_count += 1
        else:
            valid_unapplied.append({
                "id": jid,
                "title": title,
                "company": comp,
                "location": loc,
                "url": url,
                "score": score,
                "reason": reason
            })
            
    conn.commit()
    print(f"Skipped {skipped_count} invalid internships.")
    print(f"Valid, Tech-Aligned, Remote Unapplied Internships remaining: {len(valid_unapplied)}")
    print("\n--- AUDITED VALID INTERNSHIPS ---")
    for v in sorted(valid_unapplied, key=lambda x: x['score'], reverse=True):
        print(f"[{v['score']} pts] {v['company']} - {v['title']} | Loc: {v['location']} | {v['url']}")

if __name__ == '__main__':
    audit_internships()
