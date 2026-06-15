print("BITABLE_APP_TOKEN =", BITABLE_APP_TOKEN)
print("MAIN_TABLE_ID =", MAIN_TABLE_ID)
print("SKU_TABLE_ID =", SKU_TABLE_ID)
print("TARGET_URL =", TARGET_TABLE_URL)

import os
import re
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs
from config import *

TARGET_TABLE_URL = os.getenv("TARGET_TABLE_URL")
START_DATE = os.getenv("START_DATE")
END_DATE = os.getenv("END_DATE")

BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def request_json(method, url, headers=None, params=None, json=None):
    res = requests.request(method, url, headers=headers, params=params, json=json, timeout=30)
    if res.status_code >= 400:
        raise Exception(f"HTTP {res.status_code}: {res.text[:1000]}")
    return res.json()


def parse_target_table_url(url):
    app_match = re.search(r"/base/([^/?]+)", url)
    if not app_match:
        raise Exception("无法从飞书链接中解析 base app_token")

    app_token = app_match.group(1)
    query = parse_qs(urlparse(url).query)
    table_id = query.get("table", [None])[0]

    if not table_id:
        raise Exception("无法从飞书链接中解析 table_id")

    return app_token, table_id


def parse_date_range(start_date, end_date):
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=BEIJING_TZ)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=BEIJING_TZ) + timedelta(days=1)
    return start_dt.isoformat(), end_dt.isoformat()


def get_feishu_token():
    data = request_json(
        "POST",
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": FEISHU_APP_ID,
            "app_secret": FEISHU_APP_SECRET
        }
    )

    if data.get("code") != 0:
        raise Exception(f"获取飞书Token失败: {data}")

    return data["tenant_access_token"]


def feishu_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def get_all_records(token, app_token, table_id):
    all_items = []
    page_token = None

    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        data = request_json("GET", url, headers=feishu_headers(token), params=params)

        if data.get("code") != 0:
            raise Exception(f"读取飞书表失败: {data}")

        page_data = data.get("data", {})
        all_items.extend(page_data.get("items", []))

        if not page_data.get("has_more"):
            break

        page_token = page_data.get("page_token")

    return all_items


def create_record(token, app_token, table_id, fields):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

    data = request_json(
        "POST",
        url,
        headers=feishu_headers(token),
        json={"fields": fields}
    )

    if data.get("code") != 0:
        raise Exception(f"写入飞书失败: {data}")

    return data


def get_shopify_orders(start_iso, end_iso):
    url = f"https://{SHOPIFY_STORE}/admin/api/2025-01/orders.json"

    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN
    }

    data = request_json(
        "GET",
        url,
        headers=headers,
        params={
            "status": "any",
            "created_at_min": start_iso,
            "created_at_max": end_iso,
            "limit": 250,
            "order": "created_at asc"
        }
    )

    return data.get("orders", [])


def build_kol_code_map(records):
    result = {}

    for record in records:
        fields = record.get("fields", {})
        code = fields.get("折扣码")

        if code:
            result[str(code).strip()] = fields

    print(f"KOL折扣码数量: {len(result)}")
    return result


def build_sku_map(records):
    result = {}

    for record in records:
        fields = record.get("fields", {})
        sku = fields.get("SKU")

        if sku:
            result[str(sku).strip()] = {
                "product": fields.get("产品"),
                "category": fields.get("大类")
            }

    print(f"SKU映射数量: {len(result)}")
    return result


def build_existing_order_names(records):
    result = set()

    for record in records:
        fields = record.get("fields", {})
        name = fields.get("Name")

        if name:
            result.add(str(name).strip())

    print(f"目标表已存在订单数量: {len(result)}")
    return result


def get_discount_code(order):
    discounts = order.get("discount_codes", [])

    if not discounts:
        return None

    return discounts[0].get("code")


def get_valid_items(order):
    items = []

    for item in order.get("line_items", []):
        sku = item.get("sku")
        title = item.get("title") or item.get("name")

        if not sku:
            continue

        sku = str(sku).strip()

        if sku in INSURANCE_SKUS:
            continue

        items.append({
            "sku": sku,
            "title": title
        })

    return items


def build_remark(items, sku_map):
    remarks = []

    for item in items:
        sku = item["sku"]
        title = item["title"]

        sku_info = sku_map.get(sku)

        if sku_info and sku_info.get("category") in ["高盖", "卷帘门"] and sku_info.get("product"):
            remarks.append(str(sku_info["product"]))
        else:
            remarks.append(str(title))

    return "\n".join(remarks)


def get_billing_province(order):
    billing = order.get("billing_address") or {}
    return billing.get("province") or ""


def format_date(created_at):
    return created_at[:10] if created_at else ""


def main():
    print("开始同步 Shopify KOL 订单")

    target_app_token, target_table_id = parse_target_table_url(TARGET_TABLE_URL)
    start_iso, end_iso = parse_date_range(START_DATE, END_DATE)

    print(f"目标表: {target_table_id}")
    print(f"拉取时间: {start_iso} 到 {end_iso}")

    token = get_feishu_token()

    kol_records = get_all_records(token, BITABLE_APP_TOKEN, MAIN_TABLE_ID)
    sku_records = get_all_records(token, BITABLE_APP_TOKEN, SKU_TABLE_ID)
    target_records = get_all_records(token, target_app_token, target_table_id)

    kol_code_map = build_kol_code_map(kol_records)
    sku_map = build_sku_map(sku_records)
    existing_orders = build_existing_order_names(target_records)

    orders = get_shopify_orders(start_iso, end_iso)

    print(f"Shopify订单数量: {len(orders)}")

    created = 0
    skipped_no_code = 0
    skipped_code_not_found = 0
    skipped_duplicate = 0
    skipped_no_sku = 0

    for order in orders:
        order_name = order.get("name")

        if order_name in existing_orders:
            skipped_duplicate += 1
            continue

        code = get_discount_code(order)

        if not code:
            skipped_no_code += 1
            continue

        code = str(code).strip()

        if code not in kol_code_map:
            skipped_code_not_found += 1
            continue

        items = get_valid_items(order)

        if not items:
            skipped_no_sku += 1
            continue

        sku_list = [item["sku"] for item in items]
        remark = build_remark(items, sku_map)

        fields = {
            "Name": order_name,
            "Paid at": order.get("created_at"),
            "Total": order.get("current_total_price"),
            "Discount Code": code,
            "Lineitem sku": ",".join(sku_list),
            "Billing Province Name": get_billing_province(order),
            "日期": format_date(order.get("created_at")),
            "备注": remark
        }

        create_record(token, target_app_token, target_table_id, fields)

        existing_orders.add(order_name)
        created += 1

        print(f"写入成功: {order_name} | {code} | {','.join(sku_list)}")

    print("同步完成")
    print(f"新增: {created}")
    print(f"跳过-无折扣码: {skipped_no_code}")
    print(f"跳过-折扣码不在KOL表: {skipped_code_not_found}")
    print(f"跳过-重复订单: {skipped_duplicate}")
    print(f"跳过-无有效SKU: {skipped_no_sku}")


if __name__ == "__main__":
    main()
