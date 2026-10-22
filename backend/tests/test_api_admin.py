"""管理员用户管理（issue #114）：列表 / 改角色状态 / 手工验证；自锁守卫。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import login_as, make_app


def test_admin_only() -> None:
    app = make_app()
    with TestClient(app) as alice, TestClient(app) as anon:
        login_as(alice, "alice")
        assert anon.get("/api/v1/admin/users").status_code == 401
        assert alice.get("/api/v1/admin/users").status_code == 403


def test_list_patch_verify() -> None:
    app = make_app()
    with TestClient(app) as root, TestClient(app) as bob:
        login_as(root, "root", role="admin")
        bob_me = login_as(bob, "bob")
        users = root.get("/api/v1/admin/users").json()
        assert sorted(u["username"] for u in users) == ["bob", "root"]
        assert all("password" not in u for u in users)
        # 禁用 → bob 会话立即失效
        r = root.patch(f"/api/v1/admin/users/{bob_me['user_id']}", json={"status": "disabled"})
        assert r.status_code == 200 and r.json()["status"] == "disabled"
        assert bob.get("/api/v1/auth/me").status_code == 401
        r = root.patch(
            f"/api/v1/admin/users/{bob_me['user_id']}",
            json={"status": "active", "role": "admin"},
        )
        assert r.json()["role"] == "admin"
        assert root.patch("/api/v1/admin/users/u_nope", json={"role": "user"}).status_code == 404
        # 手工验证
        users_store = app.state.users
        u = users_store.get(bob_me["user_id"])
        users_store.put(u.model_copy(update={"email_verified_at": None}))
        r = root.post(f"/api/v1/admin/users/{bob_me['user_id']}/verify")
        assert r.status_code == 200 and r.json()["email_verified"] is True


def test_admin_cannot_lock_itself_out() -> None:
    app = make_app()
    with TestClient(app) as root, TestClient(app) as root2:
        me = login_as(root, "root", role="admin")
        uid = me["user_id"]
        assert root.patch(f"/api/v1/admin/users/{uid}", json={"role": "user"}).status_code == 400
        r = root.patch(f"/api/v1/admin/users/{uid}", json={"status": "disabled"})
        assert r.status_code == 400
        me2 = login_as(root2, "root2", role="admin")
        # 两个 admin：可以降级另一个；之后 root2 不再是 admin → 403
        r = root.patch(f"/api/v1/admin/users/{me2['user_id']}", json={"role": "user"})
        assert r.status_code == 200
        assert root2.get("/api/v1/admin/users").status_code == 403
        r = root2.patch(f"/api/v1/admin/users/{uid}", json={"role": "user"})
        assert r.status_code == 403
