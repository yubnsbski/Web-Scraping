# 投資特化・非助言MVP

このMVPは、日本株と投信の保有分析、条件フィルタ型の候補抽出、NISA枠、配当/分配金見込み、根拠付き投資レポートに集中する。家計、銀行明細、支出予測、家計ベンチマーク、自動売買、証券口座注文連携は対象外。

## 入力

保有CSVの必須列:

```csv
asset_type,ticker_or_fund_code,name,quantity,avg_cost,account_type,tax_wrapper,source
```

任意列:

```csv
current_price,annual_income,distribution_per_unit
```

投信プロファイルCSVの必須列:

```csv
fund_code,name,asset_class,expense_ratio,distribution_policy,nisa_eligible,provider_id
```

任意列:

```csv
diversification_score
```

サンプル:

- `examples/investment_holdings_sample.csv`: 日本株と投信が混在した保有CSV。
- `examples/investment_funds_sample.csv`: 投信候補抽出用のプロファイルCSV。
- `examples/financials_sample.csv`: EDINET由来財務の開発用サンプル。

## API

- `POST /api/holdings/import`: 保有CSV/JSONを正規化する。
- `POST /api/portfolio/analyze`: 評価額、評価損益、配当/分配金見込み、NISA枠、集中度を決定論で集計する。
- `POST /api/candidates/screen`: 日本株と投信を条件一致で抽出する。推奨順位ではなく比較対象の提示。
- `POST /api/reports/investment-monthly`: 保有分析と候補抽出結果から、根拠・計算式付きの月次レポートを生成する。

サンプルCSVを使った最小確認:

```json
POST /api/portfolio/analyze
{
  "path": "examples/investment_holdings_sample.csv",
  "financials_csv": "examples/financials_sample.csv"
}
```

レポートの重要KPIは、`evidence_keys`、`formula`、`last_updated`、`disclaimer` を持つ。

## データ方針

本番モードでは、契約済みとして明示されていない市場価格providerを拒否する。EDINET、手入力、ユーザーCSVは許容し、J-Quants、yfinance、Stooq等の未契約providerは本番配信系に使わない。

## 境界

候補抽出は「条件に一致した比較対象の提示」に限る。個別銘柄の買付、売却、保有継続を断定的に推奨しない。最終的な投資判断はユーザー本人が行う。
