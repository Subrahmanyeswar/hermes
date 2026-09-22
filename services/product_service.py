from models.product import Product


class ProductService:
    def __init__(self):
        self.products: list[Product] = []
    def add_product(self, product: Product) -> None:
        self.products.append(product)
    def get_total_inventory_value(self) -> float:
        return sum(p.price for p in self.products)