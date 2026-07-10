# PC-off ホスティング: Oracle Always Free VM + Tailscale

PC を起動していなくても投資AIアシスタントを使えるようにする構成。
月額 **0円** (Oracle Cloud Always Free 枠 + Tailscale 無料プラン)。

```
iPhone ──(Tailscale/WireGuard)──> invest-vm (Oracle Cloud)
                                    └─ https://invest-vm.tail038f4f.ts.net
                                       └─ 127.0.0.1:8000 (systemd 常駐)
```

## セキュリティ設計 (万全方針)

| レイヤ | 対策 |
|---|---|
| ネットワーク | 公開ポートを一切開けない。アクセスは tailnet (WireGuard 暗号化) 経由のみ |
| OCI 側 | Security List の受信ルールを全削除 (SSH 22 も閉じる) |
| VM 側 | ufw で受信全拒否 + tailscale0 のみ許可 (二重防御) |
| SSH | Tailscale SSH (tailnet 内デバイスのみ・鍵管理不要) |
| OS | unattended-upgrades でセキュリティパッチ自動適用 |
| 秘密情報 | `.env.local` は git 管理外。転送は tailnet 経由の scp のみ |

## 初回セットアップ手順 (ユーザー作業 ≈ 30分)

### 1. Oracle Cloud アカウント作成
https://www.oracle.com/jp/cloud/free/ から登録 (クレジットカード必要だが Always Free 枠は課金なし)。ホームリージョンは **Japan East (Tokyo)** か **Japan Central (Osaka)** を選ぶ (後から変更不可)。

### 2. Tailscale Auth key を発行
https://login.tailscale.com/admin/settings/keys → **Generate auth key**
- Reusable: off / Expiration: 短め / Pre-approved: on

### 3. VM を作成
OCI コンソール → Compute → Instances → Create Instance:
- **Image**: Ubuntu 24.04 (aarch64)
- **Shape**: Ampere **VM.Standard.A1.Flex — 2 OCPU / 12GB RAM** (Always Free 枠は合計 4 OCPU / 24GB まで)
- **Boot volume**: 50GB (デフォルトで可)
- **詳細オプション → cloud-init**: `cloud-init.yaml` の中身を貼り付け (先に `TS_AUTHKEY_HERE` を手順2のキーに置換)
- SSH 公開鍵欄は空でよい (Tailscale SSH を使うため)

### 4. 起動確認 (約5〜10分後)
- Tailscale 管理画面 (https://login.tailscale.com/admin/machines) に **invest-vm** が現れる
- PC から: `tailscale ssh ubuntu@invest-vm` で入れることを確認
- `curl -s http://127.0.0.1:8000/api/health` が VM 内で 200 を返すことを確認
  (初回は pip の torch ダウンロードで setup に 10分程度かかる場合あり。
   進捗は `sudo tail -f /var/log/cloud-init-output.log`)

### 5. 【重要】公開側の入口を閉じる
tailnet SSH が通ることを確認**してから**:
OCI コンソール → Networking → VCN → Security List → **Ingress Rules をすべて削除** (22/tcp 含む)。
これで VM はインターネット側から一切見えなくなる。

### 6. データと APIキー を PC から送る
PC 側 (このリポジトリ直下) で:
```powershell
powershell -ExecutionPolicy Bypass -File ops\cloud\sync-data.ps1
```
`data/` (市場データ・RAGインデックス)、`local_docs/` (RAGコーパス)、`.env.local` (GEMINI_API_KEY) を送り、サービスを再起動してヘルスチェックまで行う。

### 7. iPhone から使う
Tailscale アプリを ON にして https://invest-vm.tail038f4f.ts.net を開く。

## 運用

- **コード更新**: `tailscale ssh ubuntu@invest-vm` → `bash ~/Web-Scraping/ops/cloud/setup-app.sh` (git pull + 依存更新 + build + 再起動まで一括)
- **データ更新**: PC 側で `sync-data.ps1` を再実行
- **ログ**: `journalctl -u investment-assistant -f`
- **PC 側サーバはそのまま残る**: VM に問題があっても従来どおり https://nobe.tail038f4f.ts.net が使える (ロールバック不要の並行運用)

## 制約・既知の注意

- Always Free の A1 枠はリージョンによって在庫切れで作成に失敗することがある ("Out of capacity")。時間を置いて再試行するか、1 OCPU / 6GB に下げる。
- データの自動更新 (morning-refresh 相当) は VM ではまだ未設定 — 当面は PC 側で更新して `sync-data.ps1` で送る運用。VM 上の cron 化は次スプリント候補。
