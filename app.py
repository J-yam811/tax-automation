"""確定申告自動仕訳システム - Streamlit Web UI"""

from __future__ import annotations

import io
import logging
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

# src/ をパスに追加 (PYTHONPATH 未設定環境向け)
sys.path.insert(0, str(Path(__file__).parent / "src"))

from tax_automation.config import list_available_profiles, load_card_profile
from tax_automation.exporters.csv_exporter import CsvExporter, _OUTPUT_COLUMNS
from tax_automation.models import CategorizationSource
from tax_automation.parsers.profile_detector import detect_profile
from tax_automation.pipeline import Pipeline

# ─────────────────────────────────────────────
# ログ設定 (Streamlit 環境用)
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# ─────────────────────────────────────────────
# ページ設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="確定申告 仕訳システム",
    page_icon="📊",
    layout="wide",
)

st.title("📊 確定申告 自動仕訳システム")
st.caption("クレジットカードの利用明細CSVをアップロードするだけで勘定科目を自動分類します")

# ─────────────────────────────────────────────
# サイドバー: 設定
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")

    business_ratio = st.slider(
        "事業割合 (%)",
        min_value=0,
        max_value=100,
        value=100,
        step=5,
        help="全明細に適用するデフォルトの事業割合。後から個別に変更可能です。",
    )

    current_year = 2026
    year_options = ["全年度"] + [str(y) for y in range(current_year, current_year - 6, -1)]
    year_label = st.selectbox(
        "年度フィルター",
        options=year_options,
        index=1,
        help="指定した年のトランザクションのみ出力します",
    )
    year_filter: int | None = None if year_label == "全年度" else int(year_label)

    use_gemini = st.checkbox(
        "Gemini AI による分類を使用する",
        value=True,
        help="ルールで分類できなかった明細をGemini AIで分類します。APIキーが必要です。",
    )

    st.divider()
    st.subheader("対応カード一覧")
    for p in list_available_profiles():
        try:
            name = load_card_profile(p).name
            st.caption(f"• {name} (`{p}`)")
        except Exception:
            pass

# ─────────────────────────────────────────────
# メインエリア
# ─────────────────────────────────────────────
uploaded_file = st.file_uploader(
    "利用明細CSVをアップロード",
    type=["csv"],
    help="楽天カード・エポス・三井住友など主要カードのCSVに対応。形式は自動判定します。",
)

if uploaded_file is None:
    st.info("CSVファイルをアップロードしてください。カード会社の管理サイトからダウンロードできます。")
    st.stop()

# ─────────────────────────────────────────────
# プロファイル自動検出 (ファイルが変わったときだけ実行)
# ─────────────────────────────────────────────
file_id = f"{uploaded_file.name}_{uploaded_file.size}"
if st.session_state.get("last_file_id") != file_id:
    # 一時ファイルに保存してプロファイル検出
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = Path(tmp.name)

    detected = detect_profile(tmp_path)
    st.session_state["last_file_id"] = file_id
    st.session_state["tmp_input_path"] = str(tmp_path)
    st.session_state["detected_profile"] = detected
    # 前回の結果をクリア
    st.session_state.pop("result_transactions", None)
    st.session_state.pop("result_stats", None)
    st.session_state.pop("result_csv_bytes", None)

detected_profile: str = st.session_state["detected_profile"]
tmp_input_path: str = st.session_state["tmp_input_path"]

# カード検出結果を表示
profile_display_name = detected_profile
try:
    profile_display_name = load_card_profile(detected_profile).name
except Exception:
    pass

col1, col2 = st.columns([3, 1])
with col1:
    st.success(f"カード形式を検出しました: **{profile_display_name}** (`{detected_profile}`)")
with col2:
    override_profile = st.selectbox(
        "別のプロファイルを使用",
        options=["(自動検出)"] + list_available_profiles(),
        index=0,
        label_visibility="collapsed",
    )

active_profile = detected_profile if override_profile == "(自動検出)" else override_profile

# ─────────────────────────────────────────────
# 処理実行ボタン
# ─────────────────────────────────────────────
if st.button("▶ 仕訳を実行", type="primary", use_container_width=True):
    with st.spinner("仕訳処理中..."):
        try:
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as out_tmp:
                out_path = Path(out_tmp.name)

            pipeline = Pipeline(
                profile_name=active_profile,
                use_gemini=use_gemini,
                default_business_ratio=business_ratio / 100,
            )
            transactions, stats = pipeline.run(
                input_csv=Path(tmp_input_path),
                output_csv=out_path,
                year=year_filter,
                dry_run=False,
            )

            # ダウンロード用 CSV をメモリに読み込む
            with open(out_path, "rb") as f:
                csv_bytes = f.read()

            st.session_state["result_transactions"] = transactions
            st.session_state["result_stats"] = stats
            st.session_state["result_csv_bytes"] = csv_bytes

        except Exception as e:
            st.error(f"処理中にエラーが発生しました: {e}")
            st.stop()

# ─────────────────────────────────────────────
# 結果表示
# ─────────────────────────────────────────────
if "result_transactions" not in st.session_state:
    st.stop()

transactions = st.session_state["result_transactions"]
stats = st.session_state["result_stats"]
csv_bytes: bytes = st.session_state["result_csv_bytes"]

# 統計サマリー
st.divider()
st.subheader("処理結果")

metric_cols = st.columns(5)
metric_cols[0].metric("合計件数", stats.total)
metric_cols[1].metric("ルール分類", stats.rule_matched)
metric_cols[2].metric("キャッシュ利用", stats.cache_hit)
metric_cols[3].metric("Gemini分類", stats.gemini_categorized)
metric_cols[4].metric("未分類", stats.unclassified)

# 勘定科目別サマリー
exporter = CsvExporter()
summary_text = exporter.export_summary(transactions, year=year_filter)
with st.expander("勘定科目別合計を見る", expanded=True):
    st.code(summary_text)

# 仕訳結果テーブル
st.subheader("仕訳結果一覧")

# Transaction → DataFrame に変換
_SOURCE_LABELS = {
    CategorizationSource.RULE: "ルール",
    CategorizationSource.GEMINI: "Gemini",
    CategorizationSource.CACHE: "キャッシュ",
    CategorizationSource.MANUAL: "手動",
    CategorizationSource.UNCLASSIFIED: "未分類",
}

rows = []
for tx in sorted(transactions, key=lambda t: t.date):
    if year_filter and tx.date.year != year_filter:
        continue
    business_ratio_val = float(tx.business_ratio)
    rows.append({
        "日付": tx.date.strftime("%Y/%m/%d"),
        "金額": int(tx.amount),
        "利用店名": tx.merchant_name,
        "勘定科目": tx.category_name or tx.category_code or "未分類",
        "摘要": tx.memo or "",
        "事業割合": f"{int(business_ratio_val * 100)}%",
        "経費計上額": round(float(tx.amount) * business_ratio_val),
        "分類方法": _SOURCE_LABELS.get(tx.categorization_source, ""),
        "Gemini判断理由": tx.gemini_reasoning or "",
    })

if rows:
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.warning("表示するトランザクションがありません。年度フィルターを確認してください。")

# ダウンロードボタン
st.divider()
st.download_button(
    label="📥 仕訳結果CSVをダウンロード",
    data=csv_bytes,
    file_name=f"仕訳結果_{uploaded_file.name}",
    mime="text/csv",
    use_container_width=True,
    type="primary",
)
