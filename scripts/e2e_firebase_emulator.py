"""Firebase Authentication end-to-end test against the *Firebase Auth emulator*.

Needs the emulator on 127.0.0.1:9099:
    npx firebase-tools emulators:start --only auth --project demo-adaptive
No real Google project or credentials are used.  Run with the backend venv's python:
    python scripts/e2e_firebase_emulator.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
EMU = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
PORT = int(os.environ.get("E2E_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}/api"
PW = "Str0ng-Passw0rd!x"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def main() -> int:
    try:
        httpx.get(f"http://{EMU}/", timeout=3)
    except Exception:
        print(f"Auth emulator not reachable on {EMU}. Start it first (see docstring).")
        return 2
    httpx.delete(f"http://{EMU}/emulator/v1/projects/demo-adaptive/accounts", timeout=5)
    tmp = Path(tempfile.mkdtemp(prefix="fbe2e-"))
    env = dict(os.environ, AUTH_MODE="firebase", FIREBASE_AUTH_EMULATOR_HOST=EMU, FIREBASE_PROJECT_ID="demo-adaptive",
               DATA_DIR=str(tmp), ENVIRONMENT="development", BLOCKCHAIN_ENABLED="false", SERVE_FRONTEND="false",
               DATABASE_URL=f"sqlite:///{tmp}/app.db", PYTHONPATH=str(BACKEND))
    py = sys.executable
    cwd = str(BACKEND)
    r = subprocess.run([py, "-m", "app.cli", "create-admin", "--email", "admin@example.com", "--name", "FB Admin"],
                       cwd=cwd, env=env, capture_output=True, text=True)
    check("cli create-admin (firebase mode)", r.returncode in (0, None) and "created" in r.stdout, r.stdout + r.stderr)

    os.environ.update(FIREBASE_AUTH_EMULATOR_HOST=EMU)
    import firebase_admin
    from firebase_admin import auth as fa
    from google.auth.credentials import AnonymousCredentials
    if not firebase_admin._apps:
        firebase_admin.initialize_app(AnonymousCredentials(), {"projectId": "demo-adaptive"})
    uid = fa.get_user_by_email("admin@example.com").uid
    check("account exists in emulator, unverified", fa.get_user(uid).email_verified is False)
    fa.update_user(uid, password=PW)

    srv = subprocess.Popen([py, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
                           cwd=cwd, env=env, stdout=open(tmp / "srv.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{BASE}/auth/config", timeout=2).status_code == 200:
                    break
            except Exception:
                time.sleep(0.5)
        c = httpx.Client(base_url=BASE, timeout=20)
        check("config reports firebase mode", c.get("/auth/config").json().get("auth_mode") == "firebase")

        r = c.post("/auth/login", json={"identifier": "admin@example.com", "password": PW})
        check("unverified e-mail is blocked (403)", r.status_code == 403 and r.headers.get("x-auth-error") == "email_not_verified",
              f"{r.status_code} {r.text[:120]}")
        r = c.post("/auth/login", json={"identifier": "admin@example.com", "password": "wrong-password-1"})
        check("wrong password -> generic 401", r.status_code == 401 and "Incorrect" in r.text)
        r = c.post("/auth/login", json={"identifier": "nobody@example.com", "password": PW})
        check("unknown account -> same generic 401", r.status_code == 401 and "Incorrect" in r.text)

        fa.update_user(uid, email_verified=True)
        c = httpx.Client(base_url=BASE, timeout=20)
        r = c.post("/auth/login", json={"identifier": "admin@example.com", "password": PW})
        check("verified login succeeds", r.status_code == 200 and r.json().get("access_token"), r.text[:150])
        tok = r.json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}
        check("real Firebase ID token has 3 JWT parts", tok.count(".") == 2)
        check("refresh cookie is httpOnly", "httponly" in r.headers.get("set-cookie", "").lower())
        me = c.get("/auth/me", headers=H)
        check("/me with Firebase token", me.status_code == 200 and me.json()["role"] == "admin")
        check("admin endpoint reachable", c.get("/admin/users", headers=H).status_code == 200)

        r = c.post("/auth/refresh")
        check("refresh issues new token", r.status_code == 200 and r.json().get("access_token"), r.text[:150])

        bad = tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB")
        check("tampered token rejected", c.get("/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401)
        check("garbage token rejected", c.get("/auth/me", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401)
        check("missing token rejected", c.get("/auth/me").status_code == 401)

        r = c.post("/auth/password-reset", json={"identifier": "admin@example.com"})
        r2 = c.post("/auth/password-reset", json={"identifier": "ghost@example.com"})
        check("password reset: identical response for known/unknown", r.status_code == r2.status_code == 200 and r.json() == r2.json())
        oob = httpx.get(f"http://{EMU}/emulator/v1/projects/demo-adaptive/oobCodes").json().get("oobCodes", [])
        resets = sorted({o["email"] for o in oob if o["requestType"] == "PASSWORD_RESET"})
        check("reset e-mail issued only for the real account", "admin@example.com" in resets and "ghost@example.com" not in resets, str(resets))

        # admin provisions a faculty user; user is created in Firebase, unverified, reset link issued
        r = c.post("/admin/users", headers=H, json={"email": "fac@example.com", "full_name": "Fac One", "role": "faculty",
                                                    "faculty": {"employee_id": "EMP9", "department": "CSE", "designation": "Lecturer"}})
        check("admin provisions user (201)", r.status_code == 201, r.text[:150])
        fuid = fa.get_user_by_email("fac@example.com").uid
        check("provisioned user exists in Firebase", bool(fuid))

        # logout revokes
        time.sleep(1.1)
        r = c.post("/auth/logout", headers=H)
        check("logout ok", r.status_code == 200)
        time.sleep(1.1)
        check("old access token rejected after logout", c.get("/auth/me", headers=H).status_code == 401)
        check("refresh rejected after logout", httpx.Client(base_url=BASE).post("/auth/refresh").status_code == 401)

        # deactivate/reactivate via admin API (second admin session)
        fa.update_user(fuid, password=PW, email_verified=True)
        time.sleep(1.1)
        r = c.post("/auth/login", json={"identifier": "admin@example.com", "password": PW})
        check("re-login after logout works", r.status_code == 200, r.text[:120])
        H = {"Authorization": f"Bearer {r.json()['access_token']}"}
        c2 = httpx.Client(base_url=BASE, timeout=20)
        r = c2.post("/auth/login", json={"identifier": "fac@example.com", "password": PW})
        check("provisioned faculty can log in", r.status_code == 200, r.text[:120])
        fH = {"Authorization": f"Bearer {r.json()['access_token']}"}
        check("faculty denied admin endpoint (403)", c2.get("/admin/users", headers=fH).status_code == 403)
        fid = r.json()["user"]["id"]
        r = c.patch(f"/admin/users/{fid}", headers=H, json={"is_active": False})
        check("admin deactivates faculty", r.status_code == 200, r.text[:120])
        check("Firebase account disabled in emulator", fa.get_user(fuid).disabled is True)
        time.sleep(1.1)
        check("deactivated user's token rejected", c2.get("/auth/me", headers=fH).status_code in (401, 403))
        r = httpx.post(f"{BASE}/auth/login", json={"identifier": "fac@example.com", "password": PW})
        check("deactivated user cannot log in", r.status_code in (401, 403), str(r.status_code))


        # ---- all five roles: provision -> verify e-mail/set password in Firebase -> log in -> role-correct access ----
        H = {"Authorization": f"Bearer {c.post('/auth/login', json={'identifier': 'admin@example.com', 'password': PW}).json()['access_token']}"}
        specs = {
            "student": {"email": "stu@example.com", "full_name": "Stu Dent", "role": "student",
                        "student": {"roll_number": "R-1001", "department": "CSE", "semester": 3}},
            "faculty": {"email": "fac2@example.com", "full_name": "Fac Two", "role": "faculty",
                        "faculty": {"employee_id": "EMP77", "department": "CSE", "designation": "Lecturer"}},
            "advisor": {"email": "adv@example.com", "full_name": "Adv Isor", "role": "advisor"},
            "management": {"email": "mgmt@example.com", "full_name": "Man Agement", "role": "management"},
        }
        probes = {"student": ("/student/dashboard", {"/advisor/dashboard", "/management/analytics", "/admin/users"}),
                  "faculty": ("/faculty/subjects", {"/advisor/dashboard", "/management/analytics", "/admin/users", "/student/dashboard"}),
                  "advisor": ("/advisor/dashboard", {"/management/analytics", "/admin/users", "/student/dashboard"}),
                  "management": ("/management/analytics", {"/advisor/dashboard", "/admin/users", "/student/dashboard"}),
                  "admin": ("/admin/users", {"/advisor/dashboard", "/management/analytics", "/student/dashboard"})}
        sessions = {"admin": (c, H)}
        for role, body in specs.items():
            r = c.post("/admin/users", headers=H, json=body)
            check(f"[{role}] provisioned by admin", r.status_code == 201, r.text[:120])
            u = fa.get_user_by_email(body["email"])
            fa.update_user(u.uid, password=PW, email_verified=True)
            cl = httpx.Client(base_url=BASE, timeout=20)
            r = cl.post("/auth/login", json={"identifier": body["email"], "password": PW})
            ok = r.status_code == 200 and r.json()["user"]["role"] == role
            check(f"[{role}] logs in with Firebase and gets role '{role}'", ok, r.text[:120])
            if ok:
                sessions[role] = (cl, {"Authorization": f"Bearer {r.json()['access_token']}"})
        for role, (own, forbidden) in probes.items():
            if role not in sessions:
                continue
            cl, hh = sessions[role]
            rr = cl.get(own, headers=hh)
            check(f"[{role}] can open its own area {own}", rr.status_code == 200, f"{rr.status_code} {rr.text[:80]}")
            for path in sorted(forbidden):
                rr = cl.get(path, headers=hh)
                check(f"[{role}] blocked from {path}", rr.status_code == 403, str(rr.status_code))
        if "student" in sessions:
            cl, hh = sessions["student"]
            r = cl.post("/auth/login", json={"identifier": "R-1001", "password": PW})
            check("student can also sign in with roll number", r.status_code == 200, f"{r.status_code} {r.text[:80]}")

        # a valid Firebase identity that was never provisioned must not be auto-created
        stray = fa.create_user(email="stray@example.com", password=PW, email_verified=True)
        d = httpx.post(f"http://{EMU}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=k",
                       json={"email": "stray@example.com", "password": PW, "returnSecureToken": True}).json()
        r = httpx.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {d['idToken']}"})
        check("unprovisioned Firebase identity -> 403, no auto-create", r.status_code == 403, r.text[:100])
        r = httpx.post(f"{BASE}/auth/login", json={"identifier": "stray@example.com", "password": PW})
        check("unprovisioned identity cannot log in", r.status_code == 401)
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except Exception:
            srv.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
