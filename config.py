import os
from dotenv import load_dotenv

load_dotenv()

DATAGOLF_API_KEY = os.getenv("DATAGOLF_API_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "./golf.db")
FLASK_ENV = os.getenv("FLASK_ENV", "development")

DATAGOLF_BASE_URL = "https://feeds.datagolf.com"
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
