"""Smoke-test a deployed instance (public URL or localhost).

    python scripts/check_deployment.py https://your-app.example.com [--email you@school.edu --password '...']

Without credentials only the public checks run; with them it also signs in, reads /me, refreshes and signs out.
Prints PASS/FAIL per check, never prints the password or tokens."""
import argparse
import sys

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("--email")
ap.add_argument("--password")
a = ap.parse_args()
base = a.url.rstrip("/")
fails = 0


def check(name, ok, detail=""):
    global fails
    fails += 0 if ok else 1
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


c = httpx.Client(base_url=base, timeout=30, follow_redirects=False)
https = base.startswith("https://")
local = any(h in base for h in ("localhost", "127.0.0.1"))
check("served over HTTPS", https or local, "use https:// for a public site")
r = c.get("/api/health")
check("health endpoint", r.status_code == 200, str(r.status_code))
cfg = c.get("/api/auth/config").json() if r.status_code == 200 else {}
print(f"     auth_mode={cfg.get('auth_mode')} environment={cfg.get('environment')}")
if not local:
    check("production environment flag", cfg.get("environment") == "production", str(cfg.get("environment")))
    check("Firebase auth mode (not local dev logins)", cfg.get("auth_mode") == "firebase", str(cfg.get("auth_mode")))
r = c.get("/")
check("front-end page served", r.status_code == 200 and "<div id=\"root\"" in r.text, str(r.status_code))
csp = r.headers.get("content-security-policy", "")
check("SPA has a CSP", "default-src" in csp)
check("nosniff + frame protection", r.headers.get("x-content-type-options") == "nosniff" and
      ("frame-ancestors" in csp or r.headers.get("x-frame-options")))
check("API requires a login (401)", c.get("/api/auth/me").status_code == 401)
check("admin API not open (401/403)", c.get("/api/admin/users").status_code in (401, 403))
check("unknown API path is JSON 404", c.get("/api/nope").status_code == 404)
r = c.post("/api/auth/login", json={"identifier": "nobody@example.com", "password": "wrong-password-1"})
check("bad login -> generic 401", r.status_code == 401 and "Incorrect" in r.text, str(r.status_code))
for p in ("/.env", "/backend/.env", "/data/app.db", "/.git/config"):
    rr = c.get(p)
    check(f"{p} not exposed", rr.status_code != 200 or "<div id=\"root\"" in rr.text, str(rr.status_code))

if a.email and a.password:
    r = c.post("/api/auth/login", json={"identifier": a.email, "password": a.password})
    check("sign-in works", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    if r.status_code == 200:
        sc = r.headers.get("set-cookie", "").lower()
        check("refresh cookie HttpOnly", "httponly" in sc)
        check("refresh cookie Secure + SameSite", ("secure" in sc or local) and "samesite" in sc, sc[:80])
        H = {"Authorization": "Bearer " + r.json()["access_token"]}
        m = c.get("/api/auth/me", headers=H)
        check("/me returns the role", m.status_code == 200 and m.json().get("role"), str(m.status_code))
        print("     role =", m.json().get("role"))
        check("session refresh", c.post("/api/auth/refresh").status_code == 200)
        check("sign-out", c.post("/api/auth/logout", headers=H).status_code == 200)
print(f"\n{'ALL CHECKS PASSED' if not fails else str(fails) + ' CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
