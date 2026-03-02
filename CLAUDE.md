# 確定申告自動化システム - プロジェクト概要

## このプロジェクトの目的
個人事業主向けに、クレジットカードの利用明細CSV を読み込んで勘定科目を自動仕訳し、確定申告用CSVを出力するCLIツール。

## 技術スタック
- Python 3.9 (システムPython。3.11+向けに書いたが `eval_type_backport` で互換対応済み)
- `google-generativeai` - Gemini API (デフォルト: `gemini-2.5-flash` 無料枠)
- `pydantic v2` + `eval_type_backport` - データモデル
- `pandas`, `chardet` - CSV読み込み・文字コード自動検出
- `click` - CLI
- `pyyaml` - 設定ファイル

## 依存パッケージのインストール方法
```bash
python3 -m pip install google-generativeai pydantic pyyaml click pandas python-dotenv chardet eval_type_backport
python3 -m pip install pytest pytest-mock  # テスト用
```
※ `pip install -e .` のeditable installはPython 3.9では動かないため、直接installする

## 実行方法
```bash
# プロジェクトルートで実行 (PYTHONPATH=src が必要)
PYTHONPATH=src python3 -m tax_automation.cli --help
PYTHONPATH=src python3 -m tax_automation.cli profiles
PYTHONPATH=src python3 -m tax_automation.cli process data/input/my_card.csv --profile generic --dry-run --verbose
```

## テスト実行
```bash
PYTHONPATH=src python3 -m pytest tests/ -v
# → 35件全テスト通過
```

## 環境設定
```bash
cp .env.example .env
# .env に GEMINI_API_KEY=xxx を設定
# APIキーはGoogle AI Studio (https://aistudio.google.com/app/apikey) で取得
```

## プロジェクト構成
```
src/tax_automation/
├── models.py              # Pydanticデータモデル (Transaction, ReceiptData, ReceiptItem等)
├── config.py              # YAML設定ローダー
├── cache.py               # Gemini APIレスポンスの永続キャッシュ
├── pipeline.py            # カードCSV専用パイプライン
├── unified_pipeline.py    # 統合パイプライン (カードCSV + レシート → Excel)
├── receipt_scanner.py     # Gemini Vision APIレシート読み取り
├── matcher.py             # レシート↔カード明細の自動突合
├── cli.py                 # CLIコマンド
├── parsers/
│   ├── csv_parser.py      # プロファイル駆動CSVパーサー (ヘッダーなし対応)
│   └── profile_detector.py
├── categorizers/
│   ├── rule_based.py      # キーワードマッチング分類器
│   └── gemini.py          # Gemini API一括分類器
└── exporters/
    ├── csv_exporter.py    # CSV出力
    └── freee_exporter.py  # freee取引インポート用Excel出力

config/
├── categories.yaml        # 勘定科目マスタ (17科目: 仕入高・被服費追加済み)
├── rules.yaml             # 仕訳ルール (飲食店向けにカスタマイズ済み)
└── card_profiles/
    ├── gougin.yaml        # ごうぎんVISAカード (ヘッダーなし・Shift-JIS)
    ├── generic.yaml       # 汎用テンプレート
    ├── rakuten.yaml       # 楽天カード
    ├── epos.yaml          # エポスカード
    └── smbc.yaml          # 三井住友カード

data/
├── input/                 # カード明細CSVを入れるフォルダ
├── receipts/              # レシート画像を入れるフォルダ
└── output/                # freee用Excelの出力先
```

## 処理フロー (統合パイプライン)
```
カードCSV + レシート画像 → [CSVパース] + [レシートAIスキャン]
  → [自動マッチング] → [ルール分類] → [Gemini分類] → [freee用Excel出力]
```
- レシートとカード明細は日付+金額で自動マッチング → 重複しない
- マッチしたレシートは品目詳細をカード取引に統合
- マッチしないレシートは現金取引として新規登録

## 出力Excel (freeeインポート形式)
`収支区分, 発生日, 取引先, 勘定科目, 税区分, 金額, 決済口座, 決済方法, 購入品目`

## 完了済みタスク
- [x] 実際のカードCSVでの動作確認 (ごうぎんVISA 202502〜202512)
- [x] ごうぎんカード用プロファイルYAML作成
- [x] 飲食店向けルール・カテゴリカスタマイズ (仕入高・被服費)
- [x] freee用Excel出力対応
- [x] レシートスキャン機能 (Gemini Vision API)
- [x] レシート↔カード明細の自動突合システム
- [x] 統合パイプライン (カード+レシート一括処理)

## 今後やること
- [ ] レシート画像での実データテスト
- [ ] Streamlit Webアプリ化 (経理担当者向けUI)
- [ ] 手動修正ワークフロー
- [ ] Amazon注文履歴CSVとの自動突合

