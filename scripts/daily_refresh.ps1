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

# Python は進捗ログを stderr に出力する。$ErrorActionPreference = "Stop" のままだと
# PowerShell がその stderr 行を NativeCommandError(致命的)扱いして最初のログで中断する。
# 取得処理の本当の成否は終了コードで判定するので、ここだけ Continue にする。
$ErrorActionPreference = "Continue"

# 全工程: OHLCV -> daily_bars.csv 集約 -> 財務 -> RAG(予測込み)再構築
# まずは --max 300 程度で運用し、安定したら 0(全件) に。全件1年は数時間かかります。
python -m investment_assistant.cli market-daily-refresh `
  --range 1y --max 300 2>&1 | Tee-Object -FilePath $log

# python の終了コードをタスクスケジューラに伝播する。
# これが無いと、取得が失敗しても LastTaskResult が 0(成功) になり、
# 「毎朝ちゃんと動いているか」の判定が当てにならなくなる。
$code = $LASTEXITCODE
if ($code -ne 0) {
  Add-Content -Path $log -Value "ERROR: market-daily-refresh exited with code $code"
}
exit $code
