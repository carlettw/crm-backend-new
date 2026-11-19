from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update

from app.db.session import SessionLocal
from app.models import Earning, Message, Tour
from tests.conftest import PW, Api, login

TZ5 = timezone(timedelta(hours=5))


async def _setup(c):
    sa = await login(c, "superadmin")

    async def mk(**kw):
        return await sa.post("/users", {"password": PW, "phone": "901234567", **kw}, expect=201)

    boss = await mk(role="boss", username="boss1", full_name="Boshliq Bir", boss_percent=10)
    admin = await mk(role="admin", username="admin1", full_name="Admin Bir")
    g1 = await mk(role="guide", username="gid1", full_name="Gid Bir", guide_level=3, languages=["en"], regions=["samarkand"])
    g2 = await mk(role="guide", username="gid2", full_name="Gid Ikki", guide_level=3, languages=["en"], regions=["samarkand"])
    drv = await mk(role="driver", username="drv1", full_name="Haydovchi Bir", car_model="Cobalt")
    await sa.put("/level-rates/3", {"amount": 200000})
    b = await login(c, "boss1")
    await b.post("/boss/admins", {"admin_id": admin["id"]}, expect=201)
    a = await login(c, "admin1")
    return dict(sa=sa, b=b, a=a, boss=boss, admin=admin, g1=g1, g2=g2, drv=drv)


def _tour(start: datetime, title="Samarqand city tour", **kw):
    return {"title": title, "start_at": start.isoformat(), "groups": [{"language": "en", "tourist_name": "John", "pax_count": 2}],
            "total_price": 1000000, "guide_amount": 250000, "driver_amount": 150000, "platform_percent": 10, **kw}


async def _publish(a: Api, boss_id, start, **kw):
    t = await a.post(f"/tours?boss_id={boss_id}", _tour(start, **kw), expect=201)
    await a.post(f"/tours/{t['id']}/publish?boss_id={boss_id}", {"min_guide_level": 3, "region": "samarkand"})
    return t


async def _move_start(tour_id, dt):
    async with SessionLocal() as db:
        await db.execute(update(Tour).where(Tour.id == tour_id).values(start_at=dt))
        await db.commit()


async def test_login_lockout_and_password_flow(client):
    for _ in range(5):
        r = await client.post("/auth/login", json={"username": "superadmin", "password": "wrong"})
        assert r.status_code == 401
    r = await client.post("/auth/login", json={"username": "superadmin", "password": PW})
    assert r.status_code == 429


async def test_must_change_and_token_revocation(client):
    env = await _setup(client)
    r = await client.post("/auth/login", json={"username": "gid1", "password": PW})
    assert r.json()["must_change_password"] is True
    old = Api(client, r.json()["access_token"])
    me = await old.get("/users/me")
    assert me["must_change_password"] is True
    new = await old.post("/auth/change-password", {"old_password": PW, "new_password": "Yangi12345"})
    await old.get("/users/me", expect=401)            # eski token bekor
    fresh = Api(client, new["access_token"])
    assert (await fresh.get("/users/me"))["must_change_password"] is False
    # super admin parolni tiklasa — sessiya tugaydi
    await env["sa"].post(f"/users/{env['g1']['id']}/reset-password", {"new_password": "Tiklandi123"}, expect=204)
    await fresh.get("/users/me", expect=401)
    # zaif parol
    await env["sa"].post("/users", {"role": "admin", "username": "weak", "full_name": "Weak", "phone": "901112233",
                                    "password": "12345678"}, expect=422)


async def test_card_is_encrypted(client):
    await _setup(client)
    g = await login(client, "gid1")
    out = await g.put("/me/card", {"number": "8600 0000 0000 0007"})
    assert out["masked"] == "8600 **** **** 0007"
    async with SessionLocal() as db:
        raw = (await db.execute(text("SELECT card_number FROM users WHERE username='gid1'"))).scalar_one()
    assert raw and not raw.isdigit() and "8600" not in raw


async def test_full_tour_flow(client):
    env = await _setup(client)
    a, bid = env["a"], env["boss"]["id"]
    start = datetime.now(timezone.utc) + timedelta(days=3)
    t = await _publish(a, bid, start)
    g1, g2, d = await login(client, "gid1"), await login(client, "gid2"), await login(client, "drv1")

    await g1.post(f"/jobs/tours/{t['id']}/guide/accept")
    await g2.post(f"/jobs/tours/{t['id']}/guide/accept", expect=409)  # boshqa gid oldi

    # ikkinchi tur 1 soatdan keyin — gid1 band
    t2 = await _publish(a, bid, start + timedelta(hours=1), title="Registon")
    r = await g1.post(f"/jobs/tours/{t2['id']}/guide/accept", expect=409)
    assert "band" in r["detail"]
    # admin ham band gidni tayinlay olmaydi
    await a.post(f"/tours/{t2['id']}/assign?boss_id={bid}", {"role": "guide", "user_id": env["g1"]["id"]}, expect=409)

    await d.post(f"/jobs/tours/{t['id']}/driver/apply", expect=201)
    await a.post(f"/tours/{t['id']}/driver/approve?boss_id={bid}", {"user_id": env["drv"]["id"]})

    # vaqtni o'zgartirish — ishtirokchilarga Toshkent vaqtida xabar boradi
    new_start = (start + timedelta(hours=2)).astimezone(TZ5)
    await a.patch(f"/tours/{t['id']}?boss_id={bid}", {"start_at": new_start.isoformat()})
    async with SessionLocal() as db:
        msgs = (await db.execute(select(Message.body).where(Message.recipient_id == env["g1"]["id"]))).scalars().all()
    assert any(new_start.strftime("%d.%m.%Y %H:%M") in m for m in msgs), msgs

    # boshlanmagan turni yakunlab bo'lmaydi
    await a.post(f"/tours/{t['id']}/complete?boss_id={bid}", expect=400)
    await _move_start(t["id"], datetime.now(timezone.utc) - timedelta(hours=1))
    await g1.post(f"/jobs/tours/{t['id']}/complete")
    done = await a.post(f"/tours/{t['id']}/complete?boss_id={bid}")
    assert done["status"] == "completed"
    async with SessionLocal() as db:
        kinds = sorted(e.kind.value for e in (await db.execute(select(Earning).where(Earning.tour_id == t["id"]))).scalars())
    assert kinds == ["admin", "driver", "guide"]

    # jarima: haqdan oshmaydi
    await a.post(f"/tours/{t['id']}/fines?boss_id={bid}", {"user_id": env["g1"]["id"], "amount": 300000}, expect=400)
    await a.post(f"/tours/{t['id']}/fines?boss_id={bid}", {"user_id": env["g1"]["id"], "amount": 50000}, expect=201)

    # to'lov
    b = env["b"]
    due = await b.get("/boss/payouts/due?all=true")
    gi = next(i for i in due["items"] if i["user_id"] == env["g1"]["id"])
    assert gi["net"] == 200000
    p = await b.post("/boss/payouts/pay", {"user_id": env["g1"]["id"], "all": True}, expect=201)
    await b.post("/boss/payouts/pay", {"user_id": env["g1"]["id"], "all": True}, expect=404)  # ikkinchi marta yo'q
    await g1.post(f"/payments/{p['payment_id']}/dispute", {"reason": "kelmadi"})
    await b.post(f"/boss/payouts/{p['payment_id']}/resend")
    await g1.post(f"/payments/{p['payment_id']}/confirm")


async def test_admin_cannot_farm_fee_on_empty_tour(client):
    env = await _setup(client)
    a, bid = env["a"], env["boss"]["id"]
    t = await _publish(a, bid, datetime.now(timezone.utc) + timedelta(days=1))
    await _move_start(t["id"], datetime.now(timezone.utc) - timedelta(hours=1))
    await a.post(f"/tours/{t['id']}/complete?boss_id={bid}")
    async with SessionLocal() as db:
        assert (await db.execute(select(Earning).where(Earning.tour_id == t["id"]))).first() is None


async def test_cancel_and_deactivate(client):
    env = await _setup(client)
    a, bid = env["a"], env["boss"]["id"]
    start = datetime.now(timezone.utc) + timedelta(days=2)
    t = await _publish(a, bid, start)
    g1 = await login(client, "gid1")
    await g1.post(f"/jobs/tours/{t['id']}/guide/accept")
    # faolsizlantirish: sessiya tugaydi va turdan chiqariladi
    await env["sa"].patch(f"/users/{env['g1']['id']}/active", {"is_active": False})
    await g1.get("/users/me", expect=401)
    tour = await a.get(f"/tours/{t['id']}?boss_id={bid}")
    assert tour["guide_id"] is None and tour["status"] == "open"
    d = await login(client, "drv1")
    await d.post(f"/jobs/tours/{t['id']}/driver/apply", expect=201)
    await a.post(f"/tours/{t['id']}/cancel?boss_id={bid}", {"reason": "ob-havo"})
    apps = await a.get(f"/tours/{t['id']}/applications?boss_id={bid}")
    assert apps[0]["status"] == "rejected"
    local = start.astimezone(TZ5).strftime("%d.%m.%Y %H:%M")
    async with SessionLocal() as db:
        body = (await db.execute(select(Message.body).where(Message.recipient_id == env["drv"]["id"])
                                 .order_by(Message.id.desc()))).scalars().first()
    assert local in body


async def test_cron_requires_key(client):
    r = await client.get("/cron/tick?key=wrong")
    assert r.status_code == 403
    from app.api.v1.cron import cron_key
    r = await client.get(f"/cron/tick?key={cron_key()}")
    assert r.status_code == 200 and r.json()["ok"]


def test_production_settings_check():
    from app.core.config import Settings
    s = Settings(environment="production", secret_key="change-me", auto_create_tables=False)
    try:
        s.check_production()
    except RuntimeError as e:
        assert "SECRET_KEY" in str(e)
    else:
        raise AssertionError("xavfli sozlama o'tib ketdi")
