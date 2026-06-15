import requests
import os

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")

url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

response = requests.post(
    url,
    json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
)

print("Status:", response.status_code)
print(response.text[:1000])
