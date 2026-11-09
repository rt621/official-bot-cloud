# -*- coding: utf-8 -*-
"""运营后台 API 集成测试：跑完自动清理测试数据。"""
import sqlite3
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
B = "http://127.0.0.1:8000"
results = []


def check(name, cond, extra=""):
    results.append((name, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)[:120]) if (extra and not cond) else ""))


c = httpx.Client(base_url=B, timeout=20)

# ---- Phase 1: 注册测试管理员 + 普通用户 ----
r = c.post("/api/auth/register", json={"username": "adm_test01", "password": "admtest12345"})
check("P1 注册 adm_test01", r.status_code == 200, r.text)
con = sqlite3.connect("data/app.db")
con.execute("UPDATE users SET is_admin=1 WHERE username='adm_test01'")
con.commit()
r = c.post("/api/auth/login", json={"username": "adm_test01", "password": "admtest12345"})
check("P1 登录 adm_test01", r.status_code == 200, r.text)
ca = httpx.Client(base_url=B, headers={"Authorization": "Bearer " + r.json()["token"]}, timeout=20)
r = ca.get("/api/auth/me")
check("P1 me.is_admin=True", r.json().get("is_admin") is True, r.text)

r = c.post("/api/auth/register", json={"username": "test_user_b", "password": "bbbb12345"})
check("P1 注册 test_user_b", r.status_code == 200, r.text)
b_tok = r.json()["token"]
cb = httpx.Client(base_url=B, headers={"Authorization": "Bearer " + b_tok}, timeout=20)

# ---- Phase 2: 非管理员访问后台 403 ----
r = cb.get("/api/admin/users")
check("P2 非管理员访问 /admin/users → 403", r.status_code == 403, r.status_code)

# ---- Phase 3: A1/B1/C1/C3/D1/D2 列表 ----
r = ca.get("/api/admin/users", params={"q": "yys"})
check("A1 用户列表含 yys", r.status_code == 200 and any(u["username"] == "yys" for u in r.json()["items"]), r.text[:200])
r = ca.get("/api/admin/users", params={"q": "test_user_b"})
check("A1 搜索 test_user_b 命中", len(r.json()["items"]) == 1)
r = ca.get("/api/admin/instances")
insts = r.json()["items"]
check("B1 实例总览含实例1", any(i["id"] == 1 and i["username"] == "yys" for i in insts), r.text[:200])
r = ca.get("/api/admin/stats/overview")
ov = r.json()
check("C1 概览统计", r.status_code == 200 and ov["users_total"] >= 3 and ov["instances_total"] >= 1, r.text[:200])
r = ca.get("/api/admin/stats/ranking", params={"days": 7})
check("C3 排行榜", r.status_code == 200 and isinstance(r.json()["items"], list), r.text[:200])
r = ca.get("/api/admin/audit-logs")
check("D1 审计日志", r.status_code == 200 and r.json()["total"] > 0, r.text[:150])
r = ca.get("/api/admin/runtime-logs", params={"level": "error"})
check("D2 运行日志(error过滤)", r.status_code == 200, r.text[:150])

# ---- Phase 4: A2 停用/启用 ----
bid = [u for u in ca.get("/api/admin/users").json()["items"] if u["username"] == "test_user_b"][0]["id"]
r = ca.post(f"/api/admin/users/{bid}/disable")
check("A2 停用用户", r.status_code == 200, r.text)
r = c.post("/api/auth/login", json={"username": "test_user_b", "password": "bbbb12345"})
check("A2 被停用用户登录 → 403", r.status_code == 403, r.status_code)
r = cb.get("/api/instances")
check("A2 在用 token 被拒 → 403", r.status_code == 403, r.status_code)
r = ca.post(f"/api/admin/users/{bid}/enable")
check("A2 启用用户", r.status_code == 200, r.text)
r = c.post("/api/auth/login", json={"username": "test_user_b", "password": "bbbb12345"})
check("A2 启用后可登录", r.status_code == 200, r.text)

# ---- Phase 5: A3/A4/A6 ----
r = ca.post(f"/api/admin/users/{bid}/reset-password")
newpwd = r.json().get("new_password", "")
check("A3 重置密码返回新密码", r.status_code == 200 and len(newpwd) == 10, r.text[:150])
r = c.post("/api/auth/login", json={"username": "test_user_b", "password": newpwd})
check("A3 新密码可登录", r.status_code == 200, r.text[:100])
r = ca.post(f"/api/admin/users/{bid}/set-admin", json={"is_admin": True})
check("A4 设管理员", r.status_code == 200 and r.json()["is_admin"] is True, r.text)
r = ca.post(f"/api/admin/users/{bid}/set-admin", json={"is_admin": False})
check("A4 撤管理员", r.status_code == 200 and r.json()["is_admin"] is False, r.text)
r = ca.post(f"/api/admin/users/{ca.get('/api/auth/me').json()['id']}/set-admin", json={"is_admin": False})
check("A4 不能改自己", r.status_code == 400, r.status_code)
r = ca.get(f"/api/admin/users/{bid}/logins")
check("A6 登录记录", r.status_code == 200 and r.json()["total"] >= 2, r.text[:150])

# ---- Phase 6: E3 邀请码 + D3 注册模式 ----
r = ca.put("/api/admin/settings", json={"registration_mode": "invite"})
check("D3 注册模式→invite", r.status_code == 200 and r.json()["registration_mode"] == "invite", r.text[:150])
r = c.post("/api/auth/register", json={"username": "test_user_c", "password": "cccc12345"})
check("E3 无邀请码注册 → 400", r.status_code == 400, r.status_code)
r = ca.post("/api/admin/invites", json={"count": 2})
codes = r.json()["items"]
check("E3 生成2个邀请码", r.status_code == 200 and len(codes) == 2, r.text[:150])
r = c.post("/api/auth/register", json={"username": "test_user_c", "password": "cccc12345", "invite_code": codes[0]})
check("E3 邀请码注册成功", r.status_code == 200, r.text[:150])
r = c.post("/api/auth/register", json={"username": "test_user_c2", "password": "cccc12345", "invite_code": codes[0]})
check("E3 同一邀请码复用 → 400", r.status_code == 400, r.status_code)
r = ca.get("/api/admin/invites")
inv = r.json()["items"]
check("E3 邀请码列表状态", sum(1 for i in inv if i["code"] == codes[0] and i["used"]) == 1 and sum(1 for i in inv if i["code"] == codes[1] and not i["used"]) == 1)
r = ca.put("/api/admin/settings", json={"registration_mode": "open"})
check("D3 注册模式还原 open", r.json()["registration_mode"] == "open")

# ---- Phase 7: E1 实例数上限 ----
r = ca.put("/api/admin/settings", json={"max_instances_per_user": 1})
check("E1 上限设置保存=1", r.json()["max_instances_per_user"] == 1, r.text[:150])
con.execute(
    "INSERT INTO bot_instances (user_id, appid, secret_enc, name, enabled, status, status_detail, created_at) "
    "VALUES ((SELECT id FROM users WHERE username='test_user_c'), 'FAKE9999', 'x', 'fake', 0, 'offline', '', CURRENT_TIMESTAMP)"
)
con.commit()
cc_tok = c.post("/api/auth/login", json={"username": "test_user_c", "password": "cccc12345"}).json()["token"]
cc = httpx.Client(base_url=B, headers={"Authorization": "Bearer " + cc_tok}, timeout=20)
r = cc.post("/api/instances", json={"appid": "1234567890", "app_secret": "garbage123"})
check("E1 超上限绑定 → 400", r.status_code == 400 and "最多绑定" in r.text, r.text[:150])

# ---- Phase 8: F1 公告 ----
r = ca.put("/api/admin/settings", json={"announcement": "测试公告：平台将于今晚升级。"})
check("F1 设置公告", r.status_code == 200, r.text[:150])
r = cc.get("/api/announcement")
check("F1 用户读取公告", r.json().get("content") == "测试公告：平台将于今晚升级。", r.text)
r = ca.put("/api/admin/settings", json={"announcement": ""})
check("F1 清空公告", r.json()["announcement"] == "", r.text[:100])

# ---- Phase 9: F2 维护模式 ----
r = ca.post("/api/admin/maintenance", json={"on": True})
check("F2 开启维护模式", r.status_code == 200 and r.json()["on"] is True, r.text)
ok_off = False
for _ in range(20):
    time.sleep(1)
    st = [i["status"] for i in ca.get("/api/admin/instances").json()["items"] if i["id"] == 1][0]
    if st != "online":
        ok_off = True
        break
check("F2 实例1 已停止运行", ok_off, f"status={st}")
r = ca.post("/api/admin/maintenance", json={"on": False})
check("F2 关闭维护模式", r.status_code == 200 and r.json()["on"] is False, r.text)
ok_on = False
st = "?"
for _ in range(30):
    time.sleep(1)
    st = [i["status"] for i in ca.get("/api/admin/instances").json()["items"] if i["id"] == 1][0]
    if st == "online":
        ok_on = True
        break
check("F2 实例1 恢复在线", ok_on, f"status={st}")

# ---- Phase 10: A5 删除用户（级联） ----
cid = [u for u in ca.get("/api/admin/users").json()["items"] if u["username"] == "test_user_c"][0]["id"]
r = ca.delete(f"/api/admin/users/{cid}")
check("A5 删除用户C", r.status_code == 200, r.text)
r = ca.get("/api/admin/users")
names = [u["username"] for u in r.json()["items"]]
check("A5 用户C已从列表消失", "test_user_c" not in names, str(names))
n = con.execute("SELECT COUNT(*) FROM bot_instances WHERE appid='FAKE9999'").fetchone()[0]
check("A5 级联删除假实例", n == 0, n)

# ---- 清理：测试管理员 ----
uid = con.execute("SELECT id FROM users WHERE username='adm_test01'").fetchone()[0]
con.execute("DELETE FROM login_logs WHERE user_id=?", (uid,))
con.execute("DELETE FROM audit_logs WHERE user_id=?", (uid,))
con.execute("DELETE FROM users WHERE username='adm_test01'")
con.commit()
con.close()
print()
print("=== 汇总 ===")
passed = sum(1 for _, ok, _ in results if ok)
print(f"{passed}/{len(results)} 项通过")
if passed != len(results):
    sys.exit(1)
