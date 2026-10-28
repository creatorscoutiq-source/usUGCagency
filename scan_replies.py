"""Scan all 10 inboxes for replies to the UGC campaign (since first send date)."""
import imaplib, email, sys, ssl, certifi
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from config import GMAIL_ACCOUNTS

SINCE       = "26-Oct-2026"   # first batch send date
SUBJECT_KEY = "60 videos a month"

ctx = ssl.create_default_context(cafile=certifi.where())
results = []

for aid, acc in GMAIL_ACCOUNTS.items():
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ctx)
        M.login(acc["email"], acc["app_password"].replace(" ", ""))
        M.select("INBOX")
        _, data = M.search(None, "SINCE", SINCE, "SUBJECT", f'"{SUBJECT_KEY}"')
        uids = data[0].split()
        print(f"{acc['email']}: {len(uids)} matches", flush=True)
        for uid in uids:
            try:
                M.socket().settimeout(30)
                _, msg_data = M.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                frm  = msg.get("From", "")
                subj = msg.get("Subject", "")
                date = msg.get("Date", "")
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors="replace")[:400]
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors="replace")[:400]
                results.append((acc["email"], frm, date, subj, body.strip()))
            except Exception as e:
                results.append((acc["email"], "FETCH_ERR", "", "", str(e)[:100]))
        M.logout()
    except Exception as e:
        print(f"{acc['email']}: ERROR {e}", flush=True)

print(f"\nTotal: {len(results)}\n")
for inbox, frm, date, subj, body in results:
    print(f"[{inbox}]")
    print(f"FROM: {frm}")
    print(f"DATE: {date}")
    print(f"SUBJ: {subj}")
    print("---")
    print(body)
    print("=" * 60)
