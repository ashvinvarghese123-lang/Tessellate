"""Department authentication: username + password, then a one-time code emailed to the
department's REGISTERED address. No roles. The department comes from the account, never from the client.

Security choices (all enforced here, none in the browser):
- passwords: scrypt with a random salt; compared in constant time
- codes: 6 digits from `secrets`, stored only as an HMAC; expire in 5 min; single use; 5 tries; resend cooldown
- sessions: random 256-bit token in an HTTP-only cookie; only its SHA-256 is stored; 8 h limit, 60 min idle limit
- errors never say whether the username exists
"""
import base64, hashlib, hmac, json, os, re, secrets, smtplib, logging, threading, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

log = logging.getLogger("tessellate.mail")
SECRET = os.environ.get("TESSELLATE_SECRET", "dev-only-change-me").encode()
COOKIE = "tess_session"
OTP_MINUTES, MAX_TRIES, RESEND_SECONDS, MAX_SENDS = 5, 5, 30, 4
SESSION_HOURS, IDLE_MINUTES, LOCK_AFTER, LOCK_MINUTES = 8, 60, 5, 15
now = lambda: datetime.now(timezone.utc)


# ---------- passwords ----------
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except Exception:
        return False


_DUMMY = hash_password("not-a-real-password")  # so unknown usernames take the same time as wrong passwords


def strong_enough(pw: str):
    if len(pw) < 10 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(400, "Choose a password with at least 10 characters, including letters and numbers.")


# ---------- email ----------
def _smtp_send(host, to, subject, body):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ.get("SMTP_FROM", "noreply@tessellate.local"), to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=20) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    except Exception:
        log.exception("Email to %s could not be sent", to)   # visible in the server log, never shown to users


def _brevo_send(to, subject, body):
    """Email over HTTPS (port 443). Works on hosts that block SMTP ports, such as Render's free plan."""
    try:
        data = json.dumps({"sender": {"email": os.environ["SMTP_FROM"], "name": "Tessellate"}, "to": [{"email": to}],
                           "subject": subject, "textContent": body}).encode()
        req = urllib.request.Request(os.environ.get("BREVO_API_URL", "https://api.brevo.com/v3/smtp/email"), data=data, method="POST",
                                     headers={"api-key": os.environ["BREVO_API_KEY"], "content-type": "application/json", "accept": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except urllib.error.HTTPError as e:
        log.error("Email to %s was refused (%s): %s", to, e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception:
        log.exception("Email to %s could not be sent", to)


def send_email(to: str, subject: str, body: str):
    """Sent in the background so signing in never waits for the mail provider.
    BREVO_API_KEY set -> HTTPS API. SMTP_HOST set -> SMTP. Neither (development) -> printed in the SERVER log only."""
    if os.environ.get("BREVO_API_KEY"):
        threading.Thread(target=_brevo_send, args=(to, subject, body), daemon=True).start()
        return
    host = os.environ.get("SMTP_HOST")
    if not host:
        log.warning("DEV EMAIL to %s | %s | %s", to, subject, body)
        return
    threading.Thread(target=_smtp_send, args=(host, to, subject, body), daemon=True).start()


def mask(email: str) -> str:
    u, d = email.split("@")
    return u[0] + "***@" + d


def code_hash(challenge_id, code):
    return hmac.new(SECRET, f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def audit(conn, account_id, dept_id, event):
    conn.execute("INSERT INTO login_audit (account_id, department_id, event) VALUES (%s,%s,%s)", (account_id, dept_id, event))


# ---------- routes ----------
from .db import db  # noqa: E402  (shared connection dependency)
router = APIRouter(prefix="/api/auth")


class LoginReq(BaseModel):
    username: str
    password: str


class VerifyReq(BaseModel):
    challenge_id: str
    code: str


def _issue_code(conn, acct, challenge_id=None):
    code = f"{secrets.randbelow(10**6):06d}"
    if challenge_id is None:
        challenge_id = conn.execute("""INSERT INTO login_challenge (account_id, code_hash, expires_at)
            VALUES (%s,'',%s) RETURNING id""", (acct["id"], now() + timedelta(minutes=OTP_MINUTES))).fetchone()["id"]
    conn.execute("""UPDATE login_challenge SET code_hash=%s, expires_at=%s, attempts=0, last_sent_at=now()
                    WHERE id=%s""", (code_hash(challenge_id, code), now() + timedelta(minutes=OTP_MINUTES), challenge_id))
    send_email(acct["email"], "Your Tessellate verification code",
               f"Your code is {code}. It expires in {OTP_MINUTES} minutes. If this wasn't you, ignore this email.")
    return str(challenge_id)


@router.post("/login")
def login(req: LoginReq, conn=Depends(db)):
    bad = HTTPException(401, "The username or password is incorrect.")
    a = conn.execute("SELECT * FROM department_account WHERE username=%s AND active", (req.username.strip().lower(),)).fetchone()
    if not a:
        check_password(req.password, _DUMMY)
        raise bad
    if a["locked_until"] and a["locked_until"] > now():
        raise HTTPException(429, "Too many attempts. Please wait a few minutes and try again.")
    if not check_password(req.password, a["password_hash"]):
        n = a["failed_logins"] + 1
        conn.execute("UPDATE department_account SET failed_logins=%s, locked_until=%s WHERE id=%s",
                     (0 if n >= LOCK_AFTER else n, now() + timedelta(minutes=LOCK_MINUTES) if n >= LOCK_AFTER else None, a["id"]))
        audit(conn, a["id"], a["department_id"], "bad_password")
        conn.commit()
        raise bad
    conn.execute("UPDATE department_account SET failed_logins=0, locked_until=NULL WHERE id=%s", (a["id"],))
    cid = _issue_code(conn, a)
    conn.commit()
    return dict(challenge_id=cid, email_hint=mask(a["email"]))


def _challenge(conn, cid):
    try:
        return conn.execute("""SELECT c.*, a.email, a.department_id FROM login_challenge c
                               JOIN department_account a ON a.id=c.account_id WHERE c.id=%s""", (cid,)).fetchone()
    except Exception:
        conn.rollback()
        return None


@router.post("/verify")
def verify(req: VerifyReq, response: Response, request: Request, conn=Depends(db)):
    c = _challenge(conn, req.challenge_id)
    if not c or c["used"] or c["expires_at"] < now():
        raise HTTPException(400, "This code has expired. Please request a new one.")
    if c["attempts"] >= MAX_TRIES:
        raise HTTPException(429, "Too many incorrect codes. Please sign in again.")
    if not hmac.compare_digest(c["code_hash"], code_hash(c["id"], req.code.strip())):
        conn.execute("UPDATE login_challenge SET attempts=attempts+1 WHERE id=%s", (c["id"],))
        audit(conn, c["account_id"], c["department_id"], "bad_code")
        conn.commit()
        raise HTTPException(400, "That code isn't correct. Please check it and try again.")
    conn.execute("UPDATE login_challenge SET used=TRUE WHERE id=%s", (c["id"],))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO auth_session (token_hash, account_id, expires_at) VALUES (%s,%s,%s)",
                 (hashlib.sha256(token.encode()).hexdigest(), c["account_id"], now() + timedelta(hours=SESSION_HOURS)))
    audit(conn, c["account_id"], c["department_id"], "login_ok")
    conn.commit()
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=SESSION_HOURS * 3600,
                        secure=os.environ.get("COOKIE_SECURE", "0") == "1")
    d = conn.execute("SELECT code, name FROM department WHERE id=%s", (c["department_id"],)).fetchone()
    return dict(department=d)


@router.post("/resend")
def resend(req: dict, conn=Depends(db)):
    c = _challenge(conn, req.get("challenge_id"))
    if not c or c["used"]:
        raise HTTPException(400, "Please sign in again.")
    if (now() - c["last_sent_at"]).total_seconds() < RESEND_SECONDS:
        raise HTTPException(429, f"Please wait {RESEND_SECONDS} seconds before asking for another code.")
    if c["sends"] >= MAX_SENDS:
        raise HTTPException(429, "Too many codes requested. Please sign in again later.")
    acct = conn.execute("SELECT * FROM department_account WHERE id=%s", (c["account_id"],)).fetchone()
    _issue_code(conn, acct, c["id"])
    conn.execute("UPDATE login_challenge SET sends=sends+1 WHERE id=%s", (c["id"],))
    conn.commit()
    return dict(ok=True)


def current_department(request: Request, conn=Depends(db)):
    """The ONLY way a request learns which department it belongs to: the signed-in session."""
    tok = request.cookies.get(COOKIE)
    if not tok:
        raise HTTPException(401, "Please sign in.")
    h = hashlib.sha256(tok.encode()).hexdigest()
    s = conn.execute("""SELECT s.*, a.department_id, a.username, a.email, d.code, d.name
        FROM auth_session s JOIN department_account a ON a.id=s.account_id JOIN department d ON d.id=a.department_id
        WHERE s.token_hash=%s AND NOT s.revoked AND a.active""", (h,)).fetchone()
    if not s or s["expires_at"] < now() or (now() - s["last_seen"]) > timedelta(minutes=IDLE_MINUTES):
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    conn.execute("UPDATE auth_session SET last_seen=now() WHERE token_hash=%s", (h,))
    return dict(account_id=s["account_id"], id=s["department_id"], code=s["code"], name=s["name"],
                username=s["username"], email_hint=mask(s["email"]), token_hash=h)


@router.get("/me")
def me(d=Depends(current_department)):
    from .config import USE_ROOMS
    return dict(department=dict(code=d["code"], name=d["name"]), username=d["username"], email_hint=d["email_hint"], features=dict(rooms=USE_ROOMS))


@router.post("/logout")
def logout(response: Response, d=Depends(current_department), conn=Depends(db)):
    conn.execute("UPDATE auth_session SET revoked=TRUE WHERE token_hash=%s", (d["token_hash"],))
    audit(conn, d["account_id"], d["id"], "logout")
    conn.commit()
    response.delete_cookie(COOKIE)
    return dict(ok=True)


@router.post("/logout-all")
def logout_all(response: Response, d=Depends(current_department), conn=Depends(db)):
    conn.execute("UPDATE auth_session SET revoked=TRUE WHERE account_id=%s", (d["account_id"],))
    audit(conn, d["account_id"], d["id"], "logout_all")
    conn.commit()
    response.delete_cookie(COOKIE)
    return dict(ok=True)


class ChangePw(BaseModel):
    current: str
    new: str


@router.post("/change-password")
def change_password(req: ChangePw, d=Depends(current_department), conn=Depends(db)):
    a = conn.execute("SELECT * FROM department_account WHERE id=%s", (d["account_id"],)).fetchone()
    if not check_password(req.current, a["password_hash"]):
        raise HTTPException(400, "Your current password isn't correct.")
    strong_enough(req.new)
    conn.execute("UPDATE department_account SET password_hash=%s, password_changed_at=now() WHERE id=%s",
                 (hash_password(req.new), a["id"]))
    conn.execute("UPDATE auth_session SET revoked=TRUE WHERE account_id=%s AND token_hash<>%s", (a["id"], d["token_hash"]))
    audit(conn, a["id"], d["id"], "password_changed")
    conn.commit()
    return dict(ok=True)


@router.post("/forgot")
def forgot(req: dict, conn=Depends(db)):
    """Always answers the same way. The link goes only to the registered department email."""
    a = conn.execute("SELECT * FROM department_account WHERE username=%s AND active", (str(req.get("username", "")).strip().lower(),)).fetchone()
    if a:
        tok = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO password_reset (token_hash, account_id, expires_at) VALUES (%s,%s,%s)",
                     (hashlib.sha256(tok.encode()).hexdigest(), a["id"], now() + timedelta(minutes=30)))
        send_email(a["email"], "Reset your Tessellate password",
                   f"Use this code in the reset screen within 30 minutes: {tok}")
        audit(conn, a["id"], a["department_id"], "reset_requested")
        conn.commit()
    return dict(message="If that username exists, a reset message has been sent to the registered department email.")


@router.post("/reset")
def reset(req: dict, conn=Depends(db)):
    h = hashlib.sha256(str(req.get("token", "")).encode()).hexdigest()
    r = conn.execute("SELECT * FROM password_reset WHERE token_hash=%s AND NOT used AND expires_at>now()", (h,)).fetchone()
    if not r:
        raise HTTPException(400, "This reset link has expired. Please request a new one.")
    strong_enough(str(req.get("new_password", "")))
    conn.execute("UPDATE department_account SET password_hash=%s, failed_logins=0, locked_until=NULL, password_changed_at=now() WHERE id=%s",
                 (hash_password(req["new_password"]), r["account_id"]))
    conn.execute("UPDATE password_reset SET used=TRUE WHERE token_hash=%s", (h,))
    conn.execute("UPDATE auth_session SET revoked=TRUE WHERE account_id=%s", (r["account_id"],))
    audit(conn, r["account_id"], None, "password_reset")
    conn.commit()
    return dict(ok=True)


# ---------- self-service sign-up ----------
# A new department proves it controls an official college email address (emailed code) before the account exists.
# An existing department's account can never be taken over this way.
import time  # noqa: E402
_hits = {}
SIGNUP_MINUTES = 15


def allowed_domains():
    return [d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "college.edu").split(",") if d.strip()]


def _rate(ip, limit=10, window=3600):
    t = time.time()
    _hits[ip] = [x for x in _hits.get(ip, []) if t - x < window] + [t]
    if len(_hits[ip]) > limit:
        raise HTTPException(429, "Too many sign-up attempts. Please try again later.")


class SignupReq(BaseModel):
    department_name: str
    email: str
    username: str
    password: str


@router.post("/signup")
def signup(req: SignupReq, request: Request, conn=Depends(db)):
    _rate(request.client.host if request.client else "?")
    name = " ".join(req.department_name.split())
    email, user = req.email.strip().lower(), req.username.strip().lower()
    if not 2 <= len(name) <= 60:
        raise HTTPException(400, "Please enter your department name.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "That email address doesn't look right.")
    if email.split("@")[1] not in allowed_domains():
        raise HTTPException(400, "Please use your official college email address (ending in @" + allowed_domains()[0] + ").")
    if not re.fullmatch(r"[a-z0-9_.-]{2,30}", user):
        raise HTTPException(400, "Username: use 2-30 lowercase letters, numbers, dot, dash or underscore.")
    strong_enough(req.password)
    d = conn.execute("SELECT id FROM department WHERE lower(name)=lower(%s)", (name,)).fetchone()
    if d and conn.execute("SELECT 1 FROM department_account WHERE department_id=%s", (d["id"],)).fetchone():
        raise HTTPException(409, "This department already has an account. Use \u201cForgot password\u201d, or ask whoever set it up.")
    if conn.execute("SELECT 1 FROM department_account WHERE username=%s", (user,)).fetchone():
        raise HTTPException(409, "That username is already taken. Please choose another.")
    if conn.execute("SELECT 1 FROM department_account WHERE lower(email)=%s", (email,)).fetchone():
        raise HTTPException(409, "That email address already belongs to a department account.")
    conn.execute("DELETE FROM signup_request WHERE lower(email)=%s AND NOT used", (email,))
    rid = conn.execute("""INSERT INTO signup_request (department_name, email, username, password_hash, expires_at)
        VALUES (%s,%s,%s,%s,%s) RETURNING id""", (name, email, user, hash_password(req.password), now() + timedelta(minutes=SIGNUP_MINUTES))).fetchone()["id"]
    _send_signup_code(conn, rid, email)
    conn.commit()
    return dict(request_id=str(rid), email_hint=mask(email))


def _send_signup_code(conn, rid, email):
    code = f"{secrets.randbelow(10**6):06d}"
    conn.execute("UPDATE signup_request SET code_hash=%s, attempts=0, last_sent_at=now(), expires_at=%s WHERE id=%s",
                 (code_hash(rid, code), now() + timedelta(minutes=SIGNUP_MINUTES), rid))
    send_email(email, "Confirm your Tessellate department account",
               f"Your confirmation code is {code}. It expires in {SIGNUP_MINUTES} minutes. If you didn't ask for this, ignore this email.")


def _req(conn, rid):
    try:
        return conn.execute("SELECT * FROM signup_request WHERE id=%s", (rid,)).fetchone()
    except Exception:
        conn.rollback()
        return None


@router.post("/signup/verify")
def signup_verify(req: dict, conn=Depends(db)):
    r = _req(conn, req.get("request_id"))
    if not r or r["used"] or r["expires_at"] < now():
        raise HTTPException(400, "This code has expired. Please start again.")
    if r["attempts"] >= MAX_TRIES:
        raise HTTPException(429, "Too many incorrect codes. Please start again.")
    if not hmac.compare_digest(r["code_hash"], code_hash(r["id"], str(req.get("code", "")).strip())):
        conn.execute("UPDATE signup_request SET attempts=attempts+1 WHERE id=%s", (r["id"],))
        conn.commit()
        raise HTTPException(400, "That code isn't correct. Please check it and try again.")
    # re-check at the last moment: someone may have registered meanwhile
    d = conn.execute("SELECT id FROM department WHERE lower(name)=lower(%s)", (r["department_name"],)).fetchone()
    if (d and conn.execute("SELECT 1 FROM department_account WHERE department_id=%s", (d["id"],)).fetchone()) or \
       conn.execute("SELECT 1 FROM department_account WHERE username=%s OR lower(email)=%s", (r["username"], r["email"])).fetchone():
        raise HTTPException(409, "This department or username was just registered. Please start again.")
    if d:
        did = d["id"]
    else:
        base = "DEPT-" + (re.sub(r"[^A-Z0-9]", "", r["department_name"].upper())[:8] or "NEW")
        code, n = base, 1
        while conn.execute("SELECT 1 FROM department WHERE code=%s", (code,)).fetchone():
            n += 1
            code = f"{base}{n}"
        did = conn.execute("INSERT INTO department (code, name) VALUES (%s,%s) RETURNING id", (code, r["department_name"])).fetchone()["id"]
    aid = conn.execute("INSERT INTO department_account (department_id, username, email, password_hash) VALUES (%s,%s,%s,%s) RETURNING id",
                       (did, r["username"], r["email"], r["password_hash"])).fetchone()["id"]
    conn.execute("UPDATE signup_request SET used=TRUE WHERE id=%s", (r["id"],))
    audit(conn, aid, did, "account_created")
    conn.commit()
    return dict(department=r["department_name"], username=r["username"])


@router.post("/signup/resend")
def signup_resend(req: dict, conn=Depends(db)):
    r = _req(conn, req.get("request_id"))
    if not r or r["used"]:
        raise HTTPException(400, "Please start again.")
    if (now() - r["last_sent_at"]).total_seconds() < RESEND_SECONDS:
        raise HTTPException(429, f"Please wait {RESEND_SECONDS} seconds before asking for another code.")
    if r["sends"] >= MAX_SENDS:
        raise HTTPException(429, "Too many codes requested. Please start again later.")
    _send_signup_code(conn, r["id"], r["email"])
    conn.execute("UPDATE signup_request SET sends=sends+1 WHERE id=%s", (r["id"],))
    conn.commit()
    return dict(ok=True)
