"""Built-in ticker -> company-name fallback for major Tokyo-listed issues.

The heat map resolves names from the EDINET / Yahoo CSVs first; this static map
is the last-resort fallback so common watch-list codes still show a company name
even when those data files don't cover them (no network, no fetch required).
Names are the common Japanese display names; this is a display aid only, not
investment advice. Extend as needed.
"""

from __future__ import annotations

COMPANY_NAMES: dict[str, str] = {
    # --- common default watch list ---
    "6758": "ソニーグループ",
    "9432": "日本電信電話（NTT）",
    "9984": "ソフトバンクグループ",
    "8058": "三菱商事",
    "7203": "トヨタ自動車",
    "8306": "三菱UFJフィナンシャル・グループ",
    "9433": "KDDI",
    "6861": "キーエンス",
    # --- autos / machinery ---
    "7201": "日産自動車",
    "7267": "ホンダ",
    "7269": "スズキ",
    "7270": "SUBARU",
    "7261": "マツダ",
    "6902": "デンソー",
    "6201": "豊田自動織機",
    "6367": "ダイキン工業",
    "6273": "SMC",
    "6954": "ファナック",
    "6301": "コマツ",
    "6326": "クボタ",
    "7011": "三菱重工業",
    "7012": "川崎重工業",
    # --- electronics / semis ---
    "6501": "日立製作所",
    "6503": "三菱電機",
    "6752": "パナソニック ホールディングス",
    "6971": "京セラ",
    "6981": "村田製作所",
    "6762": "TDK",
    "6857": "アドバンテスト",
    "8035": "東京エレクトロン",
    "6920": "レーザーテック",
    "7751": "キヤノン",
    "7741": "HOYA",
    "7974": "任天堂",
    "6098": "リクルートホールディングス",
    "6594": "ニデック",
    # --- pharma / chemicals / materials ---
    "4063": "信越化学工業",
    "4502": "武田薬品工業",
    "4519": "中外製薬",
    "4523": "エーザイ",
    "4568": "第一三共",
    "4452": "花王",
    "4911": "資生堂",
    "4901": "富士フイルムホールディングス",
    "3407": "旭化成",
    "3402": "東レ",
    "4188": "三菱ケミカルグループ",
    "5108": "ブリヂストン",
    "5401": "日本製鉄",
    "5411": "JFEホールディングス",
    # --- finance / insurance / real estate ---
    "8316": "三井住友フィナンシャルグループ",
    "8411": "みずほフィナンシャルグループ",
    "8591": "オリックス",
    "8604": "野村ホールディングス",
    "8766": "東京海上ホールディングス",
    "8725": "MS&ADインシュアランスグループ",
    "8801": "三井不動産",
    "8802": "三菱地所",
    # --- trading / retail / consumer ---
    "8001": "伊藤忠商事",
    "8002": "丸紅",
    "8031": "三井物産",
    "8053": "住友商事",
    "8267": "イオン",
    "3382": "セブン&アイ・ホールディングス",
    "9983": "ファーストリテイリング",
    "4661": "オリエンタルランド",
    "2914": "日本たばこ産業",
    "2502": "アサヒグループホールディングス",
    "2503": "キリンホールディングス",
    "2802": "味の素",
    # --- telecom / IT / internet ---
    "4755": "楽天グループ",
    "4689": "LINEヤフー",
    "9434": "ソフトバンク",
    # --- transport / utilities / energy ---
    "9020": "東日本旅客鉄道（JR東日本）",
    "9022": "東海旅客鉄道（JR東海）",
    "9201": "日本航空",
    "9202": "ANAホールディングス",
    "9101": "日本郵船",
    "9104": "商船三井",
    "9107": "川崎汽船",
    "9501": "東京電力ホールディングス",
    "9531": "東京ガス",
    "1605": "INPEX",
    "5020": "ENEOSホールディングス",
    # --- construction ---
    "1801": "大成建設",
    "1802": "大林組",
    "1803": "清水建設",
    "1812": "鹿島建設",
    "1928": "積水ハウス",
}


def builtin_company_name(ticker: str) -> str | None:
    """Return the built-in display name for a bare Tokyo code, if known."""

    code = ticker.strip().upper()
    code = code[:-2] if code.endswith(".T") else code
    return COMPANY_NAMES.get(code)
