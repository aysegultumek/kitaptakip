from datetime import datetime, timedelta

import pytest

import application
import db
from application import app, calculate_estimate_days


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db(tmp_path / "test.db")
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        test_client.post("/login", data={"username": "test", "password": "123"})
        yield test_client


def add_book(client, title="Suç ve Ceza", author="Fyodor Dostoyevski", pages="671"):
    return client.post(
        "/add",
        data={"title": title, "author": author, "page_count": pages, "status": "okunuyor"},
        follow_redirects=True,
    )


def test_login_required_and_login():
    app.config.update(TESTING=True)
    test_client = app.test_client()
    assert test_client.get("/").status_code == 302
    response = test_client.post("/login", data={"username": "test", "password": "123"})
    assert response.status_code == 302


def test_page_rules_finish_and_previous(client):
    add_book(client)
    conn = db.get_db()
    book = conn.execute("SELECT * FROM books LIMIT 1").fetchone()
    book_id = book["id"]
    conn.close()

    response = client.post(
        f"/books/{book_id}/progress",
        data={"page": "700"},
        follow_redirects=True,
    )
    assert "toplam sayfayı aşamaz" in response.get_data(as_text=True)

    client.post(f"/books/{book_id}/progress", data={"page": "100"}, follow_redirects=True)
    response = client.post(
        f"/books/{book_id}/progress",
        data={"page": "50"},
        follow_redirects=True,
    )
    assert "önceki kayıttan küçük olamaz" in response.get_data(as_text=True)

    client.post(f"/books/{book_id}/progress", data={"page": "671"}, follow_redirects=True)
    conn = db.get_db()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    assert book["status"] == "okundu"
    assert book["finish_date"] is not None
    conn.close()


def test_duplicate_book_is_blocked(client):
    add_book(client)
    response = add_book(client)
    assert "Bu kitap zaten" in response.get_data(as_text=True)


def test_estimate_uses_seven_day_pace():
    now = datetime.now()
    logs = [
        {"page": 20, "logged_at": (now - timedelta(days=6)).isoformat()},
        {"page": 90, "logged_at": now.isoformat()},
    ]
    assert calculate_estimate_days(300, 90, logs) == 21


def test_annual_target_setting(client):
    response = client.post("/settings", data={"annual_target": "30"}, follow_redirects=True)
    assert "Yıllık hedef kaydedildi" in response.get_data(as_text=True)
    assert db.get_setting("annual_target") == "30"


def test_recommendations_use_read_books_and_exclude_library(client, monkeypatch):
    add_book(client)
    conn = db.get_db()
    conn.execute(
        "UPDATE books SET status = 'okundu', rating = 5, finish_date = ?",
        (db.today_string(),),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        application,
        "search_books",
        lambda query: (
            [
                {"title": "Suç ve Ceza", "author": "Fyodor Dostoyevski", "publisher": "", "cover_url": "", "url": ""},
                {"title": "Budala", "author": "Fyodor Dostoyevski", "publisher": "", "cover_url": "", "url": ""},
            ],
            "ok",
        ),
    )

    response = client.get("/recommendations")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Budala" in page
    assert "Sevdiğin/okuduğun kitapların yazarı" in page
    assert page.count("Suç ve Ceza") == 0


def test_cover_match_updates_book_cover(client, monkeypatch, tmp_path):
    add_book(client)
    conn = db.get_db()
    book_id = conn.execute("SELECT id FROM books").fetchone()["id"]
    conn.close()
    monkeypatch.setattr(application, "COVER_DIR", tmp_path / "covers")
    monkeypatch.setattr(
        application,
        "search_books",
        lambda query: (
            [{"title": "Suç ve Ceza", "author": "Fyodor Dostoyevski", "publisher": "", "cover_url": "https://img.kitapyurdu.com/cover.jpg", "url": ""}],
            "ok",
        ),
    )

    def fake_download(url, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"image")
        return True

    monkeypatch.setattr(application, "download_cover", fake_download)
    response = client.get(f"/books/{book_id}/covers")
    assert "Bu kapağı eşleştir" in response.get_data(as_text=True)

    client.post(
        f"/books/{book_id}/cover",
        data={"cover_url": "https://img.kitapyurdu.com/cover.jpg"},
        follow_redirects=True,
    )
    conn = db.get_db()
    cover_filename = conn.execute(
        "SELECT cover_filename FROM books WHERE id = ?", (book_id,)
    ).fetchone()["cover_filename"]
    conn.close()
    assert cover_filename
    assert (application.COVER_DIR / cover_filename).is_file()


def test_cover_download_rejects_non_kitapyurdu_domain(monkeypatch, tmp_path):
    import scraper

    def unexpected_request(*args, **kwargs):
        pytest.fail("A non-Kitapyurdu URL must not be fetched")

    monkeypatch.setattr(scraper.requests, "get", unexpected_request)
    assert not scraper.download_cover("https://example.com/image.jpg", tmp_path / "cover.jpg")
