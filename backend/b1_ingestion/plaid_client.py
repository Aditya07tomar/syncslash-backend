import os
import datetime
from dotenv import load_dotenv
from plaid.api import plaid_api
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid import Configuration, ApiClient, Environment

load_dotenv()

def get_plaid_client():
    """
    Creates and returns a configured Plaid API client.
    Uses sandbox environment — no real bank data.
    """
    config = Configuration(
        host=Environment.Sandbox,
        api_key={
            "clientId": os.getenv("PLAID_CLIENT_ID"),
            "secret":   os.getenv("PLAID_SECRET"),
        }
    )
    return plaid_api.PlaidApi(ApiClient(config))


def create_sandbox_token():
    """
    Plaid sandbox needs a fake 'public token' first.
    This simulates what happens when a user connects
    their bank through the Plaid UI in the real app.
    We use 'ins_109508' which is a Chase sandbox bank
    pre-loaded with Netflix, Spotify, Amazon transactions.
    """
    client = get_plaid_client()
    req = SandboxPublicTokenCreateRequest(
        institution_id="ins_109508",
        initial_products=[Products("transactions")]
    )
    response = client.sandbox_public_token_create(req)
    return response.public_token


def exchange_for_access_token(public_token: str):
    """
    Exchange the temporary public token for a permanent
    access token. This access token is what we store in
    the Users table (plaid_token column) and reuse every
    time we sync transactions for that user.
    """
    client = get_plaid_client()
    req = ItemPublicTokenExchangeRequest(public_token=public_token)
    response = client.item_public_token_exchange(req)
    return response.access_token


def fetch_transactions(access_token: str, days_back: int = 90):
    """
    Pulls transactions for the last N days.
    Returns a list of Plaid Transaction objects.
    The sandbox bank has realistic recurring charges
    already built in — Netflix on the 1st, Spotify
    on the 15th, etc.
    """
    client = get_plaid_client()
    end_date   = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days_back)

    req = TransactionsGetRequest(
        access_token=access_token,
        start_date=start_date,
        end_date=end_date,
        options=TransactionsGetRequestOptions(count=500)
    )
    response = client.transactions_get(req)
    return response.transactions