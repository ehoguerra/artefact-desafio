"""Price quotes: active promotion, PIX discount and interest-free installments (manual §3, §6.2)."""

from dataclasses import dataclass
from decimal import Decimal

from emporio_agent.store.catalog import Product, Promotion
from emporio_agent.text import round_money

PIX_DISCOUNT_PERCENT = 5
MAX_INSTALLMENTS = 12
MIN_TOTAL_FOR_INSTALLMENTS = Decimal("50.00")
# (largest installment count in the tier, minimum installment value)
_INSTALLMENT_TIERS = ((3, Decimal("0")), (6, Decimal("80.00")), (12, Decimal("100.00")))


@dataclass(frozen=True, slots=True)
class PriceQuote:
    list_price: Decimal
    promotion: Promotion | None
    final_price: Decimal
    pix_price: Decimal | None
    max_installments: int
    installment_value: Decimal


def quote(product: Product, promotion: Promotion | None) -> PriceQuote:
    final_price = promotion.apply_to(product.price) if promotion else product.price
    installments = _max_installments(final_price)
    return PriceQuote(
        list_price=product.price,
        promotion=promotion,
        final_price=final_price,
        pix_price=None if promotion else _pix_price(final_price),
        max_installments=installments,
        installment_value=round_money(final_price / installments),
    )


def _max_installments(total: Decimal) -> int:
    if total < MIN_TOTAL_FOR_INSTALLMENTS:
        return 1
    return max(n for n in range(1, MAX_INSTALLMENTS + 1) if total / n >= _minimum_installment(n))


def _minimum_installment(installments: int) -> Decimal:
    return next(minimum for limit, minimum in _INSTALLMENT_TIERS if installments <= limit)


def _pix_price(price: Decimal) -> Decimal:
    return round_money(price * (100 - PIX_DISCOUNT_PERCENT) / 100)
