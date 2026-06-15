import requests
from datetime import datetime, timedelta, timezone
from config import *


# =====================
# 基础请求
# =====================

def request_json(method, url, headers=None, params=None, json=None):
    res = requests.request(
        method,
        url,
        headers=headers,
        params=params,
        json=json,
        timeout=30
    )

    try:
        data = res.json()
    except Exception:
        data = {}

    if res.status_code >= 400:
        raise Exception(f"HTTP {res.status_code}: {res.text[:1000]}")

    return data


# =====================
# 飞书
# =====================

def get_feishu_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

    data = request_json(
        "POST",
        url,
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


def get_all_records(token, table_id):
    all_items = []
    page_token = None

    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/records"

        params = {
            "page_size": 500
        }

        if page_token:
            params["page_token"] = page_token

        data = request_json(
            "GET",
            url,
            headers=feishu_headers(token),
            params=params
        )

        if data.get("code") != 0:
            raise Exception(f"读取飞书表失败: {data}")

        page_data = data.get("data", {})
        all_items.extend(page_data.get("items", []))

        if not page_data.get("has_more"):
            break

        page_token = page_data.get("page_token")

    return all_items


def get_all_tables(token):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables"

    data = request_json(
        "GET",
        url,
        headers=feishu_headers(token)
    )

    if data.get("code") != 0:
        raise Exception(f"读取飞书表列表失败: {data}")

    return data.get("data", {}).get("items", [])


def get_current_month_table_id(token):
    month_name = f"{datetime.now().month}月出单"

    tables = get_all_tables(token)

    for table in tables:
        if table.get("name") == month_name:
            print(f"找到当月出单表: {month_name}")
            return table["table_id"]

    raise Exception(f"没有找到当月出单表: {month_name}。请先在飞书创建该表。")


def create_record(token, table_id, fields):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/records"

    data = request_json(
        "POST",
        url,
        headers=feishu_headers(token),
        json={
            "fields": fields
        }
    )

    if data.get("code") != 0:
        raise Exception(f"写入飞书失败: {data}")

    return data


# =====================
# Shopify
# =====================

def get_shopify_orders_last_48h():
    since = (
        datetime.now(timezone.utc) - timedelta(hours=48)
    ).isoformat()

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
            "created_at_min": since,
            "limit": 250
        }
    )

    return data.get("orders", [])


# =====================
# 数据构建
# =====================

def build_kol_code_map(records):
    result = {}

    for record in records:
        fields = record.get("fields", {})

        code = fields.get("折扣码")

        if not code:
            continue

        code = str(code).strip()

        if code:
            result[code] = fields

    print(f"KOL折扣码数量: {len(result)}")
    return result


def build_sku_map(records):
    result = {}

    for record in records:
        fields = record.get("fields", {})

        sku = fields.get("SKU")

        if not sku:
            continue

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

    print(f"当月已存在订单数量: {len(result)}")
    return result


def get_order_discount_code(order):
    discounts = order.get("discount_codes", [])

    if not discounts:
        return None

    first = discounts[0]

    return first.get("code")


def get_valid_line_items(order):
    valid_items = []

    for item in order.get("line_items", []):
        sku = item.get("sku")
        title = item.get("title") or item.get("name")

        if not sku:
            continue

        sku = str(sku).strip()

        if sku in INSURANCE_SKUS:
            continue

        valid_items.append({
            "sku": sku,
            "title": title
        })

    return valid_items


def build_remark(valid_items, sku_map):
    remarks = []

    for item in valid_items:
        sku = item["sku"]
        title = item["title"]

        sku_info = sku_map.get(sku)

        if sku_info:
            category = sku_info.get("category")
            product = sku_info.get("product")

            if category in ["高盖", "卷帘门"] and product:
                remarks.append(str(product))
            else:
                remarks.append(str(title))
        else:
            remarks.append(str(title))

    return "\n".join(remarks)


def get_billing_province(order):
    billing = order.get("billing_address") or {}
    return billing.get("province") or ""


def format_date(created_at):
    if not created_at:
        return ""

    return created_at[:10]


# =====================
# 主流程
# =====================

def main():
    print("开始同步 Shopify KOL 订单")

    token = get_feishu_token()

    target_table_id = get_current_month_table_id(token)

    kol_records = get_all_records(token, MAIN_TABLE_ID)
    sku_records = get_all_records(token, SKU_TABLE_ID)
    target_records = get_all_records(token, target_table_id)

    kol_code_map = build_kol_code_map(kol_records)
    sku_map = build_sku_map(sku_records)
    existing_order_names = build_existing_order_names(target_records)

    orders = get_shopify_orders_last_48h()

    print(f"Shopify近48小时订单数量: {len(orders)}")

    created_count = 0
    skipped_no_code = 0
    skipped_code_not_found = 0
    skipped_duplicate = 0
    skipped_no_valid_sku = 0

    for order in orders:
        order_name = order.get("name")

        if order_name in existing_order_names:
            skipped_duplicate += 1
            continue

        code = get_order_discount_code(order)

        if not code:
            skipped_no_code += 1
            continue

        code = str(code).strip()

        if code not in kol_code_map:
            skipped_code_not_found += 1
            continue

        valid_items = get_valid_line_items(order)

        if not valid_items:
            skipped_no_valid_sku += 1
            continue

        sku_list = [item["sku"] for item in valid_items]
        remark = build_remark(valid_items, sku_map)

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

        create_record(token, target_table_id, fields)

        existing_order_names.add(order_name)
        created_count += 1

        print(f"写入成功: {order_name} | {code} | {','.join(sku_list)}")

    print("同步完成")
    print(f"新增: {created_count}")
    print(f"跳过-无折扣码: {skipped_no_code}")
    print(f"跳过-折扣码不在KOL表: {skipped_code_not_found}")
    print(f"跳过-重复订单: {skipped_duplicate}")
    print(f"跳过-无有效SKU: {skipped_no_valid_sku}")


if __name__ == "__main__":
    main()
