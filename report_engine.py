"""
report_engine.py
ローカルLLM(Ollama)を呼び出し、資産サマリーから日本語レポートを生成する。

モデルは環境変数 OLLAMA_MODEL で切り替え可能。
デフォルトは日本語特化モデルの elyza:8b
(事前に `ollama pull hf.co/elyza/Llama-3-ELYZA-JP-8B-GGUF:Q4_K_M` の上
 `ollama cp ... elyza:8b` でリネームしておくこと。詳細はREADME参照)。

速度優先で試したい場合は、環境変数で軽量モデルに切り替えられる:
    OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M streamlit run app.py
"""

from __future__ import annotations

import os

import requests

from data_processor import PortfolioSummary
from pdf_exporter import _parse_blocks, _strip_leading_preamble

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "elyza:8b")
REQUEST_TIMEOUT_SECONDS = 180


class ReportGenerationError(Exception):
    """Ollama呼び出しに失敗した場合に送出する。"""


def _build_prompt(summary: PortfolioSummary) -> str:
    asset_class_lines = "\n".join(
        f"- {row['資産クラス']}: 評価額 {row['評価額']:,.0f}円"
        f"(構成比 {row['構成比(%)']:.1f}%)"
        for _, row in summary.by_asset_class.iterrows()
    )
    gainers_lines = "\n".join(
        f"- {row['銘柄名']}: {row['損益']:+,.0f}円({row['損益率']:+.1f}%)"
        for _, row in summary.top_gainers.iterrows()
    )
    losers_lines = "\n".join(
        f"- {row['銘柄名']}: {row['損益']:+,.0f}円({row['損益率']:+.1f}%)"
        for _, row in summary.top_losers.iterrows()
    )
    notes_lines = "\n".join(f"- {n}" for n in summary.extra_notes) or "- 特になし"

    return f"""あなたは資産管理レポートを作成するアシスタントです。
以下の数値データをもとに、日本語で「資産管理レポート」を作成してください。

# 集計データ
- 銘柄数: {summary.raw_row_count}件
- 評価額合計: {summary.total_value:,.0f}円
- 損益合計: {summary.total_gain:+,.0f}円(損益率 {summary.total_gain_rate:+.1f}%)

## 資産クラス別内訳
{asset_class_lines}

## 評価益上位
{gainers_lines}

## 評価損上位
{losers_lines}

## 検出された偏り等
{notes_lines}

# レポートの構成(この順番・見出しで、Markdown形式で書いてください)
## 1. 保有資産の現状サマリー
評価額合計、資産クラス別の配分状況を分かりやすく説明してください。

## 2. 損益・パフォーマンス分析
全体の損益状況、評価益/評価損が大きい銘柄について触れてください。

## 3. リバランス提案
資産クラスの配分に偏りがあれば指摘し、一般的な分散投資の考え方に基づいた
参考コメントを述べてください。これは投資助言ではなく一般的な情報提供である旨を
最後に一言添えてください。
- 「高い/低い」といった評価は、必ず上記の「資産クラス別内訳」に実際に記載されている
  構成比(%)の数値と比較した上で述べてください。数値を確認せずに一般論だけで
  「低い」「高い」と判定しないでください。
- 「◯%を目安にすべき」のような具体的な数値基準を新たに作り出さないでください。
  あくまで実際に提示された構成比同士の比較(例:投資信託が57.0%と資産の半分以上を
  占めている、など)に基づいてコメントしてください。

文体は丁寧語(です・ます調)で、専門用語は必要最小限にしてください。
文末は必ず「です」「ます」で統一し、「である」「だ」調を混在させないでください。

# 出力形式についての厳守事項
- 「以下にレポートを作成します」のような前置きの文は一切書かないでください。
- 挨拶や確認の言葉も不要です。
- 見出し「## 1. 保有資産の現状サマリー」から直接書き始めてください。
- Markdown本文以外の文章(説明、注釈、英語での応答など)を含めないでください。
"""


def generate_report(summary: PortfolioSummary) -> str:
    """Ollamaにプロンプトを投げ、Markdown形式のレポート文字列を返す。"""
    prompt = _build_prompt(summary)

    try:
        response = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise ReportGenerationError(
            "Ollamaに接続できません。`ollama serve` が起動しているか確認してください。"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise ReportGenerationError(
            f"レポート生成がタイムアウトしました({REQUEST_TIMEOUT_SECONDS}秒)。"
            "モデルサイズを軽量なものに変更するか、タイムアウト値を延ばしてください。"
        ) from exc
    except requests.exceptions.HTTPError as exc:
        raise ReportGenerationError(
            f"Ollama APIエラー: {exc}. "
            f"モデル '{OLLAMA_MODEL}' がpull済みか `ollama list` で確認してください。"
        ) from exc

    data = response.json()
    try:
        raw_text = data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise ReportGenerationError(
            f"Ollamaのレスポンス形式が想定と異なります: {data}"
        ) from exc

    return normalize_report_text(raw_text)


def normalize_report_text(markdown_text: str) -> str:
    """LLM出力にありがちな『文の途中での改行』を取り除き、見出し・箇条書き・
    段落の区切りだけを保った整形済みMarkdownに正規化する。

    Streamlitは(標準的なMarkdown仕様と異なり)1つの改行でも見た目上の改行
    として表示するため、この正規化を行わずに st.markdown() へ渡すと、
    LLMが文中に入れた改行がそのまま不自然な位置での改行として表示されてしまう。
    プレビュー表示・PDF変換のどちらに使う場合も、必ずこの関数を通した後の
    テキストを使うこと。
    """
    out_lines: list[str] = []
    blocks = _strip_leading_preamble(_parse_blocks(markdown_text))
    for block_type, text in blocks:
        if block_type.startswith("h") and block_type[1:].isdigit():
            out_lines.append(f"{'#' * int(block_type[1:])} {text}")
        elif block_type == "bullet":
            out_lines.append(f"- {text}")
        else:
            out_lines.append(text)
        out_lines.append("")  # ブロック間に空行を入れ、Markdownとして正しく段落分けする
    return "\n".join(out_lines).strip()
