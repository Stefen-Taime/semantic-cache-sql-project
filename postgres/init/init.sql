-- Initialisation de la base de données pour le projet de mise en cache sémantique
-- Création des tables et insertion de données d'exemple

-- Création de la table des clients
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    state VARCHAR(2) NOT NULL,
    city VARCHAR(50) NOT NULL,
    registration_date DATE NOT NULL,
    status VARCHAR(20) CHECK (status IN ('active', 'inactive', 'pending')) NOT NULL
);

-- Création de la table des produits
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    stock_quantity INTEGER NOT NULL DEFAULT 0
);

-- Création de la table des commandes
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    order_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(12, 2) NOT NULL,
    status VARCHAR(20) CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')) NOT NULL
);

-- Création de la table des détails de commande
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL
);

-- Insertion de données d'exemple pour les clients
INSERT INTO customers (first_name, last_name, email, state, city, registration_date, status) VALUES
('John', 'Doe', 'john.doe@example.com', 'CA', 'San Francisco', '2023-01-15', 'active'),
('Jane', 'Smith', 'jane.smith@example.com', 'NY', 'New York', '2023-02-20', 'active'),
('Robert', 'Johnson', 'robert.johnson@example.com', 'TX', 'Austin', '2023-03-10', 'active'),
('Emily', 'Williams', 'emily.williams@example.com', 'FL', 'Miami', '2023-04-05', 'inactive'),
('Michael', 'Brown', 'michael.brown@example.com', 'CA', 'Los Angeles', '2023-05-12', 'active'),
('Sarah', 'Davis', 'sarah.davis@example.com', 'NY', 'Buffalo', '2023-06-18', 'pending'),
('David', 'Miller', 'david.miller@example.com', 'TX', 'Dallas', '2023-07-22', 'active'),
('Jennifer', 'Wilson', 'jennifer.wilson@example.com', 'FL', 'Orlando', '2023-08-30', 'active'),
('James', 'Taylor', 'james.taylor@example.com', 'CA', 'San Diego', '2023-09-14', 'inactive'),
('Lisa', 'Anderson', 'lisa.anderson@example.com', 'NY', 'Albany', '2023-10-25', 'active');

-- Insertion de données d'exemple pour les produits
INSERT INTO products (name, description, category, price, stock_quantity) VALUES
('Laptop Pro', 'High-performance laptop for professionals', 'Electronics', 1299.99, 50),
('Smartphone X', 'Latest smartphone with advanced features', 'Electronics', 899.99, 100),
('Wireless Headphones', 'Noise-cancelling wireless headphones', 'Electronics', 199.99, 75),
('Office Chair', 'Ergonomic office chair for comfort', 'Furniture', 249.99, 30),
('Standing Desk', 'Adjustable height standing desk', 'Furniture', 399.99, 20),
('Coffee Maker', 'Programmable coffee maker with timer', 'Appliances', 79.99, 45),
('Blender', 'High-speed blender for smoothies', 'Appliances', 129.99, 35),
('Fitness Tracker', 'Waterproof fitness tracker with heart rate monitor', 'Wearables', 149.99, 60),
('Smart Watch', 'Smart watch with GPS and health tracking', 'Wearables', 299.99, 40),
('Wireless Earbuds', 'True wireless earbuds with charging case', 'Electronics', 129.99, 80);

-- Insertion de données d'exemple pour les commandes
INSERT INTO orders (customer_id, order_date, total_amount, status) VALUES
(1, '2023-11-01 10:30:00', 1499.98, 'delivered'),
(2, '2023-11-05 14:45:00', 899.99, 'shipped'),
(3, '2023-11-10 09:15:00', 329.98, 'processing'),
(4, '2023-11-15 16:20:00', 249.99, 'pending'),
(5, '2023-11-20 11:00:00', 1029.98, 'delivered'),
(6, '2023-11-25 13:30:00', 399.99, 'cancelled'),
(7, '2023-12-01 15:45:00', 279.98, 'shipped'),
(8, '2023-12-05 10:10:00', 449.98, 'processing'),
(9, '2023-12-10 12:25:00', 129.99, 'pending'),
(10, '2023-12-15 14:50:00', 1199.97, 'delivered');

-- Insertion de données d'exemple pour les détails de commande
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
(1, 1, 1, 1299.99),
(1, 3, 1, 199.99),
(2, 2, 1, 899.99),
(3, 3, 1, 199.99),
(3, 6, 1, 129.99),
(4, 4, 1, 249.99),
(5, 2, 1, 899.99),
(5, 6, 1, 129.99),
(6, 5, 1, 399.99),
(7, 6, 1, 79.99),
(7, 7, 1, 199.99),
(8, 8, 1, 149.99),
(8, 9, 1, 299.99),
(9, 10, 1, 129.99),
(10, 1, 1, 1299.99),
(10, 3, 1, 199.99),
(10, 6, 1, 79.99);

-- Création d'index pour améliorer les performances
CREATE INDEX idx_customers_state ON customers(state);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);

-- Afficher un message de confirmation
SELECT 'Base de données initialisée avec succès avec des données d\'exemple' as message;
