"""US UGC outreach — cold send to brand/agency contacts.
Source: us ugc/ugc_all_research_602_all_emails.csv
Log:    us ugc/us_ugc_sent_log.csv
"""
import csv, os, smtplib, ssl, sys, time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
import certifi

# config.py lives one level up
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GMAIL_ACCOUNTS

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
CSV  = os.path.join(HERE, "ugc_all_research_602_all_emails.csv")
LOG  = os.path.join(HERE, "us_ugc_sent_log.csv")

# ── campaign constants — edit per batch ───────────────────────────────────────
FORMATS     = "shocked-hook reels and more"
PER_ACCOUNT = 20
DELAY       = 30   # seconds between sends

# T3, T4, T5 — rotated per send; T1/T2 require per-prospect research so excluded
TEMPLATES = [
    # T3: Markup angle
    (
        "60 videos a month — $2,000",
        """\
Hi {first_name},

Fun fact: in a lot of UGC agency setups, the brand pays roughly double what the creator actually takes home.

So you're paying for the creator twice, and the person making your videos still isn't the one being paid properly.

We keep it simple. One creator, up to 60 videos a month for {company}, $2,000 flat. Mostly Tier 1 audiences, and we're running this for Higgsfield and VEED.io right now.

Should I send over a few creators' videos so you can see who'd fit?

Creator Scout""",
    ),
    # T4: In-house ops angle
    (
        "60 videos a month — $2,000",
        """\
Hi {first_name},

Hiring creators yourself means {company} is basically running its own UGC agency: sourcing, briefing, chasing drafts, and replacing whoever goes quiet after week two.

What if one creator covered 60 videos a month for $2,000? Tier 1 audiences, {formats}, and it's exactly what we're doing for Higgsfield and VEED.io right now.

Want me to send our creators' videos so you can shortlist the ones you like?

Creator Scout""",
    ),
    # T5: Founder short
    (
        "60 videos a month — $2,000",
        """\
Hi {first_name},

Most UGC agencies would quote you thousands a month for a handful of videos.

We do up to 60 a month from one creator for $2,000: {formats}, mostly Tier 1 audiences. Same setup we're running for Higgsfield and VEED.io.

Want to see a few creators' videos and pick one to start with?

Creator Scout""",
    ),
]

LOG_FIELDS = ["timestamp", "from_email", "to_email", "to_name", "status", "error"]

# email-local-parts that aren't personal names
GENERIC = {
    "info", "hello", "contact", "team", "sales", "support", "admin",
    "marketing", "media", "press", "careers", "jobs", "noreply", "no-reply",
    "partnerships", "hi", "collab", "collabs", "brand", "brands", "growth",
    "founders", "founder", "partner", "partners", "bizdev", "business",
}


def derive_first_name(email: str, company: str) -> str:
    local = email.split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").split()[0]
    if local.lower() in GENERIC:
        parts = str(company).strip().split()
        return (parts[0][0].upper() + parts[0][1:]) if parts else "there"
    return local[0].upper() + local[1:]


def load_recipients():
    rows = []
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            email = (row.get("Email") or "").strip()
            if not email or "@" not in email:
                continue
            rows.append({
                "email":   email,
                "company": (row.get("Company") or "").strip(),
            })
    return rows


def load_processed():
    if not os.path.exists(LOG):
        return set()
    done = set()
    with open(LOG, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("status") in ("sent", "failed"):
                done.add(r["to_email"].strip().lower())
    return done


def append_log(row):
    exists = os.path.exists(LOG)
    with open(LOG, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(row)


def build_msg(from_email, from_name, to_email, company, tpl_idx=0):
    first_name = derive_first_name(to_email, company)
    subject, body_tpl = TEMPLATES[tpl_idx % len(TEMPLATES)]
    body = body_tpl.format(
        first_name=first_name,
        company=company or "your company",
        formats=FORMATS,
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"]         = subject
    msg["From"]            = f"{from_name} <{from_email}>"
    msg["To"]              = to_email
    msg["Reply-To"]        = from_email
    msg["Date"]            = formatdate(localtime=True)
    msg["Message-ID"]      = make_msgid(domain=from_email.split("@")[1])
    msg["List-Unsubscribe"] = f"<mailto:{from_email}?subject=unsubscribe>"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    return msg


def main():
    recipients = load_recipients()
    processed  = load_processed()
    print(f"CSV: {len(recipients)} | already processed: {len(processed)}")

    seen, unsent = set(), []
    for r in recipients:
        k = r["email"].lower()
        if k in processed or k in seen:
            continue
        seen.add(k)
        unsent.append(r)

    accounts = sorted(GMAIL_ACCOUNTS.keys())
    total    = PER_ACCOUNT * len(accounts)
    pool     = unsent[:total]
    print(f"Available: {len(unsent)} | sending this run: {len(pool)}")
    print(f"Delay: {DELAY}s | Est runtime: ~{len(pool) * DELAY / 60:.1f} min")

    if not pool:
        print("Nothing to send.")
        return

    yes = "--yes" in sys.argv
    if not yes:
        try:
            if input("\nType SEND to confirm: ").strip() != "SEND":
                print("Aborted.")
                return
        except EOFError:
            print("No stdin. Use --yes.")
            sys.exit(1)

    # distribute first PER_ACCOUNT to account 1, next to account 2, etc.
    buckets = {}
    offset = 0
    for aid in accounts:
        buckets[aid] = pool[offset:offset + PER_ACCOUNT]
        offset += PER_ACCOUNT

    # interleave round-robin so accounts alternate in the send queue
    queue = []
    for round_idx in range(PER_ACCOUNT):
        for aid in accounts:
            if round_idx < len(buckets[aid]):
                queue.append((aid, buckets[aid][round_idx]))

    ctx = ssl.create_default_context(cafile=certifi.where())

    def connect(acc):
        s = smtplib.SMTP_SSL(acc.get("smtp_host", "smtp.gmail.com"), 465, context=ctx)
        s.login(acc["email"], acc["app_password"].replace(" ", ""))
        return s

    smtps = {}
    for aid in accounts:
        try:
            smtps[aid] = connect(GMAIL_ACCOUNTS[aid])
        except smtplib.SMTPAuthenticationError as e:
            print(f"LOGIN FAILED account {aid}: {e}")
            return

    ok = fail = 0
    for i, (aid, r) in enumerate(queue, 1):
        acc = GMAIL_ACCOUNTS[aid]
        msg = build_msg(acc["email"], acc["from_name"], r["email"], r["company"], tpl_idx=i - 1)
        try:
            smtps[aid].sendmail(acc["email"], [r["email"]], msg.as_string())
            ok += 1
            append_log({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "from_email": acc["email"], "to_email": r["email"],
                "to_name": r["company"], "status": "sent", "error": "",
            })
            print(f"  [{i}/{len(queue)}] {acc['email']} -> {r['email']} OK", flush=True)
        except Exception as e1:
            try:
                try: smtps[aid].close()
                except Exception: pass
                smtps[aid] = connect(acc)
                smtps[aid].sendmail(acc["email"], [r["email"]], msg.as_string())
                ok += 1
                append_log({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "from_email": acc["email"], "to_email": r["email"],
                    "to_name": r["company"], "status": "sent", "error": "",
                })
                print(f"  [{i}/{len(queue)}] {acc['email']} -> {r['email']} OK (retry)", flush=True)
            except Exception as e2:
                fail += 1
                append_log({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "from_email": acc["email"], "to_email": r["email"],
                    "to_name": r["company"], "status": "failed",
                    "error": f"{e2} (first: {e1})"[:200],
                })
                print(f"  [{i}/{len(queue)}] {acc['email']} -> {r['email']} FAIL: {e2}", flush=True)
        if i < len(queue):
            time.sleep(DELAY)

    for s in smtps.values():
        try: s.quit()
        except Exception: pass

    print(f"\nDone. sent={ok} failed={fail}")


if __name__ == "__main__":
    main()
