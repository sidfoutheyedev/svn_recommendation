# app/recommend.py
# The recommendation logic: onboard a user, learn from swipes, build a feed.
# A user_vector is 512 numbers, like a product_vector. Products close to it should be liked.

import random

from app import config, database


def onboard(conn, user_id, gender, categories):
    # starting user_vector for each category = the average product_vector of that category.
    # returns how many user_vectors were made (0 = none of the categories had products)
    database.save_user(conn, user_id, gender)
    database.clear_history(conn, user_id)                      # onboarding again starts fresh
    database.clear_user_vectors(conn, user_id)
    made = 0
    for category in categories:
        average = database.category_average(conn, category, config.SHOWN_GENDERS[gender])
        if average is not None:
            database.save_user_vector(conn, user_id, category, config.unit_length(average))
            made = made + 1
    return made


def learn(conn, user_id, gender, swipes):
    # swipes: a list of (product_id, action)
    user_vectors = database.get_user_vectors(conn, user_id)
    changed = set()                            # categories whose user_vector moved
    for product_id, action in swipes:
        if not database.log_swipe(conn, user_id, product_id, action):
            continue                           # never shown, or already counted
        product = database.get_product(conn, product_id)
        if product is None:
            continue                           # removed from the catalogue since
        category, product_vector = product

        if category not in user_vectors:       # a wildcard
            if action == "dislike":
                continue
            average = database.category_average(conn, category, config.SHOWN_GENDERS[gender])
            if average is None:
                continue
            user_vectors[category] = average   # they liked a wildcard: they now follow its category

        # move the user_vector a little towards (like) or away from (dislike) the product
        moved = user_vectors[category] + config.ACTION_WEIGHTS[action] * product_vector
        user_vectors[category] = config.unit_length(moved)
        changed.add(category)

    for category in changed:                   # save each changed user_vector once, at the end
        database.save_user_vector(conn, user_id, category, user_vectors[category])


def build_feed(conn, user_id, gender):
    # returns up to 20 cards: 16 personalised + 4 wildcards. An empty list means the user has seen everything.
    genders = config.SHOWN_GENDERS[gender]
    user_vectors = database.get_user_vectors(conn, user_id)

    # 1. the closest unseen products of every category they follow, best score first
    closest = []                               # (product_id, category, style, score)
    for category in user_vectors:
        closest = closest + database.closest_products(conn, user_vectors[category], category, genders, user_id)
    closest.sort(key=lambda row: row[3], reverse=True)

    # 2. the 16 best, with at most 6 of one style and at most 6 of one category
    feed = []
    style_count = {}
    category_count = {}
    for product_id, category, style, score in closest:
        if len(feed) == config.PERSONALISED:
            break
        if style_count.get(style, 0) == config.MAX_PER_STYLE:
            continue
        if category_count.get(category, 0) == config.MAX_PER_CATEGORY:
            continue
        feed.append({"product_id": product_id, "category": category, "style": style,
                     "source": "personalised", "score": round(score, 4)})
        style_count[style] = style_count.get(style, 0) + 1
        category_count[category] = category_count.get(category, 0) + 1

    # 3. if the limits left empty places, fill them with the next best products, so there are always 16
    feed_ids = [card["product_id"] for card in feed]
    for product_id, category, style, score in closest:
        if len(feed) == config.PERSONALISED:
            break
        if product_id not in feed_ids:
            feed.append({"product_id": product_id, "category": category, "style": style,
                         "source": "personalised", "score": round(score, 4)})
            feed_ids.append(product_id)

    # 4. exactly 4 wildcards: random products of their genders, from categories they don't follow first
    for product_id, category, style in database.random_products(conn, genders, user_id, feed_ids,
                                                                 list(user_vectors), config.WILDCARDS):
        feed.append({"product_id": product_id, "category": category, "style": style,
                     "source": "wildcard", "score": None})

    # 5. mix the cards, and write them into the interaction log
    random.shuffle(feed)
    database.log_shown(conn, user_id, [card["product_id"] for card in feed])
    return feed