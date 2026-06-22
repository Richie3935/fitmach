CREATE DATABASE IF NOT EXISTS fashion_compare;

USE fashion_compare;

CREATE TABLE IF NOT EXISTS search_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    query VARCHAR(255) NOT NULL,
    ip_address VARCHAR(64),
    searched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS store_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    search_log_id INT,
    store_name VARCHAR(80) NOT NULL,
    product_title VARCHAR(500) NOT NULL,
    price_text VARCHAR(80),
    price_value DECIMAL(10,2),
    product_url TEXT,
    image_url TEXT,
    match_score INT DEFAULT 0,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (search_log_id) REFERENCES search_logs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    search_log_id INT,
    store_name VARCHAR(80) NOT NULL,
    product_title VARCHAR(500) NOT NULL,
    price_text VARCHAR(80),
    price_value DECIMAL(10,2),
    product_url TEXT,
    product_key VARCHAR(255) NOT NULL,
    image_url TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_price_history_product_key (product_key)
);


CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wishlist: the single product-tracking system for items users want to monitor or purchase
CREATE TABLE IF NOT EXISTS wishlist (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    store_name VARCHAR(80) NOT NULL,
    product_title VARCHAR(500) NOT NULL,
    price_text VARCHAR(80),
    price_value DECIMAL(10,2),
    product_url TEXT,
    product_key VARCHAR(255) NOT NULL,
    image_url TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_wishlist_product_key (product_key)
);

