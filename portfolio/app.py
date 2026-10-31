import hmac
import io
import os
import json
from pathlib import Path
from urllib.parse import quote

from werkzeug.security import check_password_hash, generate_password_hash
from xml.sax.saxutils import escape

from flask import (Flask, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

app = Flask(__name__)
BASE = Path(__file__).parent
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMe@123")
PW_FILE = BASE / "admin_pw.json"


def password_ok(pw):
    # If you changed the password in Settings, check the saved (hashed) one.
    # Otherwise use ADMIN_PASSWORD.
    if PW_FILE.exists():
        with open(PW_FILE, encoding="utf-8") as f:
            return check_password_hash(json.load(f)["hash"], pw)
    return hmac.compare_digest(pw, ADMIN_PASSWORD)
REQUIRED = ["name", "roles", "email", "phone", "linkedin", "about", "experience",
            "projects", "skills", "education", "certs", "languages"]


def load_data():
    # Read on every request, so editing data.json updates the site
    with open(BASE / "data.json", encoding="utf-8") as f:
        return json.load(f)


def build_resume_pdf(d):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"{d['name']} - Resume", author=d["name"],
    )
    ss = getSampleStyleSheet()
    name_s = ParagraphStyle("name", parent=ss["Title"], fontSize=22, alignment=0, spaceAfter=2)
    head_s = ParagraphStyle("head", parent=ss["Heading2"], fontSize=12.5,
                            textColor=colors.HexColor("#4b3fd1"), spaceBefore=10, spaceAfter=4)
    body_s = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10, leading=14)
    bullet_s = ParagraphStyle("bullet", parent=body_s, leftIndent=12, bulletIndent=2)
    e = lambda t: escape(str(t))

    s = [
        Paragraph(e(d["name"]), name_s),
        Paragraph(e(f'{d["email"]} | {d["phone"]} | {d["linkedin"]}'), body_s),
        Paragraph("Career Objective", head_s),
        Paragraph(e(d["about"]), body_s),
    ]

    x = d["experience"]
    s += [
        Paragraph("Professional Experience", head_s),
        Paragraph(f'<b>{e(x["title"])}</b> - {e(x["period"])}', body_s),
        Paragraph(e(x["org"]), body_s),
    ]
    s += [Paragraph(e(p), bullet_s, bulletText="•") for p in x["points"]]

    s.append(Paragraph("Projects", head_s))
    for p in d["projects"]:
        s.append(Paragraph(f'<b>{e(p["title"])}</b> ({e(p["year"])})', body_s))
        s.append(Paragraph(e(p["desc"]), bullet_s, bulletText="•"))
        s.append(Spacer(1, 3))

    s.append(Paragraph("Technical Skills", head_s))
    for k in d["skills"]:
        s.append(Paragraph(f'<b>{e(k["category"])}:</b> {e(", ".join(k["items"]))}', body_s))
    s.append(Paragraph("Education", head_s))
    for ed in d["education"]:
        line = f'<b>{e(ed["title"])}</b>' + (f' ({e(ed["period"])})' if ed["period"] else "")
        s += [Paragraph(line, body_s), Paragraph(f'{e(ed["org"])} - {e(ed["note"])}', body_s)]

    s.append(Paragraph("Courses and Certificates", head_s))
    s += [Paragraph(e(c), bullet_s, bulletText="•") for c in d["certs"]]
    s += [Paragraph("Languages", head_s), Paragraph(e(", ".join(d["languages"])), body_s)]

    doc.build(s)
    buf.seek(0)
    return buf




@app.route("/")
def home():
    d = load_data()
    subject = f"Opportunity for {d['name']}"
    body = (f"Hello {d['name'].split()[0]},\n\n"
            "I saw your portfolio and would like to connect with you.\n\nRegards,")
    gmail = ("https://mail.google.com/mail/?view=cm&fs=1&to=" + d["email"]
             + "&su=" + quote(subject) + "&body=" + quote(body))
    mailto = f"mailto:{d['email']}?subject={quote(subject)}&body={quote(body)}"
    return render_template("index.html", d=d, gmail=gmail, mailto=mailto)


@app.route("/download-resume")
def download_resume():
    d = load_data()
    return send_file(
        build_resume_pdf(d),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{d['name'].replace(' ', '_')}_Resume.pdf",
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    error = None
    if request.method == "POST":
        if password_ok(request.form.get("password", "")):
            session["admin"] = True
            return render_template("admin.html", logged=True, error=None, d=load_data())
        session.pop("admin", None)
        error = "Wrong password"
    else:
        session.pop("admin", None)  # every visit to Settings asks for the password
    return render_template("admin.html", logged=False, error=error, d=None)


@app.route("/admin/save", methods=["POST"])
def admin_save():
    if not session.get("admin"):
        return jsonify(ok=False), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or any(k not in data for k in REQUIRED):
        return jsonify(ok=False), 400
    with open(BASE / "data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return jsonify(ok=True)


@app.route("/admin/export")
def admin_export():
    if not session.get("admin"):
        return redirect(url_for("admin"))
    return send_file(BASE / "data.json", as_attachment=True, download_name="data.json")


@app.route("/admin/password", methods=["POST"])
def admin_password():
    if not session.get("admin"):
        return jsonify(ok=False, msg="Please login again"), 401
    j = request.get_json(silent=True) or {}
    cur, new, conf = j.get("current", ""), j.get("new", ""), j.get("confirm", "")
    if not password_ok(cur):
        return jsonify(ok=False, msg="Current password is wrong"), 400
    if len(new) < 8:
        return jsonify(ok=False, msg="New password must be at least 8 characters"), 400
    if new != conf:
        return jsonify(ok=False, msg="New passwords do not match"), 400
    with open(PW_FILE, "w", encoding="utf-8") as f:
        json.dump({"hash": generate_password_hash(new)}, f)
    return jsonify(ok=True, msg="Password changed ✔")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)