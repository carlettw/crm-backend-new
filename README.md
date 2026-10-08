# Turistik firma boshqaruv paneli — backend (FastAPI)

Ishga tushirish: `cp .env.example .env` → `docker compose up --build` → http://localhost:8000/docs
(Docker konteyner avval `alembic upgrade head` ni ishga tushiradi.) Dev uchun: `AUTO_CREATE_TABLES=true`.

## Rollar
super_admin · boss (boshliq) · admin · guide (gid) · driver (haydovchi). Login: telefon + parol.
Admin boshliq ishlariga `?boss_id=` bilan kiradi (`GET /me/bosses` ro'yxatidan tanlaydi).

## Asosiy biznes qoidalar
- Tur oqimi: draft (saqlangan shablon) → `clone` (ishdan 1 kun oldin, xohlasa o'zgartirib) → `publish` (min. daraja) → open → ready (gid+haydovchi bor) → completed / cancelled.
- Minimal summa: admin tanlagan daraja uchun amaldagi eng kam summadan kam taklif yubora olmaydi. Amaldagi summa = o'zi va undan pastki (3+) darajalar summalarining eng kattasi (4-darajaga 300 000 bo'lsa, summasi belgilanmagan 5-daraja uchun ham 300 000). 1–2 daraja bepul, pol yo'q. `GET /level-rates` har daraja uchun `amount` va `effective` ni qaytaradi.
- Valyuta: tur narxi so'mda yoki dollarda kiritiladi (`price_currency`: UZS|USD); gid/haydovchi haqlari, jarimalar, daraja summalari faqat so'mda. Super admin kursni `PUT /currency/rate` bilan istalgan vaqtda kiritadi (tarix: `/currency/rate/history`). Dollarli tur narxi kiritilganda joriy kurs bilan hisoblanadi, yakunlanganda esa yakuniy kurs bilan qayta hisoblanadi.
- Gid: birinchi rozi bo'lgan avtomatik tayinlanadi (atomar UPDATE). Haydovchi: ariza → admin tasdiqlaydi. 1-daraja: amaliyot arizasi → admin tasdiqlaydi.
- Daraja: 1→2 (amaliyot tur + suhbat), 2→3 (5 tekin tur), 3→4 (15 tur), 4+ qo'lda (super admin).
- Bekor qilish: boshlanishiga >=24 soat bo'lsa gid/haydovchi o'zi bekor qiladi (`POST /jobs/tours/{id}/cancel`); <24 soat bo'lsa 400 va admin kontakti qaytadi — admin `cancel-worker` bilan bekor qiladi. Admin `redispatch` (qayta yuborish) yoki `assign` (aniq odamni, jumladan avval bekor qilganni, qaytarish) qila oladi.
- Yakun: gid va haydovchi ikkalasi `complete` bossa → hisob-kitob, haqlar (Earning), daraja hisobi. Kechikish xabari bo'lsa admin uchun `fine_prompt=true`.
- Admin haqi: har tur uchun `admin_fee_usd` ($2, `PUT /settings/admin_fee_usd`) × amaldagi dollar kursi.
- Haftalik to'lov: boshliq `GET /boss/payouts/due` → `POST /boss/payouts/pay` → oluvchi `POST /payments/{id}/confirm`.
- Super admin faqat `GET /super/share` (o'z ulushi) ni ko'radi; admin aylanmani ko'rmaydi.
- Vaqt: kiritishda tz-siz bo'lsa Toshkent vaqti deb olinadi, bazada UTC.
"# crm-backend-new" 
