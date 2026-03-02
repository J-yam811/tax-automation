"""CLIエントリポイント - Click ベースのコマンドラインインターフェース"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import __version__
from .config import list_available_profiles, load_card_profile, load_categories, load_rules
from .exporters.csv_exporter import CsvExporter


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


@click.group()
@click.version_option(__version__, prog_name="tax")
def tax() -> None:
    """確定申告自動化ツール - クレジットカード明細を自動仕訳します。

    \b
    使い方:
      tax process data/input/my_card.csv --profile rakuten
      tax process data/input/my_card.csv --profile generic --no-gemini
      tax profiles
    """
    pass


@tax.command()
@click.argument("input_csv", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--profile", "-p",
    required=False,
    default=None,
    help="カードプロファイル名 (例: rakuten, epos) またはYAMLファイルパス。省略時は自動検出。",
)
@click.option(
    "--output", "-o",
    default=None,
    type=click.Path(path_type=Path),
    help="出力CSVファイルパス (省略時は data/output/output_YYYYMMDD_HHMMSS.csv)",
)
@click.option(
    "--year",
    default=None,
    type=int,
    help="特定の年のトランザクションのみ出力 (例: 2025)",
)
@click.option(
    "--no-gemini",
    is_flag=True,
    default=False,
    help="Gemini APIを使わない (ルールのみで分類、未分類は「雑費」)",
)
@click.option(
    "--business-ratio",
    default=1.0,
    type=click.FloatRange(0.0, 1.0),
    help="事業割合のデフォルト値 0.0〜1.0 (デフォルト: 1.0 = 100%%)",
    show_default=True,
)
@click.option(
    "--rules",
    default=None,
    type=click.Path(path_type=Path),
    help="仕訳ルールYAMLのパス (省略時は config/rules.yaml)",
)
@click.option(
    "--categories",
    default=None,
    type=click.Path(path_type=Path),
    help="勘定科目YAMLのパス (省略時は config/categories.yaml)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="CSV出力せずに分類結果のみ確認する",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="各トランザクションの分類結果を表示する",
)
def process(
    input_csv: Path,
    profile: str,
    output: Path | None,
    year: int | None,
    no_gemini: bool,
    business_ratio: float,
    rules: Path | None,
    categories: Path | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """クレジットカードCSVを読み込んで仕訳分類しCSVに出力します。

    \b
    例:
      tax process data/input/rakuten_2025.csv --profile rakuten --year 2025
      tax process data/input/my_card.csv --profile generic --no-gemini --verbose
      tax process data/input/epos.csv --profile epos --business-ratio 0.8
    """
    _setup_logging(verbose)

    from .pipeline import Pipeline

    click.echo(f"処理開始: {input_csv}")
    if profile:
        click.echo(f"プロファイル: {profile}")
    else:
        click.echo("プロファイル: 自動検出")

    try:
        pipeline = Pipeline(
            profile_name=profile,
            rules_path=rules,
            categories_path=categories,
            use_gemini=not no_gemini,
            default_business_ratio=business_ratio,
        )
        transactions, stats = pipeline.run(
            input_csv=input_csv,
            output_csv=output,
            year=year,
            dry_run=dry_run,
            verbose=verbose,
        )
        if not profile and pipeline.detected_profile_name:
            click.echo(f"検出されたプロファイル: {pipeline.detected_profile_name}")
    except FileNotFoundError as e:
        click.echo(f"エラー: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"予期しないエラー: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    # 統計表示
    click.echo()
    click.echo("=" * 40)
    click.echo("処理結果")
    click.echo("=" * 40)
    click.echo(stats.summary())

    # 勘定科目別サマリー表示
    if transactions:
        click.echo()
        exporter = CsvExporter()
        click.echo(exporter.export_summary(transactions, year=year))

    if dry_run:
        click.echo()
        click.echo("(ドライラン: CSVファイルは出力されませんでした)")


@tax.command()
def profiles() -> None:
    """利用可能なカードプロファイルの一覧を表示します。"""
    available = list_available_profiles()
    if not available:
        click.echo("プロファイルが見つかりません。config/card_profiles/ を確認してください。")
        return

    click.echo("利用可能なカードプロファイル:")
    click.echo()
    for name in available:
        try:
            profile = load_card_profile(name)
            click.echo(f"  {name:<15} - {profile.name}")
        except Exception:
            click.echo(f"  {name:<15} - (読み込みエラー)")

    click.echo()
    click.echo("使い方: tax process input.csv --profile <プロファイル名>")
    click.echo("または: tax process input.csv --profile config/card_profiles/my_card.yaml")


@tax.command()
def rules() -> None:
    """現在の仕訳ルール一覧を表示します。"""
    rule_list = load_rules()
    if not rule_list:
        click.echo("ルールが設定されていません。config/rules.yaml を確認してください。")
        return

    click.echo(f"仕訳ルール ({len(rule_list)}件, priority降順):")
    click.echo()
    current_category = None
    for rule in rule_list:
        if rule.category_code != current_category:
            current_category = rule.category_code
            click.echo(f"  [{rule.category_code}]")
        kw_preview = ", ".join(rule.keywords[:3])
        if len(rule.keywords) > 3:
            kw_preview += f" ... 他{len(rule.keywords) - 3}件"
        click.echo(f"    priority={rule.priority:2d}  {kw_preview}")
    click.echo()


@tax.command()
def categories() -> None:
    """勘定科目マスタの一覧を表示します。"""
    cat_list = load_categories()
    if not cat_list:
        click.echo("勘定科目が設定されていません。config/categories.yaml を確認してください。")
        return

    click.echo(f"勘定科目マスタ ({len(cat_list)}件):")
    click.echo()
    for cat in cat_list:
        deductible = "経費計上可" if cat.is_deductible else "経費計上不可"
        click.echo(f"  {cat.code:<12} {cat.name_ja:<15} ({deductible})")
        if cat.description:
            click.echo(f"    {cat.description}")
    click.echo()
