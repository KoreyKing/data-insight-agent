from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

SEED = 20260526
START_DATE = date(2026, 3, 23)
DAYS = 56
CURRENT_START = date(2026, 5, 11)
CURRENT_END = date(2026, 5, 17)
PREVIOUS_START = date(2026, 5, 4)
PREVIOUS_END = date(2026, 5, 10)
PERIOD2_START = CURRENT_END + timedelta(days=1)
PERIOD2_END = PERIOD2_START + timedelta(days=6)
PERIOD2_SEED = 20260527
VALID_ORDER_STATUSES = {"completed", "partial_refund"}
COLUMNS = [
    "order_id",
    "order_date",
    "store_id",
    "store_name",
    "product_id",
    "product_name",
    "category_l1",
    "category_l2",
    "channel",
    "customer_type",
    "quantity",
    "gross_sales_amount",
    "discount_amount",
    "net_sales_amount",
    "order_status",
    "refund_amount",
    "unit_cost",
]


@dataclass(frozen=True)
class Store:
    store_id: str
    store_name: str
    region: str
    city: str
    store_type: str
    base_weight: float


@dataclass(frozen=True)
class Product:
    product_id: str
    product_name: str
    category_l1: str
    category_l2: str
    list_price: float
    unit_cost: float


STORES = [
    Store("SH001", "上海徐汇旗舰店", "华东", "上海", "旗舰店", 1.35),
    Store("SH002", "上海静安店", "华东", "上海", "标准店", 1.00),
    Store("HZ001", "杭州湖滨店", "华东", "杭州", "标准店", 0.95),
    Store("NJ001", "南京新街口店", "华东", "南京", "标准店", 0.85),
    Store("GZ001", "广州天河店", "华南", "广州", "旗舰店", 1.08),
    Store("GZ002", "广州番禺店", "华南", "广州", "标准店", 0.75),
    Store("SZ001", "深圳南山店", "华南", "深圳", "标准店", 0.96),
    Store("SZ002", "深圳福田店", "华南", "深圳", "快闪店", 0.62),
    Store("BJ001", "北京国贸店", "华北", "北京", "旗舰店", 1.05),
    Store("BJ002", "北京朝阳店", "华北", "北京", "标准店", 0.90),
    Store("TJ001", "天津和平店", "华北", "天津", "标准店", 0.64),
    Store("CD001", "成都太古里店", "西南", "成都", "旗舰店", 0.92),
    Store("CQ001", "重庆观音桥店", "西南", "重庆", "标准店", 0.72),
    Store("KM001", "昆明南屏店", "西南", "昆明", "快闪店", 0.50),
]

CATEGORY_DEFINITIONS = {
    "服装": [
        ("T恤", ["基础T恤", "针织短袖", "印花T恤"]),
        ("衬衫", ["亚麻衬衫", "通勤衬衫", "牛津纺衬衫"]),
        ("外套", ["轻薄外套", "防晒外套", "短款夹克"]),
        ("连衣裙", ["法式连衣裙", "通勤连衣裙", "碎花连衣裙"]),
    ],
    "配饰": [
        ("包袋", ["真皮托特包", "尼龙斜挎包", "通勤双肩包"]),
        ("丝巾", ["丝巾礼盒", "印花方巾", "轻薄围巾"]),
        ("眼镜", ["太阳镜", "防蓝光眼镜", "复古镜框"]),
        ("帽子", ["棒球帽", "渔夫帽", "贝雷帽"]),
    ],
    "童装": [
        ("T恤", ["童装T恤", "亲子短袖", "卡通T恤"]),
        ("连衣裙", ["童装连衣裙", "碎花童裙", "学院风童裙"]),
        ("外套", ["儿童防晒外套", "儿童薄夹克", "儿童运动外套"]),
        ("裤装", ["儿童休闲裤", "儿童牛仔裤", "儿童短裤"]),
    ],
    "鞋履": [
        ("运动鞋", ["轻量运动鞋", "城市跑鞋", "复古运动鞋"]),
        ("皮鞋", ["通勤乐福鞋", "软底皮鞋", "复古德比鞋"]),
        ("凉鞋", ["夏季凉鞋", "厚底凉鞋", "儿童凉鞋"]),
        ("靴子", ["短筒靴", "切尔西靴", "儿童雨靴"]),
    ],
}

BASE_PRICES = {
    "服装": [129, 169, 199, 259, 329, 399],
    "配饰": [89, 129, 169, 239, 299, 399],
    "童装": [79, 99, 129, 169, 199, 239],
    "鞋履": [199, 259, 329, 459, 599, 699],
}


def build_products(rng: random.Random) -> list[Product]:
    products: list[Product] = []
    product_index = 1
    for category, groups in CATEGORY_DEFINITIONS.items():
        for category_l2, names in groups:
            for name in names:
                for variant in ["M", "L"]:
                    price = float(rng.choice(BASE_PRICES[category]))
                    cost_rate = rng.uniform(0.42, 0.58)
                    products.append(
                        Product(
                            product_id=f"SKU-{product_index:04d}",
                            product_name=f"{name} {variant}",
                            category_l1=category,
                            category_l2=category_l2,
                            list_price=price,
                            unit_cost=round(price * cost_rate, 2),
                        )
                    )
                    product_index += 1
    return products


def generate_sample_data(
    output_dir: Path | str | None = None,
    qa_path: Path | str | None = None,
) -> dict[str, str]:
    backend_dir = Path(__file__).resolve().parents[1]
    output = Path(output_dir) if output_dir else backend_dir / "app" / "sample_data"
    output.mkdir(parents=True, exist_ok=True)
    qa_output = Path(qa_path) if qa_path else backend_dir / ".sample-data-qa.json"

    dataframe, _products = build_period1_dataframe()
    csv_path = output / "retail_sales_orders.csv"
    xlsx_path = output / "retail_sales_orders.xlsx"
    dataframe.to_csv(csv_path, index=False, encoding="utf-8")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="sales_orders", index=False)

    qa = build_qa_summary(
        dataframe,
        fixture_id="period1",
        current_start=CURRENT_START,
        current_end=CURRENT_END,
        previous_start=PREVIOUS_START,
        previous_end=PREVIOUS_END,
    )
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"csv_path": str(csv_path), "xlsx_path": str(xlsx_path), "qa_path": str(qa_output)}


def build_period1_dataframe() -> tuple[pd.DataFrame, list[Product]]:
    rng = random.Random(SEED)
    products = build_products(rng)
    rows = generate_rows(START_DATE, DAYS, rng, products, week_offset=0)
    return pd.DataFrame(rows, columns=COLUMNS), products


def generate_rows(
    start_date: date,
    days: int,
    rng: random.Random,
    products: list[Product],
    *,
    week_offset: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day_offset in range(days):
        current_date = start_date + timedelta(days=day_offset)
        week_index = week_offset + day_offset // 7
        daily_orders = daily_order_count(current_date, week_index, rng)
        for order_number in range(1, daily_orders + 1):
            store = choose_store(current_date, week_index, rng)
            product = choose_product(current_date, rng, products)
            channel = choose_channel(current_date, rng)
            quantity = choose_quantity(channel, rng)
            gross = product.list_price * quantity
            discount = round(gross * discount_rate(current_date, channel, rng), 2)
            status, refund = choose_status_and_refund(current_date, product, gross, discount, rng)
            net_sales = round(gross - discount - refund, 2)
            customer_type = choose_customer_type(week_index, rng)

            rows.append(
                {
                    "order_id": f"O{current_date:%Y%m%d}-{order_number:04d}",
                    "order_date": current_date.isoformat(),
                    "store_id": store.store_id,
                    "store_name": store.store_name,
                    "product_id": product.product_id,
                    "product_name": product.product_name,
                    "category_l1": product.category_l1,
                    "category_l2": product.category_l2,
                    "channel": channel,
                    "customer_type": customer_type,
                    "quantity": quantity,
                    "gross_sales_amount": round(gross, 2),
                    "discount_amount": discount,
                    "net_sales_amount": net_sales,
                    "order_status": status,
                    "refund_amount": round(refund, 2),
                    "unit_cost": product.unit_cost,
                }
            )
    return rows


def generate_period2_fixture(output_dir: Path | str | None = None) -> dict[str, str]:
    backend_dir = Path(__file__).resolve().parents[1]
    output = Path(output_dir) if output_dir else backend_dir / "eval" / "fixtures"
    output.mkdir(parents=True, exist_ok=True)

    period1, products = build_period1_dataframe()
    extension_rng = random.Random(PERIOD2_SEED)
    extension_rows = generate_rows(
        PERIOD2_START,
        7,
        extension_rng,
        products,
        week_offset=DAYS // 7,
    )
    extension = pd.DataFrame(extension_rows, columns=COLUMNS)
    dataframe = pd.concat([period1, extension], ignore_index=True)

    csv_path = output / "retail_sales_orders_period2.csv"
    qa_output = output / "retail_sales_orders_period2.qa.json"
    dataframe.to_csv(csv_path, index=False, encoding="utf-8")
    qa = build_qa_summary(
        dataframe,
        fixture_id="period2",
        current_start=PERIOD2_START,
        current_end=PERIOD2_END,
        previous_start=CURRENT_START,
        previous_end=CURRENT_END,
    )
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"csv_path": str(csv_path), "qa_path": str(qa_output)}


def generate_zh_header_fixture(output_dir: Path | str | None = None) -> dict[str, str]:
    """capture 用例数据（architecture.md §7 v0.13）：period1 数据改写为各列 display_name 表头。

    中文表头才对别名编辑敏感（英文 canonical 表头恒为自身别名）；KPI 基准与 period1 同值。
    """
    backend_dir = Path(__file__).resolve().parents[1]
    output = Path(output_dir) if output_dir else backend_dir / "eval" / "fixtures"
    output.mkdir(parents=True, exist_ok=True)

    period1, _products = build_period1_dataframe()
    display_names = builtin_display_names()
    missing = [column for column in COLUMNS if column not in display_names]
    if missing:
        raise ValueError(f"内置口径缺少字段显示名：{', '.join(missing)}")

    csv_path = output / "retail_sales_orders_zh.csv"
    qa_output = output / "retail_sales_orders_zh.qa.json"
    period1.rename(columns=display_names).to_csv(csv_path, index=False, encoding="utf-8")
    qa = build_qa_summary(period1, fixture_id="period1")
    qa["fixture_id"] = "period1-zh"
    qa["header_variant"] = "display_name"
    qa_output.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"csv_path": str(csv_path), "qa_path": str(qa_output)}


def builtin_display_names() -> dict[str, str]:
    pack_path = (
        Path(__file__).resolve().parents[1] / "app" / "context_packs" / "retail_operations_v1.json"
    )
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    columns = pack["data_dictionary"]["tables"][0]["columns"]
    return {column["name"]: column["display_name"] for column in columns}


def daily_order_count(current_date: date, week_index: int, rng: random.Random) -> int:
    base = 128 + week_index * 4 + rng.randint(-8, 10)
    if current_date.weekday() >= 5:
        base = int(base * rng.uniform(1.55, 1.75))
    return max(base, 80)


def choose_store(current_date: date, week_index: int, rng: random.Random) -> Store:
    weights = []
    for store in STORES:
        weight = store.base_weight
        if store.region == "华南":
            weight *= 1 + week_index * 0.045
        if store.store_id == "SH001" and PREVIOUS_START <= current_date <= PREVIOUS_END:
            weight *= 1.45
        if store.store_id == "SH001" and CURRENT_START <= current_date <= CURRENT_END:
            weight *= 1.03
        if store.store_id == "SH001" and PERIOD2_START <= current_date <= PERIOD2_END:
            weight *= 0.50
        weights.append(weight)
    return rng.choices(STORES, weights=weights, k=1)[0]


def choose_product(current_date: date, rng: random.Random, products: list[Product]) -> Product:
    weights = []
    for product in products:
        weight = 1.0
        if product.category_l1 == "童装" and (
            CURRENT_START <= current_date <= CURRENT_END
            or PERIOD2_START <= current_date <= PERIOD2_END
        ):
            weight *= 1.25
        if product.product_name.startswith(("童装T恤", "童装连衣裙", "儿童防晒外套")):
            weight *= 1.35
        weights.append(weight)
    return rng.choices(products, weights=weights, k=1)[0]


def choose_channel(current_date: date, rng: random.Random) -> str:
    channels = ["线下", "天猫", "抖音", "小程序"]
    weights = [0.46, 0.22, 0.14, 0.18]
    if CURRENT_START <= current_date <= CURRENT_END:
        weights = [0.38, 0.20, 0.27, 0.15]
    if PERIOD2_START <= current_date <= PERIOD2_END:
        weights = [0.28, 0.15, 0.45, 0.12]
    return rng.choices(channels, weights=weights, k=1)[0]


def choose_quantity(channel: str, rng: random.Random) -> int:
    if channel == "抖音":
        return rng.choices([1, 2, 3, 4], weights=[0.72, 0.20, 0.06, 0.02], k=1)[0]
    return rng.choices([1, 2, 3, 4], weights=[0.61, 0.28, 0.09, 0.02], k=1)[0]


def discount_rate(current_date: date, channel: str, rng: random.Random) -> float:
    if channel == "抖音" and PERIOD2_START <= current_date <= PERIOD2_END:
        return rng.uniform(0.48, 0.60)
    if channel == "抖音" and CURRENT_START <= current_date <= CURRENT_END:
        return rng.uniform(0.32, 0.46)
    if channel == "抖音":
        return rng.uniform(0.12, 0.24)
    if channel == "天猫":
        return rng.uniform(0.08, 0.20)
    if channel == "小程序":
        return rng.uniform(0.05, 0.16)
    return rng.uniform(0.02, 0.10)


def choose_status_and_refund(
    current_date: date,
    product: Product,
    gross: float,
    discount: float,
    rng: random.Random,
) -> tuple[str, float]:
    refund_probability = 0.045
    if product.category_l1 == "童装" and (
        CURRENT_START <= current_date <= CURRENT_END
        or PERIOD2_START <= current_date <= PERIOD2_END
    ):
        refund_probability = 0.145
    elif product.category_l1 == "童装":
        refund_probability = 0.035

    if rng.random() > refund_probability:
        return "completed", 0.0

    if rng.random() < 0.38:
        return "refunded", max(gross - discount, 0)
    refund = max((gross - discount) * rng.uniform(0.25, 0.55), 0)
    return "partial_refund", refund


def choose_customer_type(week_index: int, rng: random.Random) -> str:
    old_customer_share = min(0.35 + week_index * 0.02, 0.49)
    return "老客" if rng.random() < old_customer_share else "新客"


def build_qa_summary(
    dataframe: pd.DataFrame,
    *,
    fixture_id: str = "period1",
    current_start: date = CURRENT_START,
    current_end: date = CURRENT_END,
    previous_start: date = PREVIOUS_START,
    previous_end: date = PREVIOUS_END,
) -> dict[str, Any]:
    frame = dataframe.copy()
    frame["order_date"] = pd.to_datetime(frame["order_date"])
    current = window(frame, current_start, current_end)
    previous = window(frame, previous_start, previous_end)
    sh001_drop = sales_drop(previous, current, "SH001")
    kids_refund = refund_rate(current[current["category_l1"] == "童装"])
    douyin_current = current[current["channel"] == "抖音"]
    douyin_previous = previous[previous["channel"] == "抖音"]
    weekend_orders = frame[frame["order_date"].dt.weekday >= 5].groupby("order_date").size().mean()
    weekday_orders = frame[frame["order_date"].dt.weekday < 5].groupby("order_date").size().mean()
    first_week = window(frame, START_DATE, START_DATE + timedelta(days=6))
    returning_lift = customer_share(current, "老客") - customer_share(first_week, "老客")
    sh001_drop_threshold = -25 if fixture_id == "period1" else -10
    maximum_row_count = 10000 if fixture_id == "period1" else 12000

    checks = {
        "row_count_in_range": bool(8000 <= len(frame.index) <= maximum_row_count),
        "required_columns_present": bool(frame.columns.tolist() == COLUMNS),
        "sh001_sales_drop": bool(sh001_drop <= sh001_drop_threshold),
        "kids_refund_spike": bool(kids_refund >= 10),
        "douyin_aov_drop_with_order_lift": (
            percentage_change(aov(douyin_previous), aov(douyin_current)) <= -20
            and percentage_change(order_count(douyin_previous), order_count(douyin_current)) >= 30
        ),
        "weekend_effect": bool(weekend_orders / weekday_orders >= 1.4),
        "returning_customer_share_lift": bool(returning_lift >= 8),
    }
    checks["douyin_aov_drop_with_order_lift"] = bool(checks["douyin_aov_drop_with_order_lift"])
    return {
        "schema_version": 2,
        "fixture_id": fixture_id,
        "seed": SEED,
        "extension_seed": PERIOD2_SEED if fixture_id == "period2" else None,
        "order_count_rule": sorted(VALID_ORDER_STATUSES),
        "row_count": len(frame.index),
        "date_range": {
            "start": frame["order_date"].min().date().isoformat(),
            "end": frame["order_date"].max().date().isoformat(),
        },
        "windows": {
            "current": {"start": current_start.isoformat(), "end": current_end.isoformat()},
            "previous": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
        },
        "core_kpis": {
            "current": core_kpis(current),
            "previous": core_kpis(previous),
        },
        "anomaly_entities": [
            {"id": "sh001", "keywords": ["SH001", "徐汇"]},
            {"id": "kids", "keywords": ["童装"]},
            {"id": "douyin", "keywords": ["抖音"]},
        ],
        "checks": checks,
        "metrics": {
            "sh001_sales_delta_pct": round(sh001_drop, 2),
            "kids_current_refund_rate": round(kids_refund, 2),
            "douyin_aov_delta_pct": round(
                percentage_change(aov(douyin_previous), aov(douyin_current)), 2
            ),
            "douyin_order_delta_pct": round(
                percentage_change(order_count(douyin_previous), order_count(douyin_current)), 2
            ),
            "weekend_weekday_order_ratio": round(weekend_orders / weekday_orders, 2),
            "returning_customer_share_lift_pp": round(returning_lift, 2),
        },
    }


def window(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return frame[(frame["order_date"] >= start_ts) & (frame["order_date"] <= end_ts)]


def order_count(frame: pd.DataFrame) -> int:
    valid = frame[frame["order_status"].isin(VALID_ORDER_STATUSES)]
    return int(valid["order_id"].nunique())


def sales_amount(frame: pd.DataFrame) -> float:
    valid_sales = frame[frame["order_status"].isin(["completed", "partial_refund"])]
    return float(valid_sales["net_sales_amount"].sum())


def aov(frame: pd.DataFrame) -> float:
    orders = order_count(frame)
    return 0.0 if orders == 0 else sales_amount(frame) / orders


def core_kpis(frame: pd.DataFrame) -> dict[str, float | int]:
    return {
        "sales_amount": round(sales_amount(frame), 2),
        "order_count": order_count(frame),
        "average_order_value": round(aov(frame), 2),
        "refund_rate": round(refund_rate(frame), 2),
    }


def refund_rate(frame: pd.DataFrame) -> float:
    # 与产品报告口径一致：分母只数三种可识别的订单状态
    counted = frame[frame["order_status"].isin(["completed", "partial_refund", "refunded"])]
    if counted.empty:
        return 0.0
    refunds = counted["order_status"].isin(["refunded", "partial_refund"]).sum()
    return float(refunds / len(counted.index) * 100)


def sales_drop(previous: pd.DataFrame, current: pd.DataFrame, store_id: str) -> float:
    previous_sales = sales_amount(previous[previous["store_id"] == store_id])
    current_sales = sales_amount(current[current["store_id"] == store_id])
    return percentage_change(previous_sales, current_sales)


def customer_share(frame: pd.DataFrame, customer_type: str) -> float:
    if frame.empty:
        return 0.0
    return float((frame["customer_type"] == customer_type).sum() / len(frame.index) * 100)


def percentage_change(previous: float, current: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "period1": generate_sample_data(),
                "period2": generate_period2_fixture(),
                "period1_zh": generate_zh_header_fixture(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
