"""Read-only store data loaded from the challenge CSVs."""

import csv
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from emporio_agent.text import digits, normalize, round_money, tokens

_FILE_TEMPLATE = "desafio_tecnico_ai_eng - {table}.csv"
_STOPWORDS = frozenset(
    {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "para", "com"}
)


class ProductStatus(StrEnum):
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


class Availability(StrEnum):
    AVAILABLE = "disponivel"
    OUT_OF_STOCK = "esgotado"
    DISCONTINUED = "descontinuado"
    COMING_SOON = "em_breve"


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    name: str
    category_id: int
    price: Decimal
    description: str
    stock: int
    status: ProductStatus
    specs: dict[str, str]
    created_at: date

    @property
    def availability(self) -> Availability:
        if self.status is ProductStatus.DISCONTINUED:
            return Availability.DISCONTINUED
        if self.status is ProductStatus.COMING_SOON:
            return Availability.COMING_SOON
        return Availability.AVAILABLE if self.stock > 0 else Availability.OUT_OF_STOCK

    @property
    def is_available(self) -> bool:
        return self.availability is Availability.AVAILABLE


@dataclass(frozen=True, slots=True)
class Promotion:
    id: int
    product_id: int
    discount_percent: int
    description: str
    is_active: bool

    def apply_to(self, price: Decimal) -> Decimal:
        return round_money(price * (100 - self.discount_percent) / 100)


@dataclass(frozen=True, slots=True)
class Customer:
    id: int
    name: str
    phone: str
    email: str
    city: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    def matches_contact(self, contact: str) -> bool:
        """E-mail ignoring case/spaces, or phone by digits (with or without DDD / +55)."""
        if "@" in contact:
            return contact.strip().casefold() == self.email.strip().casefold()
        stored = digits(self.phone)
        return digits(contact) in {stored, stored[2:], "55" + stored}


@dataclass(frozen=True, slots=True)
class OrderItem:
    product_id: int
    quantity: int


@dataclass(frozen=True, slots=True)
class Order:
    id: int
    customer_id: int
    order_date: date
    status: OrderStatus
    total: Decimal  # historical amount charged; not always the sum of current item prices
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: tuple[OrderItem, ...]


@dataclass(frozen=True, slots=True)
class Catalog:
    categories: tuple[Category, ...]
    products: tuple[Product, ...]
    promotions: tuple[Promotion, ...]
    customers: tuple[Customer, ...]
    orders: tuple[Order, ...]

    @classmethod
    def load(cls, data_dir: Path) -> "Catalog":
        items = _load_order_items(_rows(data_dir, "order_items"))
        return cls(
            categories=tuple(map(_category, _rows(data_dir, "categories"))),
            products=tuple(map(_product, _rows(data_dir, "products"))),
            promotions=tuple(map(_promotion, _rows(data_dir, "promotions"))),
            customers=tuple(map(_customer, _rows(data_dir, "customers"))),
            orders=tuple(_order(row, items) for row in _rows(data_dir, "orders")),
        )

    def product(self, product_id: int) -> Product | None:
        return next((p for p in self.products if p.id == product_id), None)

    def find_products(self, name: str) -> list[Product]:
        """Products whose name contains every token of `name` (or whose id equals it).

        An exact (normalized) name match wins over longer names that also contain the tokens.
        """
        query = name.strip()
        if query.isdigit():
            product = self.product(int(query))
            return [product] if product else []
        wanted = _meaningful(tokens(query))
        if not wanted:
            return []
        matches = [p for p in self.products if wanted <= set(tokens(p.name))]
        exact = [p for p in matches if normalize(p.name) == normalize(query)]
        return exact or matches

    def search(
        self,
        term: str | None = None,
        category: Category | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        only_available: bool = False,
    ) -> list[Product]:
        """Filter by category, final price and availability, then by term; cheapest first.

        The term is matched against name + category first; only when nothing matches there does it
        fall back to the product description.
        """
        candidates = [
            p
            for p in self.products
            if (category is None or p.category_id == category.id)
            and (min_price is None or self.final_price(p) >= min_price)
            and (max_price is None or self.final_price(p) <= max_price)
            and (not only_available or p.is_available)
        ]
        if term and (wanted := _meaningful(tokens(term))):
            by_name = [p for p in candidates if wanted <= self._name_tokens(p)]
            candidates = by_name or [
                p for p in candidates if wanted <= self._name_tokens(p) | set(tokens(p.description))
            ]
        return sorted(candidates, key=lambda p: (self.final_price(p), p.id))

    def category(self, category_id: int) -> Category | None:
        return next((c for c in self.categories if c.id == category_id), None)

    def category_by_name(self, name: str) -> Category | None:
        """Unique category whose name (or, failing that, description) contains the query tokens."""
        wanted = _meaningful(tokens(name))
        if not wanted:
            return None
        for field in ("name", "description"):
            matches = [c for c in self.categories if wanted <= set(tokens(getattr(c, field)))]
            if matches:
                return matches[0] if len(matches) == 1 else None
        return None

    def active_promotion(self, product_id: int) -> Promotion | None:
        active = [p for p in self.promotions if p.product_id == product_id and p.is_active]
        return max(active, key=lambda p: p.discount_percent, default=None)

    def final_price(self, product: Product) -> Decimal:
        promotion = self.active_promotion(product.id)
        return promotion.apply_to(product.price) if promotion else product.price

    def order(self, order_id: int) -> Order | None:
        return next((o for o in self.orders if o.id == order_id), None)

    def customer(self, customer_id: int) -> Customer | None:
        return next((c for c in self.customers if c.id == customer_id), None)

    def _name_tokens(self, product: Product) -> set[str]:
        category = self.category(product.category_id)
        category_name = category.name if category else ""
        return set(tokens(f"{product.name} {category_name}"))


def _meaningful(words: Iterable[str]) -> set[str]:
    return {word for word in words if word not in _STOPWORDS}


def _rows(data_dir: Path, table: str) -> Iterator[dict[str, str]]:
    path = data_dir / _FILE_TEMPLATE.format(table=table)
    with path.open(encoding="utf-8", newline="") as file:
        yield from csv.DictReader(file)


def _optional(value: str) -> str | None:
    return value.strip() or None


def _optional_date(value: str) -> date | None:
    text = _optional(value)
    return date.fromisoformat(text) if text else None


def _category(row: dict[str, str]) -> Category:
    return Category(int(row["category_id"]), row["name"], row["description"])


def _product(row: dict[str, str]) -> Product:
    specs = json.loads(row["specs"]) if row["specs"].strip() else {}
    return Product(
        id=int(row["product_id"]),
        name=row["name"].strip(),
        category_id=int(row["category_id"]),
        price=Decimal(row["price_brl"]),
        description=row["description"].strip(),
        stock=int(row["stock_quantity"]),
        status=ProductStatus(row["status"]),
        specs={str(key): str(value) for key, value in specs.items()},
        created_at=date.fromisoformat(row["created_at"]),
    )


def _promotion(row: dict[str, str]) -> Promotion:
    return Promotion(
        id=int(row["promotion_id"]),
        product_id=int(row["product_id"]),
        discount_percent=int(row["discount_percent"]),
        description=row["description"].strip(),
        is_active=row["is_active"].strip() == "1",
    )


def _customer(row: dict[str, str]) -> Customer:
    return Customer(
        id=int(row["customer_id"]),
        name=row["name"].strip(),
        phone=row["phone"].strip(),
        email=row["email"].strip(),
        city=row["city"].strip(),
    )


def _load_order_items(rows: Iterable[dict[str, str]]) -> dict[int, tuple[OrderItem, ...]]:
    items: dict[int, list[OrderItem]] = {}
    for row in rows:
        item = OrderItem(int(row["product_id"]), int(row["quantity"]))
        items.setdefault(int(row["order_id"]), []).append(item)
    return {order_id: tuple(order_items) for order_id, order_items in items.items()}


def _order(row: dict[str, str], items: dict[int, tuple[OrderItem, ...]]) -> Order:
    order_id = int(row["order_id"])
    return Order(
        id=order_id,
        customer_id=int(row["customer_id"]),
        order_date=date.fromisoformat(row["order_date"]),
        status=OrderStatus(row["status"]),
        total=Decimal(row["total_brl"]),
        payment_method=row["payment_method"].strip(),
        tracking_code=_optional(row["tracking_code"]),
        estimated_delivery=_optional_date(row["estimated_delivery"]),
        notes=_optional(row["notes"]),
        items=items.get(order_id, ()),
    )
