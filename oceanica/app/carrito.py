"""Lógica de la orden en captura (sin interfaz, para poder probarla)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")


@dataclass
class Linea:
    servicio_id: int
    nombre: str
    unidad: str
    precio: Decimal
    cantidad: Decimal

    @property
    def importe(self) -> Decimal:
        return (self.precio * self.cantidad).quantize(CENTAVO, rounding=ROUND_HALF_UP)


class Carrito:
    def __init__(self):
        self.lineas: list[Linea] = []
        self.descuento = Decimal("0.00")

    def agregar(self, servicio: dict, cantidad: Decimal | None) -> None:
        if cantidad is None or cantidad <= 0:
            raise ValueError("Escribe una cantidad mayor que cero.")
        if servicio["unidad"] == "pieza" and cantidad != cantidad.to_integral_value():
            raise ValueError(f"'{servicio['nombre']}' se cobra por pieza: la cantidad debe ser un número entero.")
        cantidad = cantidad.quantize(CENTAVO)
        for l in self.lineas:
            if l.servicio_id == servicio["id"]:
                l.cantidad += cantidad
                return
        self.lineas.append(Linea(servicio["id"], servicio["nombre"], servicio["unidad"], Decimal(servicio["precio"]), cantidad))

    def quitar(self, indice: int) -> None:
        if 0 <= indice < len(self.lineas):
            del self.lineas[indice]

    def limpiar(self) -> None:
        self.lineas.clear()
        self.descuento = Decimal("0.00")

    @property
    def subtotal(self) -> Decimal:
        return sum((l.importe for l in self.lineas), Decimal("0.00"))

    @property
    def total(self) -> Decimal:
        return max(self.subtotal - self.descuento, Decimal("0.00"))

    def items(self) -> list[dict]:
        return [{"servicio_id": l.servicio_id, "cantidad": l.cantidad} for l in self.lineas]

    def __bool__(self) -> bool:
        return bool(self.lineas)
