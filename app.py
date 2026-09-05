"""
app.py
資産管理ポートフォリオ 自動レポート生成ツール(ローカルAI版)

- CSV/Excelで資産データをアップロード
- pandasで集計
- ローカルLLM(Ollama)で日本語レポートを生成
- PDFとしてダウンロード

金融データを外部API・クラウドに送信せず、すべてローカル環境内で完結する設計。
"""

import os
import tempfile

import streamlit as st

from data_processor import ValidationError, compute_summary, load_data
from pdf_exporter import PdfExportError, markdown_to_pdf
from report_engine import (
    OLLAMA_MODEL,
    ReportGenerationError,
    generate_report,
)

st.set_page_config(page_title="資産管理レポート自動生成(ローカルAI版)", layout="wide")

st.title("📊 資産管理レポート自動生成ツール(ローカルAI版)")
st.caption(
    f"使用モデル: `{OLLAMA_MODEL}` (Ollamaでローカル実行 / 外部送信なし)"
)

with st.expander("サンプルデータの列フォーマット", expanded=False):
    st.markdown(
        "以下の列を含むCSV/Excelをアップロードしてください:\n\n"
        "`銘柄名, 資産クラス, 保有数量, 取得単価, 現在値, 評価額, 損益, 損益率`\n\n"
        "`sample_data/sample_portfolio.csv` にサンプルがあります。"
    )

uploaded_file = st.file_uploader(
    "資産データをアップロード(CSV / Excel)", type=["csv", "xlsx", "xls"]
)

if uploaded_file is not None:
    try:
        df = load_data(uploaded_file)
    except ValidationError as e:
        st.error(str(e))
        st.stop()

    st.subheader("アップロードされたデータ")
    st.dataframe(df, use_container_width=True)

    summary = compute_summary(df)

    col1, col2, col3 = st.columns(3)
    col1.metric("評価額合計", f"{summary.total_value:,.0f} 円")
    col2.metric(
        "損益合計",
        f"{summary.total_gain:+,.0f} 円",
        f"{summary.total_gain_rate:+.1f} %",
    )
    col3.metric("銘柄数", f"{summary.raw_row_count} 件")

    st.subheader("資産クラス別内訳")
    st.dataframe(summary.by_asset_class, use_container_width=True)

    st.caption("※ ローカルLLMでの生成のため、環境によっては数分かかります。")
    if st.button("🤖 AIレポートを生成する", type="primary"):
        with st.spinner(
            f"ローカルLLM({OLLAMA_MODEL})でレポートを生成中です。"
            "環境によっては数分かかる場合があります。しばらくお待ちください..."
        ):
            try:
                report_text = generate_report(summary)
            except ReportGenerationError as e:
                st.error(str(e))
                st.stop()

        st.session_state["report_text"] = report_text

    if "report_text" in st.session_state:
        st.subheader("生成されたレポート")
        st.markdown(st.session_state["report_text"])

        # PDF生成はローカル処理のみで軽量(LLM呼び出しを含まない)なため、
        # 「作成」ボタンを挟まずダウンロードボタン一発で完結させる。
        # download_button自体はページ描画のたびに評価されるが、
        # markdown_to_pdfは高速なので都度実行しても体感の遅延はない。
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                pdf_path = os.path.join(tmp_dir, "asset_report.pdf")
                markdown_to_pdf(st.session_state["report_text"], pdf_path)
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

            st.download_button(
                label="⬇️ PDFをダウンロード",
                data=pdf_bytes,
                file_name="asset_report.pdf",
                mime="application/pdf",
            )
        except PdfExportError as e:
            st.error(str(e))
else:
    st.info("資産データ(CSV/Excel)をアップロードすると開始できます。")
