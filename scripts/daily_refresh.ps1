# 毎日のファイナンスデータ自動更新（Windows タスクスケジューラから起動）。
# 事前に一度だけ: market-universe-build でユニバースCSVを作成しておくこと。
# 個人利用・非助言。Yahoo の利用規約と各自の責任の範囲で実行してください。

$ErrorActionPreference = "Stop"
$Repo = "C:\Users\ynobe\Documents\GitHub\Web-Scraping"   # ← 自分のパスに合わせる
Set-Location $Repo

# robots バイパス（個人利用の許可済み設定）
$env:MARKET_ALLOW_ROBOTS_BYPASS = "1"
$env:MARKET_DOMESTIC_UNIVERSE_PATH = "$Repo\local_docs\market\domestic_universe.csv"

$log = "$Repo\local_docs\logs\daily_refresh_{0:yyyyMMdd}.log" -f (Get-Date)
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

# 全工程: OHLCV -> daily_bars.csv 集約 -> 財務 -> RAG(予測込み)再構築。
#
# Python は進捗ログを stderr に出す。PowerShell でそのまま実行すると stderr 行を
# NativeCommandError 扱いして中断/警告表示してしまうため、リダイレクトは cmd 側で行い
# stdout/stderr をまとめてログへ書く（PowerShell に stderr を渡さない）。これで
# NativeCommandError は発生しない。本当の成否は終了コードで判定する。
#
# まずは控えめ(--range 6mo --max 100)で確実に完走させ、安定したら増やす:
#   全件は --max 0、精度重視は --range 1y（重いので早朝起動推奨）。
$py = "python -m investment_assistant.cli market-daily-refresh --range 6mo --max 100"
cmd /c "$py 1> ""$log"" 2>&1"
$code = $LASTEXITCODE

Write-Host "---- log tail ----"
Get-Content $log -Tail 12 -ErrorAction SilentlyContinue

# python の終了コードをタスクスケジューラに伝播する。
# これが無いと、取得が失敗しても LastTaskResult が 0(成功) になり、
# 「毎朝ちゃんと動いているか」の判定が当てにならなくなる。
if ($code -ne 0) {
  Add-Content -Path $log -Value "ERROR: market-daily-refresh exited with code $code"
}
exit $code
