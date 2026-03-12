"""確定申告自動化システム - Streamlit Webアプリ

経理担当者向けのシンプルなWebインターフェース。
カード明細CSV＋レシート画像をアップロード → 自動仕訳 → freee用Excelダウンロード
"""

import sys
import os
import logging
import tempfile
from pathlib import Path
from decimal import Decimal

from dotenv import load_dotenv
load_dotenv()  # .env からAPIキーを読み込む

import streamlit as st
import pandas as pd

# プロジェクトのsrcをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from tax_automation.unified_pipeline import UnifiedPipeline
from tax_automation.exporters.freee_exporter import FreeeExcelExporter
from tax_automation.models import PaymentMethod

# ログ設定
logging.basicConfig(level=logging.INFO, format="%(message)s")

# ============================================================
# ページ設定
# ============================================================
st.set_page_config(
    page_title="確定申告自動化システム",
    page_icon="🧾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# カスタムCSS
# ============================================================
st.markdown("""
<style>
    /* メインヘッダー */
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        color: white;
    }
    .main-header h1 {
        color: white !important;
        font-size: 2rem !important;
        margin-bottom: 0.3rem !important;
    }
    .main-header p {
        color: #a0aec0;
        font-size: 1rem;
        margin: 0;
    }

    /* ステータスカード */
    .stat-card {
        background: linear-gradient(135deg, #f8f9fa, #ffffff);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    .stat-card .value {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a2e;
    }
    .stat-card .label {
        font-size: 0.85rem;
        color: #718096;
        margin-top: 4px;
    }

    /* アップロードエリア */
    .upload-section {
        background: #f7fafc;
        border: 2px dashed #cbd5e0;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
    }

    /* 結果テーブル */
    .dataframe {
        font-size: 0.85rem !important;
    }

    /* ボタンスタイル */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        padding: 0.6rem 2rem;
    }

    /* サイドバー */
    [data-testid="stSidebar"] {
        background-color: #f8f9fa;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# ヘッダー
# ============================================================
st.markdown("""
<div class="main-header">
    <h1>🧾 確定申告自動化システム</h1>
    <p>カード明細CSV＋レシート画像をアップロード → AIが自動仕訳 → freee用Excelをダウンロード</p>
</div>
""", unsafe_allow_html=True)


# ============================================================
# サイドバー: 設定
# ============================================================
with st.sidebar:
    st.markdown("### ⚙️ 設定")

    profile = st.selectbox(
        "カードプロファイル",
        ["gougin", "rakuten", "epos", "smbc", "generic"],
        index=0,
        help="使用するクレジットカードの種類を選択",
    )

    profile_names = {
        "gougin": "ごうぎんVISAカード",
        "rakuten": "楽天カード",
        "epos": "エポスカード",
        "smbc": "三井住友カード",
        "generic": "汎用",
    }

    settlement_account = st.text_input(
        "決済口座名",
        value=profile_names.get(profile, "クレジットカード"),
        help="freeeに登録している口座名",
    )

    st.markdown("---")
    st.markdown("### 🔑 Gemini APIキー")

    # 優先順位: 環境変数 → st.secrets → 手動入力
    _env_key = os.getenv("GEMINI_API_KEY", "")
    if not _env_key:
        try:
            _env_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            pass

    if _env_key:
        st.success("APIキー設定済み ✅", icon="🔐")
        sidebar_api_key = _env_key
    else:
        sidebar_api_key = st.text_input(
            "APIキーを入力",
            type="password",
            placeholder="AIzaSy...",
            help="Google AI Studio (aistudio.google.com) で取得できます",
        )
        if not sidebar_api_key:
            st.warning("APIキーを入力してください")

    st.markdown("---")
    st.markdown("### 📋 使い方")
    st.markdown("""
    1. **カード明細CSV**をアップロード
    2. **レシート画像**をアップロード（任意）
    3. **「仕訳実行」**ボタンを押す
    4. 結果を確認して**Excelをダウンロード**
    """)

    st.markdown("---")
    st.markdown(
        "<small style='color: #999'>Powered by Gemini AI</small>",
        unsafe_allow_html=True,
    )


# ============================================================
# メインエリア: ファイルアップロード
# ============================================================
col1, col2 = st.columns(2)

with col1:
    st.markdown("### 💳 カード明細CSV")
    csv_file = st.file_uploader(
        "カード明細CSVをアップロード",
        type=["csv"],
        help="カード会社からダウンロードしたCSVファイル",
        key="csv_upload",
    )
    if csv_file:
        st.success(f"✅ {csv_file.name} ({csv_file.size / 1024:.1f} KB)")

with col2:
    st.markdown("### 📸 レシート画像（任意）")
    receipt_files = st.file_uploader(
        "レシート画像をアップロード（複数可）",
        type=["jpg", "jpeg", "png", "heic", "webp"],
        accept_multiple_files=True,
        help="レシートの写真。複数枚のレシートを1枚に並べて撮った画像もOK",
        key="receipt_upload",
    )
    if receipt_files:
        st.success(f"✅ {len(receipt_files)}枚のレシート画像")


# ============================================================
# 仕訳実行ボタン
# ============================================================
st.markdown("---")

if not csv_file and not receipt_files:
    st.info("👆 カード明細CSVまたはレシート画像をアップロードしてください")
    st.stop()

col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    run_button = st.button(
        "🚀 仕訳を実行する",
        type="primary",
        use_container_width=True,
    )

if not run_button:
    st.stop()


# ============================================================
# 処理実行
# ============================================================
if not sidebar_api_key:
    st.error("⚠️ サイドバーにGemini APIキーを入力してから実行してください。")
    st.stop()

with st.spinner("🤖 AIが仕訳処理中... しばらくお待ちください"):
    try:
        # サイドバーで確定済みのAPIキーをenv varに設定
        api_key = sidebar_api_key
        os.environ["GEMINI_API_KEY"] = api_key

        # 一時ファイルにCSVを保存
        csv_path = None
        if csv_file:
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
                f.write(csv_file.getvalue())
                csv_path = f.name

        # レシート画像を一時フォルダに保存
        receipt_folder = None
        if receipt_files:
            receipt_folder = tempfile.mkdtemp()
            for rf in receipt_files:
                img_path = os.path.join(receipt_folder, rf.name)
                with open(img_path, "wb") as f:
                    f.write(rf.getvalue())

        # パイプライン実行
        pipeline = UnifiedPipeline(
            profile_name=profile,
            settlement_account=settlement_account,
            use_gemini=True,
            default_business_ratio=1.0,
        )

        transactions, stats = pipeline.run(
            card_csv=csv_path,
            receipt_folder=receipt_folder,
            dry_run=True,
            verbose=False,
        )

        # 一時ファイル削除
        if csv_path:
            os.unlink(csv_path)

    except Exception as e:
        st.error(f"❌ エラーが発生しました: {e}")
        import traceback
        st.code(traceback.format_exc())
        st.stop()


# ============================================================
# 統計表示
# ============================================================
st.markdown("---")
st.markdown("## 📊 処理結果")

stat_cols = st.columns(5)
stat_data = [
    ("合計", stats.total, "件"),
    ("ルールマッチ", stats.rule_matched, "件"),
    ("AI分類", stats.gemini_categorized + stats.cache_hit, "件"),
    ("未分類", stats.unclassified, "件"),
    ("レシート", stats.receipts_scanned, "枚"),
]

for col, (label, value, unit) in zip(stat_cols, stat_data):
    with col:
        st.markdown(f"""
        <div class="stat-card">
            <div class="value">{value}</div>
            <div class="label">{label} ({unit})</div>
        </div>
        """, unsafe_allow_html=True)

if stats.receipts_scanned > 0:
    st.markdown("")
    rcols = st.columns(3)
    with rcols[0]:
        st.metric("カードと統合", f"{stats.receipts_matched}枚")
    with rcols[1]:
        st.metric("現金取引", f"{stats.receipts_cash}枚")
    with rcols[2]:
        if stats.receipts_unmatched > 0:
            st.metric("要確認", f"{stats.receipts_unmatched}枚", delta="要確認", delta_color="inverse")
        else:
            st.metric("要確認", "0枚")


# ============================================================
# 結果テーブル
# ============================================================
st.markdown("### 📋 仕訳一覧")

rows = []
for tx in sorted(transactions, key=lambda t: t.date):
    pay_icon = "💵" if tx.payment_method == PaymentMethod.CASH else "💳"
    receipt_icon = "📄" if tx.matched_receipt else ""
    items_text = ", ".join(item.name for item in tx.receipt_items[:5]) if tx.receipt_items else ""

    rows.append({
        "": f"{pay_icon}{receipt_icon}",
        "日付": tx.date.strftime("%Y/%m/%d"),
        "取引先": tx.merchant_name,
        "勘定科目": tx.category_name or tx.category_code or "未分類",
        "金額": f"¥{int(tx.amount):,}",
        "決済": "現金" if tx.payment_method == PaymentMethod.CASH else "カード",
        "品目": items_text,
        "分類方法": tx.categorization_source.value,
    })

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# 勘定科目別サマリー
# ============================================================
st.markdown("### 📈 勘定科目別合計")

from collections import defaultdict
category_totals = defaultdict(int)
for tx in transactions:
    code = tx.category_name or tx.category_code or "未分類"
    category_totals[code] += int(tx.amount)

summary_df = pd.DataFrame([
    {"勘定科目": k, "合計金額": f"¥{v:,}", "金額(数値)": v}
    for k, v in sorted(category_totals.items(), key=lambda x: -x[1])
])

col_chart, col_table = st.columns([2, 1])
with col_chart:
    import altair as alt
    chart_data = pd.DataFrame([
        {"勘定科目": k, "金額": v}
        for k, v in sorted(category_totals.items(), key=lambda x: -x[1])
        if v > 0
    ])
    if not chart_data.empty:
        chart = alt.Chart(chart_data).mark_bar(
            cornerRadiusTopLeft=6,
            cornerRadiusTopRight=6,
        ).encode(
            x=alt.X("勘定科目", sort="-y", axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("金額", axis=alt.Axis(format=",.0f")),
            color=alt.Color("勘定科目", legend=None,
                scale=alt.Scale(scheme="tableau10")),
            tooltip=["勘定科目", alt.Tooltip("金額", format=",.0f")],
        ).properties(height=350)
        st.altair_chart(chart, use_container_width=True)

with col_table:
    st.dataframe(
        summary_df[["勘定科目", "合計金額"]],
        use_container_width=True,
        hide_index=True,
    )
    total = sum(v for v in category_totals.values() if v > 0)
    st.markdown(f"**合計: ¥{total:,}**")


# ============================================================
# Excelダウンロード
# ============================================================
st.markdown("---")
st.markdown("## 📥 freee用Excelダウンロード")

with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
    exporter = FreeeExcelExporter(settlement_account=settlement_account)
    exporter.export(transactions, f.name)
    excel_path = f.name

with open(excel_path, "rb") as f:
    excel_data = f.read()

os.unlink(excel_path)

file_name = f"freee_import_{csv_file.name.replace('.csv', '')}.xlsx" if csv_file else "freee_import.xlsx"

st.download_button(
    label="📥 freee用Excelをダウンロード",
    data=excel_data,
    file_name=file_name,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    use_container_width=True,
)

st.caption("このファイルをfreeeの「取引」→「エクセルインポート」からインポートしてください。")
