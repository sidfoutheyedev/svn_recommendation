# check_vectors.py
# Proof that the vector database works:  python check_vectors.py SOULED_279325
# Prints the 5 products most similar to that product (the first line is the product itself).

import sys

from app import database

product_id = sys.argv[1]
rows = database.most_similar(product_id, 6)
if len(rows) == 0:
    print(product_id, "is not in the database")
for found_id, category, style, similarity in rows:
    print(round(similarity, 3), found_id, category, style)
