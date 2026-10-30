"""Industry code (產業別) -> sector name. TWSE and TPEx share the same numbering."""
from __future__ import annotations

INDUSTRY_NAMES: dict[str, str] = {
    "01": "水泥",
    "02": "食品",
    "03": "塑膠",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "玻璃陶瓷",
    "09": "造紙",
    "10": "鋼鐵",
    "11": "橡膠",
    "12": "汽車",
    "14": "建材營造",
    "15": "航運",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "19": "綜合",
    "20": "其他",
    "21": "化學",
    "22": "生技醫療",
    "23": "油電燃氣",
    "24": "半導體",
    "25": "電腦及週邊設備",
    "26": "光電",
    "27": "通信網路",
    "28": "電子零組件",
    "29": "電子通路",
    "30": "資訊服務",
    "31": "其他電子",
    "32": "文化創意",
    "33": "農業科技",
    "34": "電子商務",
    "35": "綠能環保",
    "36": "數位雲端",
    "37": "運動休閒",
    "38": "居家生活",
    "80": "管理股票",
    "91": "存託憑證",
}

ETF_SECTOR = "ETF / 其他商品"
UNKNOWN_SECTOR = "未分類"

# sectors that have an official TWSE 類股指數 of the same name
TWSE_SECTOR_INDEX = {name: f"{name}類指數" for name in INDUSTRY_NAMES.values()}
TWSE_SECTOR_INDEX["其他"] = "其他類指數"
MAIN_INDEX = "發行量加權股價指數"


def is_common_stock(code: str) -> bool:
    """4-digit code not starting with 00 -> ordinary listed/OTC company (excludes ETF, ETN, warrants, TDR-ish codes)."""
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


def sector_name(code: str, industry: str | None) -> str:
    if not is_common_stock(code):
        return ETF_SECTOR
    if industry:
        return INDUSTRY_NAMES.get(industry.strip(), f"{UNKNOWN_SECTOR}({industry.strip()})")
    return UNKNOWN_SECTOR
