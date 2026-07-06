# Backend Docker kullanımı

`.env` dosyasında en azından `SECRET_KEY`, `DATABASE_URL` ve yapay zeka için `GROQ_API_KEY` tanımlanmalıdır. `.env` imaja kopyalanmaz.

```powershell
docker compose up --build
```

API `http://localhost:8000/api/` adresinde çalışır. Container açılırken migration ve `collectstatic` otomatik uygulanır. `DATABASE_URL` verilmezse yerel Docker kullanımı için kalıcı SQLite volume'u kullanılır.

Tek başına imaj oluşturmak için:

```powershell
docker build -t e-teacher-backend .
docker run --rm -p 8000:8000 --env-file .env e-teacher-backend
```
