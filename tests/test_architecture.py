from pathlib import Path

import app.modules.delivery.repository as delivery_repository
import app.modules.menu.repository as menu_repository
import app.modules.orders.repository as orders_repository
import app.modules.users.repository as users_repository

MODULES = ("orders", "users", "menu", "delivery")


def test_services_do_not_import_frameworks():
    root = Path(__file__).resolve().parents[1] / "app" / "modules"
    for name in MODULES:
        source = (root / name / "service.py").read_text(encoding="utf-8")
        assert "fastapi" not in source
        assert "sqlalchemy" not in source


def test_factory_swaps_backend_without_touching_service(monkeypatch):
    modules = (
        orders_repository,
        users_repository,
        menu_repository,
        delivery_repository,
    )
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    for module in modules:
        module._memory_repository = None
        factory_name = next(
            name
            for name in dir(module)
            if name.startswith("create_") and name.endswith("_repository")
        )
        factory = getattr(module, factory_name)
        repository = factory(None)
        assert repository is factory(None)
        assert type(repository).__name__.startswith("InMemory")
