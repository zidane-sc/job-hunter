import sqlite3
import re

def audit_all():
    conn = sqlite3.connect('/data/workspace/tools/job-hunter/jobs.db')
    c = conn.cursor()
    
    # Applied URLs
    c.execute("SELECT job_url FROM applications WHERE job_url IS NOT NULL")
    applied_urls = set(r[0].split('?')[0].strip() for r in c.fetchall())
    
    c.execute("""
        SELECT id, title, company, location, url, score, score_reason, employment_type, job_type 
        FROM jobs 
        WHERE is_skipped = 0
    """)
    all_jobs = c.fetchall()
    print(f"Total active jobs in DB: {len(all_jobs)}")
    
    skipped_breakdown = {}
    
    for r in all_jobs:
        jid, title, comp, loc, url, score, reason, emp_type, jtype = r
        clean_url = url.split('?')[0].strip()
        t_low = title.lower()
        c_low = comp.lower()
        full_text = f"{title} {comp} {loc} {reason} {emp_type}".lower()
        
        # Don't touch applied jobs
        if clean_url in applied_urls:
            continue
            
        skip_reason = None
        
        # 1. Directory / Aggregator / Profile links
        if any(bad in url.lower() for bad in ['/role/r/', '/role/l/', 'web3.career/@', 'cryptojobslist.com/@', '/categories/']):
            skip_reason = "Directory/Aggregator link or user profile"
            
        # 2. Unpaid / Volunteer / $0
        elif any(re.search(rf"\b{re.escape(w)}\b", t_low) or re.search(rf"\b{re.escape(w)}\b", full_text) for w in ["unpaid", "volunteer", "no salary or stipend", "cash compensation: none"]):
            skip_reason = "Unpaid or volunteer role"

        # 3. Web3 / Crypto / Blockchain / DeFi / Tokenomics
        elif any(w in t_low or w in c_low or w in full_text for w in [
            "web3", "crypto", "blockchain", "solana", "smart contract", "defi", "nft", 
            "p2p crypto", "triton one", "ledger", "ethereum", "bitcoin", "rust developer in", "crypto.com", "binance accelerator programm - software engineer (ledger)"
        ]) or "web3.career" in url or "cryptojobs" in url:
            skip_reason = "Web3/Crypto role (user constraint: no Web3)"

        # 4. Pure Java / C# / .NET / C++ (without Go or Node)
        elif (re.search(r"\bjava\b", t_low) and not any(k in full_text for k in ["javascript", "golang", "go", "node", "typescript"])) or re.search(r"\b(\.net|c#|c\+\+)\b", t_low):
            skip_reason = "Java-only or C#/.NET/C++ (user stack is Go/Node/TS)"

        # 5. Mobile-only (Flutter, Android, iOS native)
        elif (any(m in t_low for m in ["flutter", "android", "ios", "swift", "react native"]) and not any(k in t_low for k in ["full stack", "fullstack", "backend"])):
            skip_reason = "Mobile-only role (user constraint: no Mobile)"

        # 6. Forward Deployed Engineer (FDE / Client-facing solutions consultant)
        elif any(f in t_low for f in ["forward deployed", "fde", "solutions consultant", "sales engineer", "field engineer"]):
            skip_reason = "Forward Deployed / Solutions Engineer (client-facing, not core dev)"

        # 7. Pure Python without Go/Node/TypeScript fullstack
        elif (re.search(r"\bpython\b", t_low) and not any(k in full_text for k in ["react", "node", "typescript", "fullstack", "full stack", "golang", "go ", "web", "postgres"])):
            skip_reason = "Pure Python role (user constraint: no pure Python/DS/ML)"

        # 8. SRE / DevOps-only / Sysadmin (user constraint: no SRE)
        elif any(d in t_low for d in ["devops engineer", "sre", "site reliability", "sysadmin", "azure devops", "cloud network engineer", "proxy engineer"]):
            skip_reason = "DevOps/SRE-only role (user constraint: no SRE)"

        # 9. Non-tech & Foreign language requirements
        elif any(nt in t_low for nt in [
            "recruitment", "employer branding", "teacher", "esl", "business analyst", 
            "general affairs", "admin", "quality intern", "tax intern", "pricing operations", 
            "auditor", "graphic design", "marketing", "sales", "curriculum", "content writer",
            "social media", "hr intern", "human resources", "talent acquisition", "robotics",
            "arabic speaker", "korean voice", "japanese speaker", "russian speaker"
        ]):
            skip_reason = "Non-tech role or foreign language requirement"

        # 10. For INTERNSHIP specifically: misclassified senior roles
        elif jtype == "INTERNSHIP" and any(re.search(rf"\b{k}\b", t_low) for k in ["senior", "sr", "staff", "lead", "principal", "head", "director"]) and not any(k in t_low for k in ["intern", "internship", "magang"]):
            # This is a misclassified senior job, reclassify to FULLTIME
            c.execute("UPDATE jobs SET job_type = 'FULLTIME' WHERE id = ?", (jid,))
            continue

        if skip_reason:
            c.execute("""
                UPDATE jobs 
                SET is_skipped = 1, skip_reason = ?, skipped_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (skip_reason, jid))
            skipped_breakdown[skip_reason] = skipped_breakdown.get(skip_reason, 0) + 1
            
    conn.commit()
    print("\nSkipped breakdown:")
    for k, v in sorted(skipped_breakdown.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {k}: {v} jobs")
        
    c.execute("""
        SELECT job_type, COUNT(*) 
        FROM jobs 
        WHERE is_skipped = 0 
        GROUP BY job_type
    """)
    print("\nRemaining Active Jobs by job_type:")
    for r in c.fetchall():
        print(f"  - {r[0]}: {r[1]} jobs")

if __name__ == '__main__':
    audit_all()
