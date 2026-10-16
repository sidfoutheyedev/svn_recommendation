# app/main.py
# The API. Start it from the project folder:  uvicorn app.main:app --host 0.0.0.0 --port 8000
# FastAPI checks that every required field is sent with the right type (error 422 if not).

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel

from app import config, database, recommend

database.create_tables()
app = FastAPI()


class Onboarding(BaseModel):
    user_id: str
    gender: str
    categories: list[str]


class Swipe(BaseModel):
    product_id: str
    action: str


class Feed(BaseModel):
    user_id: str
    interactions: list[Swipe] = []


class Reset(BaseModel):
    user_id: str


@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
def database_down(request, error):
    return JSONResponse({"detail": "database unavailable, try again"}, 503)


def get_gender(conn, user_id):
    gender = database.get_gender(conn, user_id)
    if gender is None:
        raise HTTPException(404, "user not found, call /onboarding first")
    return gender


def answer(feed):
    return {"products": feed, "exhausted": len(feed) == 0}


@app.post("/onboarding")
def onboarding(request: Onboarding):
    user_id = request.user_id.strip()
    gender = config.lowercase(request.gender)
    if user_id == "":
        raise HTTPException(400, "user_id is empty")
    if gender not in config.SHOWN_GENDERS:
        raise HTTPException(400, "gender must be male, female or other")

    with database.pool.connection() as conn:
        valid = database.get_categories(conn)
        categories = []
        for category in request.categories:
            category = config.lowercase(category)
            if category not in valid:
                raise HTTPException(400, f"unknown category '{category}', valid: {valid}")
            if category not in categories:
                categories.append(category)

        if recommend.onboard(conn, user_id, gender, categories) == 0:
            raise HTTPException(400, "pick at least one category that has products")
        return answer(recommend.build_feed(conn, user_id, gender))


@app.post("/feed")
def feed(request: Feed):
    swipes = []
    for swipe in request.interactions:
        action = config.lowercase(swipe.action)
        if action not in config.ACTION_WEIGHTS:
            raise HTTPException(400, "action must be like, dislike or add_to_cart")
        swipes.append((swipe.product_id.strip(), action))

    user_id = request.user_id.strip()
    with database.pool.connection() as conn:
        gender = get_gender(conn, user_id)
        unknown = database.unknown_products(conn, user_id, [product_id for product_id, action in swipes])
        if len(unknown) > 0:
            raise HTTPException(400, f"product_id does not exist: {unknown}")
        recommend.learn(conn, user_id, gender, swipes)
        return answer(recommend.build_feed(conn, user_id, gender))


@app.post("/reset")
def reset(request: Reset):
    # forget what the user has seen, keep their user_vectors
    user_id = request.user_id.strip()
    with database.pool.connection() as conn:
        gender = get_gender(conn, user_id)
        database.clear_history(conn, user_id)
        return answer(recommend.build_feed(conn, user_id, gender))


@app.get("/health")
def health():
    with database.pool.connection() as conn:
        return {"status": "ok", "products": database.count_products(conn)}