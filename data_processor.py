"""
data_processor.py
資産データ(CSV/Excel)の読込・検証・集計を行うモジュール。
LLMに渡す前に、ここで数値サマリーまで作り込んでおくことで、
大きな生データをそのままLLMに投げない設計にしている。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

REQUIRED_COLUMNS = [
    "銘柄名",
    "資産クラス",
    "保有数量",
    "取得単価",
    "現在値",
    "評価額",
    "損益",
    "損益率",
]


class ValidationError(Exception):
    """入力データが想定フォーマットと異なる場合に送出する。"""


def load_data(uploaded_file) -> pd.DataFrame:
    """StreamlitのUploadedFileオブジェクトからDataFrameを読み込む。

    拡張子(.csv / .xlsx / .xls)を見て自動的にパーサーを切り替える。
    """
    name = uploaded_file.name.lower()
    raw_bytes = uploaded_file.read()

    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(raw_bytes))
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(raw_bytes))
    else:
        raise ValidationError(
            f"対応していないファイル形式です: {uploaded_file.name}"
            "(.csv / .xlsx / .xls のみ対応)"
        )

    _validate_columns(df)
    return df


def _validate_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValidationError(
            "以下の列が見つかりません: " + ", ".join(missing) +
            f"\n必要な列: {', '.join(REQUIRED_COLUMNS)}"
        )


@dataclass
class PortfolioSummary:
    total_value: float
    total_gain: float
    total_gain_rate: float
    by_asset_class: pd.DataFrame  # 資産クラス別: 評価額合計, 構成比
    top_gainers: pd.DataFrame
    top_losers: pd.DataFrame
    raw_row_count: int
    extra_notes: list[str] = field(default_factory=list)


def compute_summary(df: pd.DataFrame, top_n: int = 3) -> PortfolioSummary:
    """DataFrameから、レポート生成に必要な数値サマリーを作成する。"""
    total_value = float(df["評価額"].sum())
    total_gain = float(df["損益"].sum())
    total_cost = total_value - total_gain
    total_gain_rate = (total_gain / total_cost * 100) if total_cost else 0.0

    by_asset_class = (
        df.groupby("資産クラス")["評価額"]
        .sum()
        .reset_index()
        .sort_values("評価額", ascending=False)
    )
    by_asset_class["構成比(%)"] = (
        by_asset_class["評価額"] / total_value * 100
    ).round(1)

    sorted_by_gain = df.sort_values("損益", ascending=False)
    top_gainers = sorted_by_gain.head(top_n)[["銘柄名", "損益", "損益率"]]
    top_losers = sorted_by_gain.tail(top_n)[["銘柄名", "損益", "損益率"]].sort_values(
        "損益"
    )

    notes = []
    concentration = by_asset_class.iloc[0]
    if concentration["構成比(%)"] >= 60:
        notes.append(
            f"{concentration['資産クラス']}が資産全体の"
            f"{concentration['構成比(%)']:.1f}%を占めており、偏りが大きい状態です。"
        )

    return PortfolioSummary(
        total_value=total_value,
        total_gain=total_gain,
        total_gain_rate=total_gain_rate,
        by_asset_class=by_asset_class,
        top_gainers=top_gainers,
        top_losers=top_losers,
        raw_row_count=len(df),
        extra_notes=notes,
    )
