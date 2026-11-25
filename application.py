import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, flash, redirect, render_template, request, session, url_for

import db
from scraper import download_cover, get_book_details, search_books


TZ = ZoneInfo("Europe/Istanbul")
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "yerel-gelistirme-anahtari")

COVER_DIR = BASE_DIR / "static" / "kapaklar"
COVER_DIR.mkdir(parents=True, exist_ok=True)
db.init_db()


@app.before_request
def require_login():
    if request.endpoint in {"login", "static"}:
        return None
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "test" and request.form.get("password") == "123":
            session["logged_in"] = True
            return redirect(url_for("library"))
        flash("Kullanıcı adı veya şifre hatalı.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def library():
    shelf = request.args.get("shelf", "okunuyor")
    if shelf not in {"okunacak", "okunuyor", "okundu"}:
        shelf = "okunuyor"
    conn = db.get_db()
    books = conn.execute(
        "SELECT * FROM books WHERE status = ? ORDER BY created_at DESC, id DESC", (shelf,)
    ).fetchall()
    reading_logs = {}
    for book in books:
        reading_logs[book["id"]] = conn.execute(
            "SELECT id, page, logged_at FROM reading_logs WHERE book_id = ? "
            "ORDER BY logged_at DESC, id DESC",
            (book["id"],),
        ).fetchall()
    conn.close()
    return render_template(
        "library.html",
        books=books,
        reading_logs=reading_logs,
        active_shelf=shelf,
    )


@app.route("/recommendations")
def recommendations():
    conn = db.get_db()
    seeds = conn.execute(
        """
        SELECT title, author, rating, status
        FROM books
        WHERE status = 'okundu' OR rating >= 4
        ORDER BY rating DESC, finish_date DESC, created_at DESC
        LIMIT 5
        """
    ).fetchall()
    owned = conn.execute("SELECT title, isbn FROM books").fetchall()
    conn.close()

    queries = []
    for book in seeds:
        query = (book["author"] or "").strip() or book["title"]
        if query.casefold() not in {item.casefold() for item in queries}:
            queries.append(query)
        if len(queries) == 3:
            break

    results = []
    message = None
    for query in queries:
        found, state = search_books(query)
        if state == "site-error":
            message = "Kitapyurdu'na şu an bağlanılamıyor; öneriler yüklenemedi."
            continue
        for candidate in found or []:
            title_key = candidate.get("title", "").strip().casefold()
            author_key = candidate.get("author", "").strip().casefold()
            if not title_key:
                continue
            if any(title_key == (book["title"] or "").strip().casefold() for book in owned):
                continue
            duplicate = any(
                title_key == item["title"].casefold()
                and author_key == item["author"].casefold()
                for item in results
            )
            if not duplicate:
                candidate["reason"] = "Sevdiğin/okuduğun kitapların yazarı: %s" % query
                results.append(candidate)
        if len(results) >= 18:
            break

    if not seeds:
        message = "Öneriler için bir kitabı Okundu olarak işaretle veya 4-5 yıldızla puanla."
    elif not results and not message:
        message = "Kitapyurdu bu kitaplara göre yeni bir öneri bulamadı."
    return render_template(
        "recommendations.html",
        results=results[:18],
        message=message,
        seed_count=len(seeds),
    )


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()
    results = []
    message = None
    if query:
        found, state = search_books(query)
        if state == "site-error":
            message = "Şu an kitap aranamıyor, elle ekleyebilirsin"
        elif not found:
            message = "Kitap bulunamadı, elle ekleyebilirsin"
        else:
            results = found
    return render_template("search.html", query=query, results=results, message=message)


@app.route("/add", methods=["POST"])
def add_book():
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    publisher = request.form.get("publisher", "").strip()
    status = request.form.get("status", "okunacak")
    if status not in {"okunacak", "okunuyor", "okundu"}:
        status = "okunacak"

    raw_pages = request.form.get("page_count", "").strip()
    try:
        page_count = int(raw_pages) if raw_pages else None
    except ValueError:
        page_count = None
    if not title:
        flash("Kitap adı zorunludur.", "danger")
        return redirect(request.referrer or url_for("search"))
    if page_count is not None and page_count <= 0:
        flash("Sayfa sayısı 0'dan büyük olmalıdır.", "danger")
        return redirect(request.referrer or url_for("search"))

    product_url = request.form.get("product_url", "").strip()
    isbn = request.form.get("isbn", "").strip()
    publication_year = request.form.get("publication_year", "").strip()

    conn = db.get_db()
    duplicate = conn.execute(
        "SELECT id FROM books WHERE (title = ? AND author = ?) OR (? != '' AND isbn = ?) LIMIT 1",
        (title, author, isbn, isbn),
    ).fetchone()
    if duplicate:
        conn.close()
        flash("Bu kitap zaten kitaplığında.", "warning")
        return redirect(url_for("library"))

    if product_url:
        details = get_book_details(product_url)
        page_count = page_count or details.get("page_count")
        isbn = isbn or details.get("isbn", "")
        publication_year = publication_year or details.get("publication_year", "")

    cover_filename = None
    cover_url = request.form.get("cover_url", "").strip()
    if cover_url:
        filename = "kitap-%s.jpg" % secrets.token_hex(8)
        if download_cover(cover_url, COVER_DIR / filename):
            cover_filename = filename

    finish_date = db.today_string() if status == "okundu" else None
    conn.execute(
        """
        INSERT INTO books
        (title, author, publisher, cover_filename, page_count, isbn, publication_year,
         product_url, status, finish_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (title, author, publisher, cover_filename, page_count, isbn, publication_year,
         product_url, status, finish_date, datetime.now(TZ).isoformat()),
    )
    conn.commit()
    conn.close()
    flash("Kitap rafta.", "success")
    return redirect(url_for("library", shelf=status))


@app.get("/books/<int:book_id>/covers")
def find_book_covers(book_id):
    conn = db.get_db()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    if not book:
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))

    query = request.args.get("q", "").strip() or " ".join(
        part for part in (book["title"], book["author"]) if part
    )
    results, state = search_books(query)
    message = (
        "Kitapyurdu'na şu an bağlanılamıyor."
        if state == "site-error"
        else "Uygun eşleşme bulunamadı." if not results else None
    )
    return render_template(
        "cover_matches.html",
        book=book,
        query=query,
        results=results or [],
        message=message,
    )


@app.post("/books/<int:book_id>/cover")
def set_book_cover(book_id):
    conn = db.get_db()
    book = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        conn.close()
        flash("Kitap bulunamadı.", "danger")
        return redirect(url_for("library"))
    cover_url = request.form.get("cover_url", "").strip()
    if not cover_url:
        conn.close()
        flash("Seçilen sonuçta kapak görseli bulunmuyor.", "warning")
        return redirect(url_for("find_book_covers", book_id=book_id))
    filename = "kitap-%s.jpg" % secrets.token_hex(8)
    if not download_cover(cover_url, COVER_DIR / filename):
        conn.close()
        flash("Kapak indirilemedi. Başka bir eşleşme deneyebilirsin.", "danger")
        return redirect(url_for("find_book_covers", book_id=book_id))
    conn.execute("UPDATE books SET cover_filename = ? WHERE id = ?", (filename, book_id))
    conn.commit()
    conn.close()
    flash("Kitap kapağı eşleştirildi.", "success")
    return redirect(request.referrer or url_for("library"))


@app.post("/books/<int:book_id>/status")
def change_status(book_id):
    status = request.form.get("status")
    if status not in {"okunacak", "okunuyor", "okundu"}:
        return redirect(url_for("library"))
    conn = db.get_db()
    finish_date = db.today_string() if status == "okundu" else None
    conn.execute("UPDATE books SET status = ?, finish_date = ? WHERE id = ?", (status, finish_date, book_id))
    conn.commit()
    conn.close()
    return redirect(url_for("library", shelf=status))


@app.post("/books/<int:book_id>/progress")
def add_progress(book_id):
    conn = db.get_db()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        conn.close()
        return redirect(url_for("library"))
    try:
        page = int(request.form.get("page", ""))
    except (TypeError, ValueError):
        conn.close()
        flash("Geçerli bir sayfa gir.", "danger")
        return redirect(url_for("library"))
    if page <= 0:
        conn.close()
        flash("Sayfa sayısı 0'dan büyük olmalıdır.", "danger")
        return redirect(url_for("library"))
    if book["page_count"] and page > book["page_count"]:
        conn.close()
        flash("Okunan sayfa toplam sayfayı aşamaz.", "danger")
        return redirect(url_for("library"))
    if page < book["current_page"]:
        conn.close()
        flash("Okunan sayfa önceki kayıttan küçük olamaz.", "danger")
        return redirect(url_for("library"))

    status = "okundu" if book["page_count"] and page == book["page_count"] else "okunuyor"
    finish_date = db.today_string() if status == "okundu" else None
    conn.execute(
        "UPDATE books SET current_page = ?, status = ?, finish_date = ? WHERE id = ?",
        (page, status, finish_date, book_id),
    )
    conn.execute(
        "INSERT INTO reading_logs(book_id, page, logged_at) VALUES (?, ?, ?)",
        (book_id, page, datetime.now(TZ).isoformat()),
    )
    conn.commit()
    conn.close()
    flash("Okuma kaydı ekledi.", "success")
    return redirect(url_for("library", shelf=status))


@app.post("/logs/<int:log_id>/delete")
def delete_log(log_id):
    conn = db.get_db()
    log = conn.execute("SELECT * FROM reading_logs WHERE id = ?", (log_id,)).fetchone()
    if log:
        conn.execute("DELETE FROM reading_logs WHERE id = ?", (log_id,))
        remaining = conn.execute(
            "SELECT page FROM reading_logs WHERE book_id = ? ORDER BY logged_at DESC, id DESC LIMIT 1",
            (log["book_id"],),
        ).fetchone()
        current_page = remaining["page"] if remaining else 0
        book = conn.execute("SELECT page_count FROM books WHERE id = ?", (log["book_id"],)).fetchone()
        status = "okundu" if book["page_count"] and current_page == book["page_count"] else (
            "okunuyor" if current_page > 0 else "okunacak"
        )
        conn.execute(
            "UPDATE books SET current_page = ?, status = ?, finish_date = NULL WHERE id = ?",
            (current_page, status, log["book_id"]),
        )
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("library"))


@app.post("/books/<int:book_id>/details")
def update_details(book_id):
    try:
        rating = int(request.form.get("rating", "0") or 0)
    except ValueError:
        rating = 0
    rating = max(0, min(5, rating))
    conn = db.get_db()
    conn.execute(
        "UPDATE books SET rating = ?, note = ? WHERE id = ?",
        (rating, request.form.get("note", "").strip(), book_id),
    )
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for("library"))


@app.route("/stats")
def stats():
    conn = db.get_db()
    year = datetime.now(TZ).year
    finished = conn.execute(
        "SELECT * FROM books WHERE status = 'okundu' AND substr(finish_date, 1, 4) = ?",
        (str(year),),
    ).fetchall()
    target = int(db.get_setting("annual_target", "24") or 24)
    monthly = [0] * 12
    for book in finished:
        try:
            monthly[int(book["finish_date"][5:7]) - 1] += 1
        except (TypeError, ValueError, IndexError):
            pass
    reading_logs = conn.execute("SELECT logged_at, page FROM reading_logs ORDER BY logged_at").fetchall()
    conn.close()

    difference = len(finished) - target
    if difference >= 0:
        status_text = "Bu yıl %d/%d, hedefin %d kitap önündesin" % (len(finished), target, difference)
    else:
        status_text = "Bu yıl %d/%d, hedefin %d kitap gerisindesin" % (len(finished), target, abs(difference))
    return render_template(
        "stats.html",
        annual_target=target,
        finished_count=len(finished),
        status_text=status_text,
        monthly=monthly,
        streak=calculate_reading_streak(reading_logs),
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            target = int(request.form.get("annual_target", "24"))
            if target < 1:
                raise ValueError
            db.set_setting("annual_target", target)
            flash("Yıllık hedef kaydedildi.", "success")
        except ValueError:
            flash("Yıllık hedef en az 1 olmalıdır.", "danger")
    target = int(db.get_setting("annual_target", "24") or 24)
    return render_template("settings.html", annual_target=target)


@app.context_processor
def utility_processor():
    conn = db.get_db()
    currently_reading = conn.execute(
        "SELECT id, title, page_count, current_page FROM books WHERE status = 'okunuyor'"
    ).fetchall()
    estimates = {}
    for book in currently_reading:
        logs = conn.execute(
            "SELECT page, logged_at FROM reading_logs WHERE book_id = ? ORDER BY logged_at",
            (book["id"],),
        ).fetchall()
        estimates[book["id"]] = calculate_estimate_days(book["page_count"], book["current_page"], logs)
    conn.close()

    def cover_url(filename):
        if filename:
            return url_for("static", filename="kapaklar/" + filename)
        return url_for("static", filename="default-cover.svg")

    return {"book_estimates": estimates, "cover_url": cover_url}


def calculate_estimate_days(page_count, current_page, logs):
    if not page_count or current_page >= page_count or not logs:
        return None
    cutoff = datetime.now(TZ) - timedelta(days=7)
    recent = []
    for log in logs:
        try:
            logged_at = datetime.fromisoformat(log["logged_at"])
            if logged_at.tzinfo is None:
                logged_at = logged_at.replace(tzinfo=TZ)
            if logged_at >= cutoff:
                recent.append(log)
        except (TypeError, ValueError):
            continue
    if not recent:
        return None
    pages = [int(row["page"]) for row in recent]
    gained = max(0, max(pages) - min(pages))
    if gained <= 0:
        return None
    pace = gained / 7
    return max(1, int(round((page_count - current_page) / pace)))


def calculate_reading_streak(logs):
    dates = set()
    for log in logs:
        try:
            dates.add(datetime.fromisoformat(log["logged_at"]).date())
        except (TypeError, ValueError):
            continue
    if not dates:
        return 0
    current = datetime.now(TZ).date()
    streak = 0
    while current in dates:
        streak += 1
        current -= timedelta(days=1)
    return streak


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=True)
