import requests
import os

SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_TOKEN = os.getenv("SHOPIFY_TOKEN")

url = f"https://{SHOPIFY_STORE}/admin/api/2025-01/orders.json"

headers = {
    "X-Shopify-Access-Token": SHOPIFY_TOKEN
}

response = requests.get(
    url,
    headers=headers,
    params={
        "status": "any",
        "limit": 5
    }
)

print("Store:", SHOPIFY_STORE)
print("Status:", response.status_code)
print(response.text[:1000])
