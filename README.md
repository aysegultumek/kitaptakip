# Kitap Takip

Kitap Okuma Takibi, Kitapyurdu araması ve SQLite kayıtlarıyla çalışır.

Kitap arama sonuçlarından kapaklar indirilir. Kitaplık kartındaki kapak bağlantısıyla Kitapyurdu sonuçlarından farklı bir kapak seçilebilir. Öneriler sekmesi, okundu olarak işaretlenen veya en az 4 yıldız verilen kitapların yazarlarına göre Kitapyurdu'nda arama yapar.

## Kurulum

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python application.py
```

Uygulama: http://localhost:5010

Giriş: `test` / `123`

## Docker

```bash
docker compose up -d --build
```

Uygulama: http://localhost:5010