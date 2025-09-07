# extensions.py
from pymongo import MongoClient, server_api
from flask import current_app
import os

# Initialize MongoDB connection
mongo_client = MongoClient(
    os.getenv("MONGO_URI"),
    server_api=server_api.ServerApi("1"),  # Note the server_api prefix
    connectTimeoutMS=30000,
    maxPoolSize=50,
)

def get_db():
    return mongo_client.get_database("kredi_app")