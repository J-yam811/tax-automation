"""プロファイル駆動のクレジットカードCSVパーサー"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import chardet
import pandas as pd

from ..models import CardProfile, Transaction


class CsvParser:
    """カードプロファイルの設定に従ってCSVファイルをパースする。

    文字コードは chardet で自動検出し、プロファイルの encoding 設定で
    上書きすることも可能。
    """

    def __init__(self, profile: CardProfile):
        self.profile = profile

    def parse(self, csv_path: Path | str) -> list[Transaction]:
        """CSVファイルを読み込んで Transaction オブジェクトのリストを返す。"""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSVファイルが見つかりません: {path}")

        encoding = self._detect_encoding(path)
        df = self._read_csv(path, encoding)
        return self._convert_to_transactions(df)

    def _detect_encoding(self, path: Path) -> str:
        """ファイルの文字コードを自動検出する。プロファイルの設定が優先。"""
        profile_enc = self.profile.encoding.lower()
        if profile_enc not in ("auto", ""):
            return profile_enc

        with path.open("rb") as f:
            raw = f.read(10000)  # 先頭10KBで判定
        result = chardet.detect(raw)
        detected = result.get("encoding") or "utf-8"
        # Shift-JIS系の名称を統一
        if detected.lower() in ("shift_jis", "shift-jis", "sjis", "cp932", "windows-1252"):
            return "cp932"
        return detected

    def _read_csv(self, path: Path, encoding: str) -> pd.DataFrame:
        """pandasでCSVを読み込む。ヘッダー行の調整も行う。"""
        p = self.profile
        # ヘッダーなしCSVの場合は header=None を指定
        header_opt = None if not p.has_header else "infer"
        try:
            df = pd.read_csv(
                path,
                encoding=encoding,
                delimiter=p.delimiter,
                header=header_opt,
                skiprows=p.skip_rows if p.skip_rows > 0 else None,
                skipfooter=p.skip_footer_rows,
                engine="python",  # skipfooter には python エンジンが必要
                dtype=str,
                skip_blank_lines=True,
            )
        except UnicodeDecodeError:
            # 文字コード検出に失敗した場合のフォールバック
            df = pd.read_csv(
                path,
                encoding="cp932",
                delimiter=p.delimiter,
                header=header_opt,
                skiprows=p.skip_rows if p.skip_rows > 0 else None,
                skipfooter=p.skip_footer_rows,
                engine="python",
                dtype=str,
                skip_blank_lines=True,
            )

        # カラム名を文字列に統一 (ヘッダーなしの場合は整数 → 文字列)
        df.columns = [str(c).strip() for c in df.columns]

        # 完全に空の行を除去
        df = df.dropna(how="all")

        return df

    def _convert_to_transactions(self, df: pd.DataFrame) -> list[Transaction]:
        """DataFrame の各行を Transaction オブジェクトに変換する。"""
        p = self.profile
        transactions = []

        for _, row in df.iterrows():
            try:
                # 日付
                raw_date = str(row[p.date_column]).strip()
                parsed_date = self._parse_date(raw_date, p.date_format)

                # 金額
                raw_amount = str(row[p.amount_column]).strip()
                amount = self._parse_amount(raw_amount, p.amount_sign)

                # マイナス金額（返金など）は処理対象に含める
                if amount is None:
                    continue

                # 店名
                merchant = str(row[p.merchant_column]).strip()
                if not merchant or merchant in ("nan", "NaN", "None"):
                    continue

                # 摘要 (オプション)
                memo = ""
                if p.memo_column and p.memo_column in row.index:
                    memo_val = row[p.memo_column]
                    if pd.notna(memo_val):
                        memo = str(memo_val).strip()

                tx = Transaction(
                    date=parsed_date,
                    merchant_name=merchant,
                    amount=amount,
                    memo=memo,
                    raw_row={k: str(v) if pd.notna(v) else "" for k, v in row.items()},
                )
                transactions.append(tx)

            except (KeyError, ValueError) as e:
                # 行のパースに失敗した場合はスキップして続行
                import warnings
                warnings.warn(f"行のパース失敗 (スキップ): {e}", stacklevel=2)
                continue

        return transactions

    def _parse_date(self, raw: str, fmt: str) -> date:
        """文字列の日付をdateオブジェクトに変換する。"""
        from datetime import datetime
        # 全角数字を半角に変換
        raw = raw.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        return datetime.strptime(raw, fmt).date()

    def _parse_amount(self, raw: str, sign: str) -> Decimal | None:
        """金額文字列をDecimalに変換する。符号の反転も処理。"""
        # カンマ・通貨記号・空白を除去
        clean = raw.replace(",", "").replace("¥", "").replace("円", "").strip()
        if not clean or clean in ("nan", "NaN", "-", ""):
            return None
        try:
            amount = Decimal(clean)
        except Exception:
            return None

        # amount_sign: "negative" の場合は符号を反転して正の値にする
        if sign == "negative":
            amount = -amount

        return amount
