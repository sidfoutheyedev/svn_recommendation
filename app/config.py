# app/config.py
# Every setting in one place, plus 2 small helpers used by several files.

import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL")
PRODUCTS_CSV = os.getenv("PRODUCTS_CSV")         # the backend link, or a file path for testing

MODEL_NAME = "patrickjohncyh/fashion-clip"
MODEL_FOLDER = "models/fashion-clip"
IMAGE_WEIGHT = 0.7                               # product_vector = 70% picture + 30% text
TEXT_WEIGHT = 0.3

# the product CSV. Categories come from the CSV, so the client can add new ones any time.
COLUMNS = ["product_id", "gender", "category", "style", "is_active", "primary_image", "embedding_text"]
ACTIVE_VALUES = ["true", "1", "yes"]
EMPTY_VALUES = ["", "null", "none", "nan", "n/a", "na", "undefined", "-"]   # all of these mean "missing"
ALLOWED_GENDERS = {"male": "male", "men": "male", "female": "female",
                   "women": "female", "other": "other", "unisex": "other"}
ALLOWED_STYLES = ["topwear", "bottomwear", "outerwear", "dresses", "innerwear", "footwear", "sets & co-ords", "accessories"]

PERSONALISED = 16                                # cards picked by the user_vectors
WILDCARDS = 4                                    # random cards from other categories/ sum of these should always be 20 for feed of 20 stacks

MAX_PER_STYLE = 6                                # max cards of one style among the 16
MAX_PER_CATEGORY = 6                             # max cards of one category among the 16
CANDIDATES = 100                                 # closest products fetched per category before the style limit, should be greater than personalised

ACTION_WEIGHTS = {"like": 0.15, "dislike": -0.08, "add_to_cart": 0.25}    # how far one swipe moves the user_vector / change only the numbers not the names
SHOWN_GENDERS = {"male": ["male", "other"], "female": ["female", "other"], "other": ["male", "female", "other"]}


def lowercase(text):
    # "  Old   MONEY " -> "old money"
    return " ".join(str(text).split()).lower()


def unit_length(vector):
    # vectors of length 1 can be compared fairly
    return vector / np.linalg.norm(vector)