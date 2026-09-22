from flask import Flask, request, jsonify

app = Flask(__name__)

class Order:
    """Order model with a new status field."""
    def __init__(self, order_id, status="pending"):
        self.order_id = order_id
        self.status = status

def create_order():
    """Endpoint to create a new order with optional status."""
    data = request.get_json()
    if not data or 'order_id' not in data:
        return jsonify({"error": "Missing order_id"}), 400
    order_id = data['order_id']
    status = data.get('status', 'pending')
    # In a real application, this would save to a database
    orders[order_id] = Order(order_id, status)
    return jsonify({
        "message": "Order created successfully",
        "order_id": order_id,
        "status": status
    }), 201

def get_order(order_id):
    """Endpoint to retrieve an order's details, including status."""
    # In a real application, this would fetch from a database
    order = orders.get(order_id)
    if order:
        return jsonify({
            "order_id": order.order_id,
            "status": order.status
        })
    return jsonify({"error": "Order not found"}), 404

# Dummy data for demonstration
orders = {}

# Register routes
app.add_url_rule('/orders', 'create_order', create_order, methods=['POST'])
app.add_url_rule('/orders/<order_id>', 'get_order', get_order, methods=['GET'])

if __name__ == '__main__':
    app.run(debug=True)