from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Integer, MetaData, Numeric, String, Table, func, select
from sqlalchemy.engine import Engine

from src.db import get_database_type, get_engine


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def define_demo_tables(metadata: MetaData) -> dict[str, Table]:
    customers = Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("name", String(255), nullable=False),
        Column("email", String(255), nullable=False),
        Column("city", String(120), nullable=False),
        Column("status", String(50), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("deleted_at", DateTime(timezone=True), nullable=True),
    )
    orders = Table(
        "orders",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
        Column("order_date", DateTime(timezone=True), nullable=False),
        Column("amount", Numeric(12, 2), nullable=False),
        Column("payment_status", String(50), nullable=False),
        Column("fulfillment_status", String(50), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("deleted_at", DateTime(timezone=True), nullable=True),
    )
    audit_log = Table(
        "audit_log",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("table_name", String(255), nullable=False),
        Column("record_id", String(255), nullable=False),
        Column("action", String(100), nullable=False),
        Column("before_data", String, nullable=True),
        Column("after_data", String, nullable=True),
        Column("actor", String(255), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    return {
        "customers": customers,
        "orders": orders,
        "audit_log": audit_log,
    }


def _seed_customers(engine: Engine, customers: Table) -> None:
    now = utc_now()
    deleted_time = now - timedelta(days=3)
    rows = [
        {
            "name": "Alya Pratama",
            "email": "alya.pratama@example.com",
            "city": "Makassar",
            "status": "active",
            "created_at": now - timedelta(days=20),
            "updated_at": now - timedelta(days=2),
            "deleted_at": None,
        },
        {
            "name": "Budi Santoso",
            "email": "budi.santoso@example.com",
            "city": "Jakarta",
            "status": "active",
            "created_at": now - timedelta(days=18),
            "updated_at": now - timedelta(days=1),
            "deleted_at": None,
        },
        {
            "name": "Citra Lestari",
            "email": "citra.lestari@example.com",
            "city": "Bandung",
            "status": "inactive",
            "created_at": now - timedelta(days=16),
            "updated_at": now - timedelta(days=4),
            "deleted_at": None,
        },
        {
            "name": "Dewa Saputra",
            "email": "dewa.saputra@example.com",
            "city": "Surabaya",
            "status": "active",
            "created_at": now - timedelta(days=12),
            "updated_at": now - timedelta(days=3),
            "deleted_at": None,
        },
        {
            "name": "Eka Wulandari",
            "email": "eka.wulandari@example.com",
            "city": "Makassar",
            "status": "inactive",
            "created_at": now - timedelta(days=10),
            "updated_at": deleted_time,
            "deleted_at": deleted_time,
        },
        {
            "name": "Farhan Hidayat",
            "email": "farhan.hidayat@example.com",
            "city": "Semarang",
            "status": "active",
            "created_at": now - timedelta(days=9),
            "updated_at": now - timedelta(days=2),
            "deleted_at": None,
        },
        {
            "name": "Gita Maharani",
            "email": "gita.maharani@example.com",
            "city": "Yogyakarta",
            "status": "active",
            "created_at": now - timedelta(days=7),
            "updated_at": now - timedelta(days=1),
            "deleted_at": None,
        },
        {
            "name": "Hendra Wijaya",
            "email": "hendra.wijaya@example.com",
            "city": "Denpasar",
            "status": "prospect",
            "created_at": now - timedelta(days=5),
            "updated_at": now - timedelta(days=1),
            "deleted_at": None,
        },
    ]
    with engine.begin() as connection:
        connection.execute(customers.insert(), rows)


def _seed_orders(engine: Engine, customers: Table, orders: Table) -> None:
    now = utc_now()
    with engine.connect() as connection:
        customer_ids = connection.execute(select(customers.c.id).order_by(customers.c.id)).scalars().all()

    if not customer_ids:
        return

    rows = [
        {
            "customer_id": customer_ids[0],
            "order_date": now - timedelta(days=9),
            "amount": Decimal("250000.00"),
            "payment_status": "paid",
            "fulfillment_status": "shipped",
            "created_at": now - timedelta(days=9),
            "updated_at": now - timedelta(days=8),
            "deleted_at": None,
        },
        {
            "customer_id": customer_ids[1],
            "order_date": now - timedelta(days=8),
            "amount": Decimal("175000.50"),
            "payment_status": "paid",
            "fulfillment_status": "processing",
            "created_at": now - timedelta(days=8),
            "updated_at": now - timedelta(days=7),
            "deleted_at": None,
        },
        {
            "customer_id": customer_ids[2],
            "order_date": now - timedelta(days=7),
            "amount": Decimal("99000.00"),
            "payment_status": "pending",
            "fulfillment_status": "pending",
            "created_at": now - timedelta(days=7),
            "updated_at": now - timedelta(days=6),
            "deleted_at": None,
        },
        {
            "customer_id": customer_ids[3],
            "order_date": now - timedelta(days=6),
            "amount": Decimal("560000.00"),
            "payment_status": "paid",
            "fulfillment_status": "delivered",
            "created_at": now - timedelta(days=6),
            "updated_at": now - timedelta(days=4),
            "deleted_at": None,
        },
        {
            "customer_id": customer_ids[0],
            "order_date": now - timedelta(days=5),
            "amount": Decimal("88000.00"),
            "payment_status": "failed",
            "fulfillment_status": "cancelled",
            "created_at": now - timedelta(days=5),
            "updated_at": now - timedelta(days=5),
            "deleted_at": None,
        },
        {
            "customer_id": customer_ids[5],
            "order_date": now - timedelta(days=4),
            "amount": Decimal("320500.00"),
            "payment_status": "paid",
            "fulfillment_status": "processing",
            "created_at": now - timedelta(days=4),
            "updated_at": now - timedelta(days=3),
            "deleted_at": None,
        },
    ]
    with engine.begin() as connection:
        connection.execute(orders.insert(), rows)


def seed_demo_database(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    metadata = MetaData()
    tables = define_demo_tables(metadata)
    metadata.create_all(engine)

    with engine.connect() as connection:
        customer_count = connection.execute(select(func.count()).select_from(tables["customers"])).scalar_one()
        order_count = connection.execute(select(func.count()).select_from(tables["orders"])).scalar_one()

    if customer_count == 0:
        _seed_customers(engine, tables["customers"])
    if order_count == 0:
        _seed_orders(engine, tables["customers"], tables["orders"])


def ensure_demo_seed_for_sqlite(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    if get_database_type(str(engine.url)) == "SQLite":
        seed_demo_database(engine)


def main() -> None:
    engine = get_engine()
    seed_demo_database(engine)
    print(f"Demo database ready: {engine.url}")


if __name__ == "__main__":
    main()
