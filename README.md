# Library Management System (FastAPI + Tailwind CSS)

FastAPI asosida yozilgan kutubxona boshqaruv paneli. Frontend server-rendered (`Jinja2`) bo'lib, dizayn `Tailwind CSS v4` bilan ishlaydi.

## Tizim haqida (qisqacha)

- Session asosidagi login/logout tizimi (`starlette` session middleware).
- Asosiy bo'limlar:
  - Foydalanuvchilar (`/users`)
  - Kutubxonalar (`/libraries`)
  - Kitob turlari + BBK (`/book_types`)
  - Mualliflar (`/authors`)
  - Nashriyotlar + shahar/yil (`/publishers`)
  - Kitoblar va nusxalar (`/books`)
- Ma'lumotlar bazasi: `SQLite` (`sql_app.db`).
- Statik fayllar: `app/static`.

## Texnologiyalar

- Python 3.13+
- FastAPI, SQLAlchemy, Jinja2
- Tailwind CSS v4 (`@tailwindcss/cli`)
- Node.js LTS (npm bilan)

## Loyiha tuzilmasi

```text
app/
  api/
  core/
  models/
  static/
    css/
      input.css       # Tailwind kirish fayli
      tailwind.css    # Build natijasi (template shu faylni yuklaydi)
  templates/
sql_app.db
requirements.txt
tailwind.config.js
package.json
```

## 1) O'rnatish (bir martalik)

### 1.1 Node.js (agar o'rnatilmagan bo'lsa)

```powershell
winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
```

Terminalni yopib qayta oching (PATH yangilanishi uchun).

### 1.2 Python virtual environment + dependency

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 1.3 Tailwind dependency

```powershell
npm install
npm run tw:build
```

## 2) Loyihani ishga tushirish

### Variant A (tavsiya): API + Tailwind watch birga

```powershell
.\.venv\Scripts\Activate.ps1
npm run dev
```

Bu buyruq:
- API serverni `0.0.0.0:8000` da ishga tushiradi
- Tailwind watch rejimida `input.css` o'zgarishlarini avtomatik `tailwind.css` ga build qiladi

### Variant B: alohida terminallarda

1. Terminal 1:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

2. Terminal 2:

```powershell
npm run tw:watch
```

## 3) Kirish (joriy DB bilan)

Joriy `sql_app.db` faylida mavjud login:

- Username: `admin`
- Password: `admin1231`

## 4) URL lar

- Asosiy sahifa: `http://127.0.0.1:8000`
- Tarmoqdan kirish: `http://<sizning-ip>:8000`
- OpenAPI JSON: `http://127.0.0.1:8000/api/v1/openapi.json`
- Swagger UI: `http://127.0.0.1:8000/docs`

## 5) Tailwind workflow (to'liq)

- Kirish fayli: `app/static/css/input.css`
- Config: `tailwind.config.js`
- Chiqish fayli: `app/static/css/tailwind.css`

Muhim:
- Template lar `tailwind.css` ni yuklaydi, `input.css` ni emas.
- Yangi class qo'shsangiz `tw:watch` ishlab turishi kerak.
- Agar style yangilanmasa:
  - `npm run tw:build` ni qayta ishga tushiring
  - Browserda hard refresh qiling (`Ctrl + F5`)

## 6) Production uchun tayyorlash

1. `.env` fayl yarating:

```powershell
copy .env.example .env
```

2. `.env` ichida albatta quyidagilarni o'zgartiring:
- `APP_SESSION_SECRET_KEY` (uzun maxfiy kalit)
- `APP_TRUSTED_HOSTS` (real domenlar)
- `APP_ENABLE_DOCS=false`
- `APP_SESSION_HTTPS_ONLY=true` (SSL ishlaganda)
- `APP_WORKERS=1` (agar SQLite ishlatayotgan bo'lsangiz tavsiya etiladi)

3. Tailwind production build:

```powershell
npm run tw:build
```

4. Windows serverda production run:

```powershell
npm run start:prod:win
```

5. Linux serverda production run:

```bash
chmod +x scripts/start_prod.sh
./scripts/start_prod.sh
```

## 7) Linux deployment (Nginx + systemd)

1. Loyihani masalan `/opt/library` ga joylashtiring.
2. Venv va dependency o'rnating:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install
npm run tw:build
cp .env.example .env
```

3. `deploy/library.service.example` ni `/etc/systemd/system/library.service` ga nusxalang va yo'llarni moslang.
4. `deploy/nginx.library.conf.example` ni `/etc/nginx/sites-available/library.conf` ga nusxalang, domenni o'zgartiring.
5. Xizmatlarni ishga tushiring:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now library
sudo ln -s /etc/nginx/sites-available/library.conf /etc/nginx/sites-enabled/library.conf
sudo nginx -t
sudo systemctl reload nginx
```

6. Healthcheck:
- `GET /health`
- `GET /healthz`

## 8) Tez-tez uchraydigan muammolar

### `node` yoki `npm` topilmadi

- Node o'rnatilgandan keyin terminalni qayta oching.
- Tekshiruv:

```powershell
node -v
npm -v
```

### `8000` port band

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

Kerak bo'lsa jarayonni to'xtating:

```powershell
Stop-Process -Id <PID> -Force
```

### `ModuleNotFoundError`

- Virtual environment aktiv ekanini tekshiring.
- Qayta o'rnating:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
