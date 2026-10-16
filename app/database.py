# app/database.py
# All the SQL lives in this file.
#
# Vectors go into Postgres as text like "[0.12, -0.5, ...]" and "::vector" turns that text into a vector.
# They come back out with "::real[]" (a plain list of numbers) and np.array() turns that into numpy.

import numpy as np
from psycopg_pool import ConnectionPool

from app import config

# Up to 10 connections that stay open and are shared by all requests.
# timeout=5: if the database doesn't answer in 5 seconds, give up with an error.
pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=15, open=True, timeout=5,
                      check=ConnectionPool.check_connection)


def vector_text(vector):
    return str(vector.tolist())


def create_tables():
    with pool.connection() as conn:
        conn.execute(open("schema.sql").read())


# ---------------- products (used by embedding_job.py) ----------------

def get_products():
    # product_id -> the product as it is in the database now
    with pool.connection() as conn:
        rows = conn.execute("SELECT product_id, gender, category, style, primary_image, embedding_text FROM products").fetchall()
    products = {}
    for row in rows:
        products[row[0]] = {"gender": row[1], "category": row[2], "style": row[3],
                            "primary_image": row[4], "embedding_text": row[5]}
    return products


def save_product(product, product_vector):
    # add the product, or replace it if it already exists
    with pool.connection() as conn:
        conn.execute("""
            INSERT INTO products (product_id, gender, category, style, primary_image, embedding_text, product_vector)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (product_id) DO UPDATE SET
                gender = EXCLUDED.gender, category = EXCLUDED.category, style = EXCLUDED.style,
                primary_image = EXCLUDED.primary_image, embedding_text = EXCLUDED.embedding_text,
                product_vector = EXCLUDED.product_vector
        """, (product["product_id"], product["gender"], product["category"], product["style"],
              product["primary_image"], product["embedding_text"], vector_text(product_vector)))


def update_fields(product):
    with pool.connection() as conn:
        conn.execute("UPDATE products SET gender = %s, category = %s, style = %s WHERE product_id = %s",
                     (product["gender"], product["category"], product["style"], product["product_id"]))


def delete_product(product_id):
    with pool.connection() as conn:
        conn.execute("DELETE FROM products WHERE product_id = %s", (product_id,))


def most_similar(product_id, how_many):
    # used by check_vectors.py. <=> is the distance between vectors, so 1 - distance = similarity (1 = identical)
    with pool.connection() as conn:
        return conn.execute("""
            SELECT product_id, category, style, 1 - (product_vector <=> (SELECT product_vector FROM products WHERE product_id = %s))
            FROM products
            ORDER BY product_vector <=> (SELECT product_vector FROM products WHERE product_id = %s)
            LIMIT %s
        """, (product_id, product_id, how_many)).fetchall()


# ---------------- the API (these get conn from main.py, so one request is saved all together) ----------------

def count_products(conn):
    return conn.execute("SELECT count(*) FROM products").fetchone()[0]


def get_categories(conn):
    rows = conn.execute("SELECT DISTINCT category FROM products").fetchall()
    return [row[0] for row in rows]


def category_average(conn, category, genders):
    # the average product_vector of one category (only products this user can see), or None if there are none
    row = conn.execute("SELECT avg(product_vector)::real[] FROM products WHERE category = %s AND gender = ANY(%s)",
                       (category, genders)).fetchone()
    if row[0] is None:
        return None
    return np.array(row[0])


def get_product(conn, product_id):
    # (category, product_vector), or None if the product was removed
    row = conn.execute("SELECT category, product_vector::real[] FROM products WHERE product_id = %s", (product_id,)).fetchone()
    if row is None:
        return None
    return row[0], np.array(row[1])


def closest_products(conn, user_vector, category, genders, user_id):
    # the CANDIDATES products of one category closest to the user_vector, that this user was never shown.
    # rows of (product_id, category, style, score). score 1 = same, 0 = unrelated
    return conn.execute("""
        SELECT product_id, category, style, 1 - (product_vector <=> %s::vector)
        FROM products
        WHERE category = %s AND gender = ANY(%s)
          AND product_id NOT IN (SELECT product_id FROM feed_log WHERE user_id = %s)
        ORDER BY product_vector <=> %s::vector
        LIMIT %s
    """, (vector_text(user_vector), category, genders, user_id, vector_text(user_vector), config.CANDIDATES)).fetchall()


def random_products(conn, genders, user_id, skip_ids, followed, how_many):
    # random products of the user's genders, never shown to them, from categories they DON'T follow first.
    # rows of (product_id, category, style)
    return conn.execute("""
        SELECT product_id, category, style FROM products
        WHERE gender = ANY(%s)
          AND product_id NOT IN (SELECT product_id FROM feed_log WHERE user_id = %s)
          AND NOT (product_id = ANY(%s))
        ORDER BY category = ANY(%s), random()
        LIMIT %s
    """, (genders, user_id, skip_ids, followed, how_many)).fetchall()


def save_user(conn, user_id, gender):
    conn.execute("INSERT INTO users VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET gender = %s",
                 (user_id, gender, gender))


def get_gender(conn, user_id):
    # FOR UPDATE: two requests for the same user at the same time wait for each other
    row = conn.execute("SELECT gender FROM users WHERE user_id = %s FOR UPDATE", (user_id,)).fetchone()
    if row is None:
        return None
    return row[0]


def get_user_vectors(conn, user_id):
    # category -> user_vector
    rows = conn.execute("SELECT category, user_vector::real[] FROM user_vectors WHERE user_id = %s", (user_id,)).fetchall()
    user_vectors = {}
    for row in rows:
        user_vectors[row[0]] = np.array(row[1])
    return user_vectors


def save_user_vector(conn, user_id, category, user_vector):
    conn.execute("""
        INSERT INTO user_vectors VALUES (%s, %s, %s::vector)
        ON CONFLICT (user_id, category) DO UPDATE SET user_vector = EXCLUDED.user_vector
    """, (user_id, category, vector_text(user_vector)))


def clear_history(conn, user_id):
    # forget what the user has seen and swiped
    conn.execute("DELETE FROM feed_log WHERE user_id = %s", (user_id,))


def clear_user_vectors(conn, user_id):
    conn.execute("DELETE FROM user_vectors WHERE user_id = %s", (user_id,))


def log_shown(conn, user_id, product_ids):
    # the whole feed in one query (unnest turns the list into rows)
    conn.execute("""
        INSERT INTO feed_log (user_id, product_id)
        SELECT %s, unnest(%s::text[])
        ON CONFLICT DO NOTHING
    """, (user_id, product_ids))


def unknown_products(conn, user_id, product_ids):
    # product_ids that are not in the catalogue AND were never shown to this user: they don't exist anywhere.
    # (a product removed by the 4 AM job is still in feed_log, so it is not "unknown")
    rows = conn.execute("""
        SELECT unnest(%s::text[])
        EXCEPT (SELECT product_id FROM products UNION SELECT product_id FROM feed_log WHERE user_id = %s)
    """, (product_ids, user_id)).fetchall()
    return [row[0] for row in rows]


def log_swipe(conn, user_id, product_id, action):
    # saves one interaction into the log. Works for any product: from our feed, trending, most liked...
    #   - never logged before          -> a new row with the action
    #   - shown in a feed, not swiped  -> the action is filled in
    #   - already swiped               -> nothing changes (the same swipe sent twice counts once)
    # returns True if it was saved (learn from it), False if it was already there
    result = conn.execute("""
        INSERT INTO feed_log (user_id, product_id, action, swiped_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (user_id, product_id) DO UPDATE SET action = EXCLUDED.action, swiped_at = now()
        WHERE feed_log.action IS NULL
    """, (user_id, product_id, action))
    return result.rowcount == 1