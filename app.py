from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
import psycopg2.extras
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = 'adwdfdg115d'  # Use a stronger, more secure key in production

# PostgreSQL Database URL
DATABASE_URL = "dbname='Sprinkles' user='postgres' password='123456789' host='localhost' port='5432'"

# Database Connection
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

@app.route('/')
def menu():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM menu_items
            WHERE available = TRUE
            ORDER BY 
                CASE 
                    WHEN type = 'Shake' THEN 1
                    WHEN type = 'Juice' THEN 2
                    WHEN type = 'Fruit Salad' THEN 3
                    WHEN type = 'Falooda' THEN 4
                    WHEN type = 'Snacks' THEN 5
                    ELSE 6
                END, id;
        """)
        menu_items = cur.fetchall()
        return render_template('menu.html', menu_items=menu_items)
    finally:
        cur.close()
        conn.close()

# Login Page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT id, username, password FROM staff WHERE username=%s AND password=%s",
            (username, password)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session['username'] = user['username']
            session['role'] = role

            if role == 'waiter':
                return redirect(url_for('waiter_dashboard'))
            elif role == 'kitchen':
                return redirect(url_for('kitchen_dashboard'))
            elif role == 'cash':
                return redirect(url_for('cash_dashboard'))
        else:
            return "Invalid credentials or role. Please try again."
    return render_template('login.html')

# Waiter Dashboard
@app.route('/waiter')
def waiter_dashboard():
    if session.get('role') != 'waiter':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, type, description, price, available FROM menu_items WHERE available = TRUE")
    menu_items = cur.fetchall()
    cur.close()
    conn.close()

    menu = [
        {
            'id': item[0],
            'name': item[1],
            'type': item[2],
            'description': item[3],
            'price': float(item[4]),
            'available': item[5]
        } for item in menu_items
    ]
    return render_template('waiter.html', username=session['username'], menu_items=menu)

# Generate Bill
@app.route('/generate_bill', methods=['POST'])
def generate_bill():
    if session.get('role') != 'waiter':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid or missing JSON'}), 400

    items = data.get('items')
    table_no = data.get('table_no')

    if not items or not table_no:
        return jsonify({'success': False, 'message': 'Missing order data'}), 400

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        total = 0.0
        valid_items = []

        for item in items:
            item_id = item.get('id')
            quantity = int(item.get('quantity', 1))
            if not item_id or quantity <= 0:
                continue

            cur.execute("SELECT name, price FROM menu_items WHERE id = %s AND available = TRUE", (item_id,))
            result = cur.fetchone()
            if result:
                name = result['name']
                price = float(result['price'])
                total += price * quantity
                valid_items.append({'id': item_id, 'name': name, 'quantity': quantity})

        if not valid_items:
            return jsonify({'success': False, 'message': 'No valid items in the order'}), 400

        timestamp = datetime.now()
        cur.execute("""
            INSERT INTO orders (items, status, table_no, timestamp, staff, total)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            json.dumps(valid_items),
            'placed',
            table_no,
            timestamp,
            session['username'],
            round(total, 2)
        ))
        order_id = cur.fetchone()['id']
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'Order placed and bill generated.',
            'order_id': order_id,
            'total': round(total, 2)
        })

    except Exception as e:
        print(f"[ERROR] Failed to generate bill: {e}")
        return jsonify({'success': False, 'message': 'Server error occurred'}), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/kitchen')
def kitchen_dashboard():
    if session.get('role') != 'kitchen':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Fetch available menu items
    cur.execute("SELECT id, name, type, description, price, available FROM menu_items WHERE available = TRUE ORDER BY id")
    menu_items = cur.fetchall()

    # Fetch only orders with status 'placed'
    cur.execute("SELECT id, items, status, table_no, timestamp, staff FROM orders WHERE status = 'placed' ORDER BY timestamp DESC")
    raw_orders = cur.fetchall()

    orders = []
    for row in raw_orders:
        items = json.loads(row['items'])
        orders.append((row['id'], items, row['status'], row['table_no'], row['timestamp'], row['staff']))

    cur.close()
    conn.close()

    return render_template('kitchen.html', menu_items=menu_items, orders=orders)

@app.route('/update_menu', methods=['POST'])
def update_menu():
    if session.get('role') != 'kitchen':
        return redirect(url_for('login'))

    data = request.get_json()
    updates = data.get('updates', [])

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        for item in updates:
            cur.execute("UPDATE menu_items SET available = %s WHERE id = %s", (item['available'], item['id']))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"[ERROR] Failed to update menu availability: {e}")
        return jsonify({'success': False, 'message': 'Update failed'}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/update_order_status_kitchen', methods=['POST'])
def update_order_status_kitchen():
    if session.get('role') != 'kitchen':
        return redirect(url_for('login'))

    data = request.get_json()
    order_id = data.get('order_id')
    if not order_id:
        return jsonify({'success': False, 'message': 'Missing order ID'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE orders SET status = 'delivered' WHERE id = %s", (order_id,))
        conn.commit()
        return jsonify({'success': True})
    except Exception as e:
        print(f"[ERROR] Failed to update order status: {e}")
        return jsonify({'success': False, 'message': 'Status update failed'}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/cash')
def cash_dashboard():
    if session.get('role') != 'cash':
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Fetch both delivered and paid orders
    cur.execute("SELECT id, items, status, table_no, timestamp, staff, total FROM orders WHERE status IN ('delivered', 'paid') ORDER BY timestamp DESC")
    raw_orders = cur.fetchall()

    orders = []
    for row in raw_orders:
        items = json.loads(row['items'])
        orders.append((row['id'], items, row['status'], row['table_no'], row['timestamp'], row['staff'], row['total']))

    cur.close()
    conn.close()

    return render_template('cashout.html', username=session['username'], orders=orders)

@app.route('/update_order_status_cash', methods=['POST'])
def update_order_status_cash():
    if session.get('role') != 'cash':
        return jsonify({'success': False, 'message': 'Unauthorized access'}), 403

    data = request.get_json()
    order_id = data.get('id')
    new_status = data.get('status')

    conn = get_db_connection()
    cur = conn.cursor()

    # Update the order status in the database
    cur.execute("UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
    conn.commit()

    cur.close()
    conn.close()

    return jsonify({'success': True})

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run()