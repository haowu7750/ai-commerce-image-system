from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.enums import RoleName
from app.models.identity import Role, User, UserRole
from app.security import hash_password


ROLE_DESCRIPTIONS = {
    RoleName.OPERATOR.value: "电商运营：拥有业务最终确认权",
    RoleName.DESIGNER.value: "美工：处理分配的设计任务",
    RoleName.ADMIN.value: "管理员：管理系统配置，不自动拥有运营权限",
}

DEMO_USERS = {
    "operator@example.local": ("演示运营", RoleName.OPERATOR.value),
    "designer@example.local": ("演示美工", RoleName.DESIGNER.value),
    "admin@example.local": ("演示管理员", RoleName.ADMIN.value),
}


def ensure_roles(db: Session) -> dict[str, Role]:
    existing = {role.name: role for role in db.scalars(select(Role)).all()}
    for name, description in ROLE_DESCRIPTIONS.items():
        if name not in existing:
            role = Role(name=name, description=description)
            db.add(role)
            existing[name] = role
    db.flush()
    return existing


def seed_demo_accounts(db: Session, settings: Settings) -> None:
    roles = ensure_roles(db)
    if not settings.seed_demo_data or settings.demo_password is None:
        db.commit()
        return

    password = settings.demo_password.get_secret_value()
    for email, (display_name, role_name) in DEMO_USERS.items():
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name=display_name,
                password_hash=hash_password(password),
                is_active=True,
            )
            db.add(user)
            db.flush()
        if role_name not in user.role_names:
            db.add(UserRole(user_id=user.id, role_id=roles[role_name].id))
    db.commit()

