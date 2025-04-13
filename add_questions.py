#!/usr/bin/env python3
import requests

# Examples of questions and their SQL queries
examples = [
    # Simple queries (existing)
    {
        "question": "Which customers are from California state?",
        "sql_query": "SELECT * FROM customers c WHERE c.state = 'CA'"
    },
    {
        "question": "List of products with a price greater than 100€",
        "sql_query": "SELECT * FROM products p WHERE p.price > 100"
    },
    {
        "question": "How many orders did we receive in 2023?",
        "sql_query": "SELECT COUNT(*) FROM orders o WHERE EXTRACT(YEAR FROM o.order_date) = 2023"
    },
    
    # Queries with simple joins
    {
        "question": "Which customers placed an order this month?",
        "sql_query": "SELECT DISTINCT c.* FROM customers c JOIN orders o ON c.id = o.customer_id WHERE o.order_date >= DATE_TRUNC('month', CURRENT_DATE)"
    },
    {
        "question": "What products were ordered by customer John Doe?",
        "sql_query": "SELECT p.name FROM products p JOIN order_items oi ON p.id = oi.product_id JOIN orders o ON oi.order_id = o.id JOIN customers c ON o.customer_id = c.id WHERE c.first_name = 'John' AND c.last_name = 'Doe'"
    },
    
    # Queries with aggregation
    {
        "question": "How many customers do we have per state?",
        "sql_query": "SELECT c.state, COUNT(*) as client_count FROM customers c GROUP BY c.state"
    },
    {
        "question": "What is the average order value by state?",
        "sql_query": "SELECT c.state, AVG(o.total_amount) AS average_orders FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.state"
    },
    
    # Complex queries
    {
        "question": "Who are the top 10 customers who spend the most?",
        "sql_query": "SELECT c.first_name, c.last_name, SUM(oi.quantity * oi.unit_price) AS total_spent FROM customers c JOIN orders o ON c.id = o.customer_id JOIN order_items oi ON o.id = oi.order_id GROUP BY c.id, c.first_name, c.last_name ORDER BY total_spent DESC LIMIT 10"
    },
    {
        "question": "Which customers have never placed an order?",
        "sql_query": "SELECT c.* FROM customers c LEFT JOIN orders o ON c.id = o.customer_id WHERE o.id IS NULL"
    },
    {
        "question": "What are the 5 most ordered products?",
        "sql_query": "SELECT p.name, SUM(oi.quantity) as total_ordered FROM products p JOIN order_items oi ON p.id = oi.product_id GROUP BY p.id, p.name ORDER BY total_ordered DESC LIMIT 5"
    },
    
    # Queries with subqueries
    {
        "question": "Which customers placed their last order more than 3 months ago?",
        "sql_query": "SELECT c.* FROM customers c JOIN (SELECT customer_id, MAX(order_date) as last_order_date FROM orders GROUP BY customer_id) o ON c.id = o.customer_id WHERE o.last_order_date < CURRENT_DATE - INTERVAL '3 months'"
    },
    {
        "question": "Which customers have placed more than 2 orders?",
        "sql_query": "SELECT c.* FROM customers c JOIN (SELECT customer_id, COUNT(*) as num_orders FROM orders GROUP BY customer_id HAVING COUNT(*) > 2) o ON c.id = o.customer_id"
    },
    
    # Advanced analysis queries
    {
        "question": "What is the average order value by day of the week?",
        "sql_query": "SELECT EXTRACT(DOW FROM o.order_date) AS day_of_week, TO_CHAR(o.order_date, 'Day') AS day_name, AVG(o.total_amount) AS average_order_value FROM orders o GROUP BY day_of_week, day_name ORDER BY day_of_week"
    },
    {
        "question": "Which products are often purchased together?",
        "sql_query": "SELECT p1.name AS product1_name, p2.name AS product2_name, COUNT(*) AS times_bought_together FROM order_items oi1 JOIN order_items oi2 ON oi1.order_id = oi2.order_id AND oi1.product_id < oi2.product_id JOIN products p1 ON oi1.product_id = p1.id JOIN products p2 ON oi2.product_id = p2.id GROUP BY p1.name, p2.name ORDER BY times_bought_together DESC LIMIT 10"
    },
    {
        "question": "Which state generated the most revenue?",
        "sql_query": "SELECT c.state, SUM(oi.quantity * oi.unit_price) AS total_revenue FROM customers c JOIN orders o ON c.id = o.customer_id JOIN order_items oi ON o.id = oi.order_id GROUP BY c.state ORDER BY total_revenue DESC LIMIT 1"
    }
]

# Embedding service endpoint
store_url = "http://localhost:8001/store"

# Add each example
for example in examples:
    response = requests.post(store_url, json=example)
    print(f"Adding '{example['question']}': {response.status_code}")
    print(response.json())