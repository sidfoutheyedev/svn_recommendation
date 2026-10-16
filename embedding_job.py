# embedding_job.py
# Makes the products table match the backend's product CSV. Run from the project folder:
#     python embedding_job.py
# Run it once by hand (empty database = every product is new), then every day at 4 AM.
# Every product is checked and saved on its own: one bad row or product is skipped and
# written in the report, and never affects the rest of the table.

import io
import os
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import torch
from PIL import Image, ImageFile
from transformers import CLIPModel, CLIPProcessor

from app import config, database

ImageFile.LOAD_TRUNCATED_IMAGES = True           # open images missing their last few bytes (browsers show them fine)
report = []                                      # (product_id, result, reason) for the report file


def stop(reason):
    print("STOPPED:", reason, "- nothing in the database was changed")
    raise SystemExit(1)


def make_product_vector(model, processor, product):
    # returns (product_vector, "") if it worked, or (None, reason) if it didn't
    try:
        response = requests.get(product["primary_image"], timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as error:
        return None, "image could not be downloaded: " + str(error)[:150]

    try:
        inputs = processor(text=[product["embedding_text"]], images=[image], return_tensors="pt",
                           padding=True, truncation=True, max_length=77)
        with torch.no_grad():
            outputs = model(**inputs)
        image_vector = outputs.image_embeds[0].numpy()
        text_vector = outputs.text_embeds[0].numpy()
    except Exception as error:
        return None, "the model failed: " + str(error)[:150]

    product_vector = config.IMAGE_WEIGHT * config.unit_length(image_vector) + config.TEXT_WEIGHT * config.unit_length(text_vector)
    if len(product_vector) != 512 or not np.isfinite(product_vector).all():
        return None, "the model returned broken numbers"
    return config.unit_length(product_vector), ""


# ---------- 1. get the CSV (the backend link, or a file for testing) ----------
print("1. getting the CSV...")
if not config.PRODUCTS_CSV:
    stop("PRODUCTS_CSV is not set in the .env file")
try:
    if config.PRODUCTS_CSV.startswith("http"):
        response = requests.get(config.PRODUCTS_CSV, timeout=120)
        response.raise_for_status()
        content = response.content
    else:
        content = open(config.PRODUCTS_CSV, "rb").read()
    # utf-8-sig: handles files saved by Excel. on_bad_lines="skip": a broken line is left out
    table = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False,
                        encoding="utf-8-sig", encoding_errors="replace", on_bad_lines="skip")
except Exception as error:
    stop("could not get or read the CSV: " + str(error)[:200])

table = table.fillna("")
table.columns = [config.lowercase(name) for name in table.columns]
for column in config.COLUMNS:
    if column not in table.columns:
        stop("the CSV has no '" + column + "' column")
print("   rows in the CSV:", len(table))


# ---------- 2. clean the rows ----------
# each value: extra spaces removed. "null", "NaN", "-" ... become "" (missing).
# a row is kept only if it is active and every value is present and valid.
print("2. cleaning...")
products = {}                                    # product_id -> the clean product
seen_images = set()                              # primary_images already kept

for row in table.to_dict("records"):
    product = {}
    for column in config.COLUMNS:
        value = " ".join(str(row[column]).split())                # remove extra spaces
        if value.lower() in config.EMPTY_VALUES:
            value = ""                                            # missing
        product[column] = value
    for column in ["gender", "category", "style", "is_active"]:
        product[column] = product[column].lower()

    reason = ""
    if product["product_id"] == "":
        reason = "missing product_id"
    elif product["is_active"] not in config.ACTIVE_VALUES:
        report.append((product["product_id"], "inactive", ""))
        continue
    else:
        missing = [column for column in config.COLUMNS if product[column] == ""]
        if len(missing) > 0:
            reason = "missing: " + ", ".join(missing)
        elif product["gender"] not in config.ALLOWED_GENDERS:
            reason = "gender not allowed: " + product["gender"]
        elif product["style"] not in config.ALLOWED_STYLES:
            reason = "style not allowed: " + product["style"]
        elif product["category"] in config.ALLOWED_STYLES:
            reason = "category is a style name: " + product["category"]
        elif not product["primary_image"].startswith(("http://", "https://")):
            reason = "primary_image is not a web link"
        elif product["product_id"] in products:
            reason = "duplicate product_id"
        elif product["primary_image"] in seen_images:
            reason = "duplicate primary_image"

    if reason != "":
        report.append((product["product_id"], "skipped", reason))
        continue
    product["gender"] = config.ALLOWED_GENDERS[product["gender"]]     # "Men" -> "male"
    products[product["product_id"]] = product
    seen_images.add(product["primary_image"])
    
print("   clean products:", len(products))
if len(products) == 0:
    stop("no clean products in the CSV")         # an empty or broken CSV must not empty the table


# ---------- 3. compare with the database ----------
print("3. comparing with the database...")
try:
    database.create_tables()
    in_database = database.get_products()
except Exception as error:
    stop("could not use the database: " + str(error)[:200])

to_embed = []            # new, or picture/text changed
fields_only = []         # only gender/category/style changed: keep the product_vector
for product_id, product in products.items():
    saved = in_database.get(product_id)          # the same product in the database, or None if it's new
    if saved is None:
        product["result"] = "added"
        to_embed.append(product)
    elif product["primary_image"] != saved["primary_image"] or product["embedding_text"] != saved["embedding_text"]:
        product["result"] = "re-embedded"
        to_embed.append(product)
    elif product["gender"] != saved["gender"] or product["category"] != saved["category"] or product["style"] != saved["style"]:
        fields_only.append(product)

to_remove = [product_id for product_id in in_database if product_id not in products]
print("   new or changed:", len(to_embed), "| fields only:", len(fields_only), "| to remove:", len(to_remove))


# ---------- 4. make product_vectors and save, one product at a time ----------
if len(to_embed) > 0:
    print("4. making product_vectors...")
    if not os.path.exists(config.MODEL_FOLDER):
        stop("model not found, run first: python download_model.py")
    model = CLIPModel.from_pretrained(config.MODEL_FOLDER)
    processor = CLIPProcessor.from_pretrained(config.MODEL_FOLDER)

    for number, i in enumerate(to_embed, start=1):
        product_vector, reason = make_product_vector(model, processor, i)
        if product_vector is None:
            report.append((i["product_id"], "failed", reason))
            continue
        try:
            database.save_product(i, product_vector)
            report.append((i["product_id"], i["result"], ""))
        except Exception as error:
            report.append((i["product_id"], "failed", "database: " + str(error)[:150]))
        if number % 50 == 0:
            print("  ", number, "/", len(to_embed))


# ---------- 5. update fields, remove old products ----------
print("5. updating and removing...")
for i in fields_only:
    try:
        database.update_fields(i)
        report.append((i["product_id"], "fields updated", ""))
    except Exception as error:
        report.append((i["product_id"], "failed", "database: " + str(error)[:150]))

for i in to_remove:
    try:
        database.delete_product(i)
        report.append((i, "removed", ""))
    except Exception as error:
        report.append((i, "failed", "database: " + str(error)[:150]))


# ---------- 6. report ----------
report = pd.DataFrame(report, columns=["product_id", "result", "reason"])
os.makedirs("reports", exist_ok=True)
file_name = "reports/embedding_job_" + datetime.now().strftime("%Y-%m-%d_%H-%M") + ".csv"
report.to_csv(file_name, index=False)

print("\nDONE")
for result, count in report["result"].value_counts().items():
    print(f"   {result}: {count}")
print("   products before:", len(in_database))
print("   details:", file_name)