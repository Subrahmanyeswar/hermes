import sys
from inventory.checker import check_inventory
from shipment.tracker import track_shipment

class Order:
    """Represents an order with items and order ID."""
    def __init__(self, order_id, items):
        self.order_id = order_id
        self.items = items  # List of items with quantity


def fulfill_order(order):
    """Fulfills an order by checking inventory and tracking shipment."""
    try:
        # Check inventory
        inventory_status = check_inventory(order.items)
        if not inventory_status['all_in_stock']:
            raise Exception("Not all items in stock")
        
        # Track shipment
        shipment_id = track_shipment(order)
        return {"status": "fulfilled", "shipment_id": shipment_id}
    except Exception as e:
        print(f"Error fulfilling order: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Example usage
    order = Order(order_id="ORD123", items=[{"product_id": "A", "quantity": 2}, {"product_id": "B", "quantity": 1}])
    result = fulfill_order(order)
    print(result)