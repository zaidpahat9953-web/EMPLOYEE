import os
from datetime import date, datetime, timedelta
from collections import Counter, defaultdict

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

TABLES = {
    "employees": [
        "first_name",
        "last_name",
        "email",
        "phone",
        "profile_pic",
        "department_id",
        "position_id",
        "hire_date",
        "salary",
        "status",
    ],
    "departments": [
        "name",
        "manager",
        "description",
        "status",
    ],
    "positions": [
        "title",
        "department_id",
        "level",
        "description",
        "status",
    ],
    "attendance": [
        "employee_id",
        "attendance_date",
        "check_in",
        "check_out",
        "status",
        "notes",
    ],
    "leaves": [
        "employee_id",
        "type",
        "start_date",
        "end_date",
        "status",
        "reason",
    ],
    "payroll": [
        "employee_id",
        "period",
        "basic_salary",
        "bonus",
        "deductions",
        "net_salary",
        "payment_date",
        "status",
    ],
}

NUMERIC_FIELDS = {
    "id",
    "department_id",
    "position_id",
    "employee_id",
    "salary",
    "basic_salary",
    "bonus",
    "deductions",
    "net_salary",
}


def require_supabase() -> Client:
    if supabase is None:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be configured.")
    return supabase


def clean_payload(table: str, payload: dict, partial: bool = False) -> dict:
    allowed = set(TABLES[table])
    cleaned = {}

    for key, value in (payload or {}).items():
        if key not in allowed:
            continue

        if value == "":
            value = None

        if key in NUMERIC_FIELDS and value is not None:
            try:
                value = float(value) if key in {"salary", "basic_salary", "bonus", "deductions", "net_salary"} else int(value)
            except (ValueError, TypeError):
                value = None

        cleaned[key] = value

    if table == "payroll":
        basic = cleaned.get("basic_salary")
        bonus = cleaned.get("bonus")
        deductions = cleaned.get("deductions")
        if basic is not None and "net_salary" not in cleaned:
            cleaned["net_salary"] = float(basic or 0) + float(bonus or 0) - float(deductions or 0)

    if not partial:
        defaults = {
            "departments": {"status": "Active"},
            "positions": {"status": "Open"},
            "employees": {"status": "Active"},
            "attendance": {"status": "Present"},
            "leaves": {"status": "Pending"},
            "payroll": {"status": "Draft", "bonus": 0, "deductions": 0},
        }
        for key, value in defaults.get(table, {}).items():
            cleaned.setdefault(key, value)

    return cleaned


def table_select(table: str):
    db = require_supabase()
    return db.table(table).select("*").order("id", desc=False).execute().data or []


def table_get(table: str, row_id: int):
    db = require_supabase()
    result = db.table(table).select("*").eq("id", row_id).single().execute()
    return result.data


def table_insert(table: str, payload: dict):
    db = require_supabase()
    result = db.table(table).insert(payload).execute()
    data = result.data or []
    return data[0] if data else payload


def table_update(table: str, row_id: int, payload: dict):
    db = require_supabase()
    result = db.table(table).update(payload).eq("id", row_id).execute()
    data = result.data or []
    return data[0] if data else table_get(table, row_id)


def table_delete(table: str, row_id: int):
    db = require_supabase()
    result = db.table(table).delete().eq("id", row_id).execute()
    return result.data or []


def parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return None


@app.errorhandler(Exception)
def handle_error(exc):
    return jsonify({"error": str(exc)}), 500


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "JavaGoat HR"})


@app.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    email = body.get("email")
    password = body.get("password")

    if email == "admin@javagoat.hr" and password == "password123":
        return jsonify({
            "token": "javagoat-demo-token",
            "user": {
                "email": "admin@javagoat.hr",
                "name": "Admin",
                "role": "HR Administrator",
            },
        })

    return jsonify({"error": "Invalid email or password"}), 401


def register_crud(table_name: str):
    endpoint_base = f"/api/{table_name}"

    def list_rows():
        return jsonify(table_select(table_name))

    def create_row():
        payload = clean_payload(table_name, request.get_json(silent=True) or {}, partial=False)
        if not payload:
            return jsonify({"error": "No valid fields supplied"}), 400
        return jsonify(table_insert(table_name, payload)), 201

    def get_row(row_id):
        row = table_get(table_name, row_id)
        if not row:
            return jsonify({"error": f"{table_name[:-1].title()} not found"}), 404
        return jsonify(row)

    def update_row(row_id):
        payload = clean_payload(table_name, request.get_json(silent=True) or {}, partial=True)
        if not payload:
            return jsonify({"error": "No valid fields supplied"}), 400
        return jsonify(table_update(table_name, row_id, payload))

    def delete_row(row_id):
        table_delete(table_name, row_id)
        return jsonify({"ok": True})

    app.add_url_rule(endpoint_base, f"{table_name}_list", list_rows, methods=["GET"])
    app.add_url_rule(endpoint_base, f"{table_name}_create", create_row, methods=["POST"])
    app.add_url_rule(f"{endpoint_base}/<int:row_id>", f"{table_name}_get", get_row, methods=["GET"])
    app.add_url_rule(f"{endpoint_base}/<int:row_id>", f"{table_name}_update", update_row, methods=["PUT"])
    app.add_url_rule(f"{endpoint_base}/<int:row_id>", f"{table_name}_delete", delete_row, methods=["DELETE"])


for table in TABLES:
    register_crud(table)


@app.get("/api/dashboard/stats")
def dashboard_stats():
    employees = table_select("employees")
    departments = table_select("departments")
    positions = table_select("positions")
    attendance = table_select("attendance")
    payroll = table_select("payroll")

    departments_by_id = {row["id"]: row for row in departments}
    positions_by_id = {row["id"]: row for row in positions}

    today = date.today().isoformat()
    present_today = sum(
        1
        for row in attendance
        if row.get("attendance_date") == today and row.get("status") in {"Present", "Late", "Remote"}
    )

    month_labels = []
    month_counts = defaultdict(int)
    now = date.today().replace(day=1)

    for i in range(11, -1, -1):
        month = (now - timedelta(days=i * 31)).replace(day=1)
        key = month.strftime("%Y-%m")
        label = month.strftime("%b")
        if key not in [m[0] for m in month_labels]:
            month_labels.append((key, label))

    month_labels = month_labels[-12:]

    for emp in employees:
        hired = parse_iso_date(emp.get("hire_date") or emp.get("created_at"))
        if hired:
            key = hired.strftime("%Y-%m")
            month_counts[key] += 1

    dept_counts = Counter()
    for emp in employees:
        dept_id = emp.get("department_id")
        dept_name = departments_by_id.get(dept_id, {}).get("name", "Unassigned")
        dept_counts[dept_name] += 1

    status_counts = Counter(emp.get("status") or "Unknown" for emp in employees)

    last_14 = [date.today() - timedelta(days=i) for i in range(13, -1, -1)]
    attendance_counts = []
    for day in last_14:
        day_key = day.isoformat()
        attendance_counts.append(
            sum(
                1
                for row in attendance
                if row.get("attendance_date") == day_key and row.get("status") in {"Present", "Late", "Remote"}
            )
        )

    position_employees = []
    for emp in employees:
        pos = positions_by_id.get(emp.get("position_id"), {})
        dept = departments_by_id.get(emp.get("department_id"), {})
        name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip() or emp.get("email") or "Employee"
        position_employees.append({
            "id": emp.get("id"),
            "name": name,
            "profile_pic": emp.get("profile_pic"),
            "position": pos.get("title") or "Unassigned",
            "department": dept.get("name") or "Unassigned",
        })

    return jsonify({
        "cards": {
            "employees": len(employees),
            "departments": len(departments),
            "positions": len(positions),
            "present_today": present_today,
            "payroll_runs": len(payroll),
        },
        "hiring_trend": {
            "labels": [label for _, label in month_labels],
            "data": [month_counts[key] for key, _ in month_labels],
        },
        "department_mix": {
            "labels": list(dept_counts.keys()) or ["No Data"],
            "data": list(dept_counts.values()) or [0],
        },
        "attendance_trend": {
            "labels": [day.strftime("%b %d") for day in last_14],
            "data": attendance_counts,
        },
        "status_breakdown": {
            "labels": list(status_counts.keys()) or ["No Data"],
            "data": list(status_counts.values()) or [0],
        },
        "position_employees": position_employees,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
