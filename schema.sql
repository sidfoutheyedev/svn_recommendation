-- The 4 tables. Created automatically the first time the job or the API runs.

CREATE EXTENSION IF NOT EXISTS vector;

-- one row per active product
CREATE TABLE IF NOT EXISTS products (
    product_id     TEXT PRIMARY KEY,
    gender         TEXT NOT NULL,              -- male / female / other
    category       TEXT NOT NULL,              -- casual, formal, ... (whatever the CSV has)
    style          TEXT NOT NULL,              -- topwear, bottomwear, ...
    primary_image  TEXT NOT NULL,
    embedding_text TEXT NOT NULL,
    product_vector vector(512) NOT NULL        -- 512 numbers from FashionCLIP
);

-- NEW: speeds up the per-category lookups (exact results, nothing changes) / this is added for faster lookups.
CREATE INDEX IF NOT EXISTS products_category_gender_idx
ON products (category, gender);

-- one row per user
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    gender  TEXT NOT NULL
);

-- one row per user per category they follow: what they like in that category
CREATE TABLE IF NOT EXISTS user_vectors (
    user_id     TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    user_vector vector(512) NOT NULL,
    PRIMARY KEY (user_id, category)
);

-- the interaction log: one row per product shown to a user. action stays empty until they swipe it.
CREATE TABLE IF NOT EXISTS feed_log (
    user_id    TEXT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    product_id TEXT NOT NULL,
    action     TEXT,
    shown_at   TIMESTAMP NOT NULL DEFAULT now(),
    swiped_at  TIMESTAMP,
    PRIMARY KEY (user_id, product_id)          -- a product is never shown twice to the same user
);
