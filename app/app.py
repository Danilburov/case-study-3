from functools import wraps
import os
from urllib.parse import urlencode

import jwt
import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    abort,
    flash,
    session,
)
from sqlalchemy import create_engine, Boolean, Column, Integer, String, select
from sqlalchemy.orm import declarative_base, Session

#configuration

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

#DB (RDS)
DB_URL = os.environ.get("DB_URL")

if not DB_URL:
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME")

    if not all([db_user, db_password, db_host, db_name]):
        raise RuntimeError(
            "DB configuration missing – either DB_URL must be set or "
            "DB_USER, DB_PASSWORD, DB_HOST, DB_NAME must all be defined."
        )

    DB_URL = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

engine = create_engine(DB_URL, future=True)
Base = declarative_base()

class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    department = Column(String(100), nullable=False)
    title = Column(String(100))      # maps to "Role" in requirements
    manager = Column(String(100))
    active = Column(Boolean, nullable=False, default=True)

Base.metadata.create_all(engine)

#Keycloak / OIDC

KEYCLOAK_BASE_URL = os.environ.get("KEYCLOAK_BASE_URL", "").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "innovatech")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "hr-portal")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET")
HR_APP_BASE_URL = os.environ.get("HR_APP_BASE_URL", "http://localhost:5000").rstrip("/")

if not KEYCLOAK_BASE_URL or not KEYCLOAK_CLIENT_SECRET:
    raise RuntimeError("KEYCLOAK_BASE_URL and KEYCLOAK_CLIENT_SECRET must be set")

OIDC_AUTH_URL = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/auth"
OIDC_TOKEN_URL = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
OIDC_LOGOUT_URL = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/logout"
OIDC_USERINFO_URL = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/userinfo"
OIDC_CERTS_URL = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

JWKS = requests.get(OIDC_CERTS_URL, timeout=5).json()

def _get_signing_key(token: str):
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    for k in JWKS["keys"]:
        if k["kid"] == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(k)
    raise RuntimeError("No matching signing key found for kid")

def decode_access_token(token: str):
    key = _get_signing_key(token)
    return jwt.decode(
        token,
        key=key,
        algorithms=["RS256"],
        audience=KEYCLOAK_CLIENT_ID,
    )

def current_user_payload():
    token = session.get("access_token")
    if not token:
        return None
    try:
        return decode_access_token(token)
    except Exception:
        return None

def current_roles():
    payload = current_user_payload()
    if not payload:
        return []
    realm_access = payload.get("realm_access", {})
    return realm_access.get("roles", [])

#decorators
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "access_token" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper

def require_role(*required_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            roles = set(current_roles())
            if not roles.intersection(required_roles):
                return ("Forbidden", 403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator

#helpers
def get_db_session():
    return Session(engine, future=True)


def get_departments(session: Session):
    stmt = select(Employee.department).distinct().order_by(Employee.department)
    return [d for d in session.execute(stmt).scalars().all() if d]

#auth routes
@app.get("/login")
def login():
    redirect_uri = f"{HR_APP_BASE_URL}{url_for('oidc_callback')}"
    params = {
        "client_id": KEYCLOAK_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
    }
    return redirect(f"{OIDC_AUTH_URL}?{urlencode(params)}")

@app.get("/oidc/callback")
def oidc_callback():
    code = request.args.get("code")
    if not code:
        return "Missing code", 400

    redirect_uri = f"{HR_APP_BASE_URL}{url_for('oidc_callback')}"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": KEYCLOAK_CLIENT_ID,
        "client_secret": KEYCLOAK_CLIENT_SECRET,
    }

    resp = requests.post(OIDC_TOKEN_URL, data=data, timeout=5)
    if resp.status_code != 200:
        return f"Token error: {resp.text}", 400

    tokens = resp.json()
    access_token = tokens.get("access_token")
    id_token = tokens.get("id_token")

    session["access_token"] = access_token
    session["id_token"] = id_token

    uinfo = requests.get(
        OIDC_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=5,
    )
    if uinfo.status_code == 200:
        session["userinfo"] = uinfo.json()

    flash("Logged in successfully.", "success")
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    session.clear()
    redirect_uri = f"{HR_APP_BASE_URL}{url_for('index')}"
    params = {
        "client_id": KEYCLOAK_CLIENT_ID,
        "post_logout_redirect_uri": redirect_uri,
    }
    return redirect(f"{OIDC_LOGOUT_URL}?{urlencode(params)}")

# Portal routes
@app.get("/")
@login_required
def index():
    with get_db_session() as s:
        total = s.query(Employee).count()
        active_count = s.query(Employee).filter_by(active=True).count()
        inactive_count = s.query(Employee).filter_by(active=False).count()
        departments = get_departments(s)

    return render_template(
        "index.html",
        total=total,
        active_count=active_count,
        inactive_count=inactive_count,
        departments=departments,
    )

@app.get("/employees")
@login_required
def employees_list():
    department = request.args.get("department") or ""
    active_filter = request.args.get("active") or ""

    with get_db_session() as s:
        stmt = select(Employee)
        if department:
            stmt = stmt.where(Employee.department == department)
        if active_filter == "true":
            stmt = stmt.where(Employee.active.is_(True))
        elif active_filter == "false":
            stmt = stmt.where(Employee.active.is_(False))

        employees = s.execute(stmt).scalars().all()
        all_departments = get_departments(s)

    return render_template(
        "employees.html",
        employees=employees,
        all_departments=all_departments,
        current_department=department,
        current_active=active_filter,
    )

@app.get("/employees/<int:emp_id>")
@login_required
def employee_detail(emp_id):
    with get_db_session() as s:
        emp = s.get(Employee, emp_id)
        if not emp:
            abort(404)
    return render_template("employee_detail.html", employee=emp)

@app.get("/employees/new")
@login_required
@require_role("hr_admin", "hr_manager")
def employee_new_form():
    return render_template("employee_form.html", mode="create", employee=None)

@app.post("/employees/new")
@login_required
@require_role("hr_admin", "hr_manager")
def employee_create():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    department = request.form.get("department", "").strip()
    title = request.form.get("title", "").strip()
    manager = request.form.get("manager", "").strip()
    active_str = request.form.get("active", "true")

    if not name or not email or not department:
        flash("Name, email, and department are required.", "error")
        return redirect(url_for("employee_new_form"))

    active = active_str.lower() == "true"

    with get_db_session() as s:
        emp = Employee(
            name=name,
            email=email,
            department=department,
            title=title,
            manager=manager or None,
            active=active,
        )
        s.add(emp)
        s.commit()
        flash(f"Employee {emp.name} created.", "success")

    return redirect(url_for("employees_list"))

@app.get("/employees/<int:emp_id>/edit")
@login_required
@require_role("hr_admin", "hr_manager")
def employee_edit_form(emp_id):
    with get_db_session() as s:
        emp = s.get(Employee, emp_id)
        if not emp:
            abort(404)
    return render_template("employee_form.html", mode="edit", employee=emp)

@app.post("/employees/<int:emp_id>/edit")
@login_required
@require_role("hr_admin", "hr_manager")
def employee_update(emp_id):
    with get_db_session() as s:
        emp = s.get(Employee, emp_id)
        if not emp:
            abort(404)

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        department = request.form.get("department", "").strip()
        title = request.form.get("title", "").strip()
        manager = request.form.get("manager", "").strip()
        active_str = request.form.get("active", "true")

        if not name or not email or not department:
            flash("Name, email, and department are required.", "error")
            return redirect(url_for("employee_edit_form", emp_id=emp_id))

        emp.name = name
        emp.email = email
        emp.department = department
        emp.title = title
        emp.manager = manager or None
        emp.active = active_str.lower() == "true"

        s.commit()
        flash(f"Employee {emp.name} updated.", "success")

    return redirect(url_for("employee_detail", emp_id=emp_id))

@app.post("/employees/<int:emp_id>/delete")
@login_required
@require_role("hr_admin", "hr_manager")
def employee_delete(emp_id):
    with get_db_session() as s:
        emp = s.get(Employee, emp_id)
        if not emp:
            abort(404)
        s.delete(emp)
        s.commit()
        flash(f"Employee {emp.name} deleted.", "success")
    return redirect(url_for("employees_list"))

@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
