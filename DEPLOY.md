# Backend'ni Supabase + Render ga joylash

1. Supabase: supabase.com → New project (parolni eslab qoling). Project Settings → Database → Connection string → **Session pooler** → URI nusxalang.
   Boshini `postgresql://` dan `postgresql+asyncpg://` ga almashtiring. Paroldagi maxsus belgilar URL-kodlanadi (@ → %40).
   (Direct connection ishlatmang: Render IPv6 ni qo'llamaydi, pooler IPv4 bilan ishlaydi.)
2. GitHub: shu papka mazmunini (backend/) yangi repoga yuklang (.env yuklanmaydi — .gitignore da).
3. Render: New → Blueprint (render.yaml avtomatik topiladi) yoki New → Web Service → Docker.
4. Environment: DATABASE_URL (1-qadam), CORS_ORIGINS (frontend manzili), FIRST_SUPERADMIN_PASSWORD (kuchli parol). SECRET_KEY avtomatik yaratiladi.
5. Deploy. Konteyner ishga tushganda `alembic upgrade head` jadvallarni Supabase'da yaratadi va RLS ni yoqadi.
6. Tekshiring: https://<nom>.onrender.com/health → {"status":"ok"}, /docs → Swagger.
7. Kirish: username `superadmin` + 4-qadamdagi parol. Darhol yangi parol o'rnating.
8. Frontend `config.js`: API: 'https://<nom>.onrender.com/api/v1'. CORS_ORIGINS ga frontend manzilini yozing (oxirida / yo'q).
