# Backend'ni Supabase + Render ga joylash

> Bepul va uxlamaydigan variant — bitta serverda hammasi (Oracle Cloud Always Free): **../deploy/README.md**

1. Supabase: supabase.com → New project (parolni eslab qoling). Project Settings → Database → Connection string → **Session pooler** → URI nusxalang.
   Boshini `postgresql://` dan `postgresql+asyncpg://` ga almashtiring. Paroldagi maxsus belgilar URL-kodlanadi (@ → %40).
   (Direct connection ishlatmang: Render IPv6 ni qo'llamaydi, pooler IPv4 bilan ishlaydi.)
2. GitHub: shu papka mazmunini (backend/) yangi repoga yuklang (.env yuklanmaydi — .gitignore da).
3. Render: New → Blueprint (render.yaml avtomatik topiladi) yoki New → Web Service → Docker.
4. Environment: `ENVIRONMENT=production`, DATABASE_URL (1-qadam), CORS_ORIGINS (frontend manzili),
   FIRST_SUPERADMIN_PASSWORD (**kamida 10 belgi, harf + raqam**). SECRET_KEY va CRON_SECRET avtomatik yaratiladi.
   `ENVIRONMENT=production` bo'lganda SECRET_KEY qisqa/standart yoki superadmin paroli zaif bo'lsa server ishga tushmaydi
   (Render loglarida sababi yoziladi).
5. Deploy. Konteyner ishga tushganda `alembic upgrade head` jadvallarni yaratadi, RLS ni yoqadi va mavjud karta raqamlarini shifrlaydi.
6. Tekshiring: https://<nom>.onrender.com/health → {"status":"ok"}, /docs → Swagger.
7. Kirish: username `superadmin` + 4-qadamdagi parol. Tizim darhol yangi parol qo'yishni so'raydi.
8. Frontend `config.js`: API: 'https://<nom>.onrender.com/api/v1'. CORS_ORIGINS ga frontend manzilini yozing (oxirida / yo'q).

## Karta raqamlari shifrlangan — kalitni yo'qotmang
Kartalar `CARD_ENCRYPTION_KEY` (berilmagan bo'lsa `SECRET_KEY`) asosida shifrlanadi.
**Shu kalitni o'zgartirsangiz, saqlangan kartalarni o'qib bo'lmaydi** (foydalanuvchilar kartani qayta kiritishi kerak bo'ladi).
`CARD_ENCRYPTION_KEY` ni ishlatmoqchi bo'lsangiz, uni shu versiyani BIRINCHI deploy qilishdan OLDIN qo'shing va keyin o'zgartirmang.
Kalitni xavfsiz joyda (parollar menejerida) saqlab qo'ying.

## Render bepul tarifi uxlab qolmasligi uchun (muhim)
Bepul tarifda server 15 daqiqa so'rovsiz uxlaydi — shunda dushanba eslatmasi va Telegram xabarlari to'xtaydi.
1. Super admin → Sozlamalar → «Cron manzili» ni nusxalang (yoki `GET /api/v1/cron/info`).
2. cron-job.org da bepul hisob → Create cronjob → shu manzil → **har 10 daqiqada**.
Bu serverni uyg'oq ushlaydi va eslatma/xabarlarni yuboradi. Pullik tarifda ham zarar qilmaydi.

## Bir nechta server nusxasi
Telegram navbati va haftalik eslatma Postgres advisory lock bilan himoyalangan — bir xabar ikki marta ketmaydi.
Login urinishlari cheklovi xotirada saqlanadi (har nusxa o'z hisobini yuritadi).

## Shu versiyani Render'ga qo'yishdan oldin (bir marta)
Render → servis → Environment → qo'shing/tekshiring:
- `ENVIRONMENT` = `production`
- `FIRST_SUPERADMIN_PASSWORD` — kamida 10 belgi, harf va raqam (aks holda server ishga tushmaydi; loglarda sababi yoziladi)
- `SECRET_KEY` — o'zgartirmang (Render yaratgan uzun kalit qolsin). Bu deploy'da karta raqamlari shu kalit bilan shifrlanadi.
- `CRON_SECRET` — ixtiyoriy (bo'sh bo'lsa SECRET_KEY dan hosil qilinadi)
Deploy'dan keyin: super admin → Sozlamalar → «Cron manzili» → cron-job.org'da har 10 daqiqaga qo'ying.

## Zaxira nusxa (backup) — GitHub Actions orqali, bepul
`.github/workflows/backup.yml` har kuni 03:00 (Toshkent) bazaning shifrlangan nusxasini oladi:
GitHub'da 14 kun saqlanadi (Actions → «Kunlik zaxira nusxa» → Artifacts) va super admin Telegramiga yuboriladi.
Sozlash: GitHub repo → Settings → Secrets and variables → Actions → New repository secret:
`DATABASE_URL` (Render'dagi bilan bir xil), `BACKUP_PASSWORD` (o'zingiz o'ylab toping va yozib qo'ying), `TELEGRAM_BOT_TOKEN` (ixtiyoriy).
Sinash: Actions → «Kunlik zaxira nusxa» → Run workflow.

Nusxadan Supabase'ga tiklash (kompyuterda, Docker bilan):
```
openssl enc -d -aes-256-cbc -pbkdf2 -in tur_YYYYMMDD_HHMM.dump.enc -out tur.dump      # BACKUP_PASSWORD so'raladi
docker run --rm -i postgres:17-alpine pg_restore --clean --if-exists --no-owner --no-privileges -d "SUPABASE_URL?sslmode=require" < tur.dump
```

Qo'lda nusxa olish (Docker'siz, pg_dump o'rnatilgan bo'lsa):
  `pg_dump "postgresql://postgres.PROJECT_REF:PAROL@aws-0-REGION.pooler.supabase.com:5432/postgres" -Fc -f tur_YYYYMMDD.dump`
- Tiklash: `pg_restore -d "<yangi baza URI>" --clean tur_YYYYMMDD.dump`
- Dump faylida karta raqamlari shifrlangan holda bo'ladi; tiklangandan keyin ham o'sha CARD_ENCRYPTION_KEY/SECRET_KEY kerak.

## Xatolarni kuzatish (ixtiyoriy)
sentry.io da bepul loyiha oching → DSN ni `SENTRY_DSN` ga yozing. Kutilmagan xatolar loglarga ham yoziladi (Render → Logs).

## Testlar
```
pip install -r requirements.txt pytest pytest-asyncio
pytest                       # SQLite'da
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/test pytest   # Postgres'da
```

## Telegram bildirishnomalari (ixtiyoriy)
1. Telegramda @BotFather → /newbot → bot nomi va username (oxiri `bot` bilan) → **token** beriladi.
2. Render → Environment: `TELEGRAM_BOT_TOKEN` = token, `FRONTEND_URL` = https://travel-operator.uz → Save (servis qayta ishga tushadi). Webhook manzili Render'ning `RENDER_EXTERNAL_URL` dan o'zi olinadi.
3. Super admin: Sozlamalar sahifasida «Telegram bot» kartasida ✅ chiqishi kerak.
4. Foydalanuvchilar: «Telegramni ulash» → botda Start.
