# モバイル配布ガイド（PWA / App Store / Google Play）

このアプリは **Webフロント（`web/`）＋ Python バックエンド（`investment_assistant.webapi`）** の構成です。
スマホで使う方法は段階的に3つあります。

| 方法 | 手間 | ストア審査 | 推奨度 |
|------|------|-----------|--------|
| ① PWA（ホーム画面に追加） | 最小（実装済み） | 不要 | ★ まずこれ |
| ② Google Play（TWA） | 小 | あり | ★ Android配布 |
| ③ iOS/Android ネイティブ（Capacitor） | 中 | あり | iOS配布したい時 |

> **重要（共通の前提）**: スマホ上のアプリから**バックエンドに到達できる必要**があります。
> - **PWA** はバックエンドのURLから配信されるので、そのまま `/api` に届きます（同一オリジン）。
> - **TWA / Capacitor** で“アプリ単体”として配るなら、**バックエンドをどこかにホスティング**し、
>   フロントの **`VITE_API_BASE`** にそのURLを指定してビルドします（下記）。バックエンドのCORS許可も必要です。

---

## ① PWA（実装済み・いちばん簡単）

1. バックエンドを起動し、フロントを **HTTPSのURL**で開く（Codespacesの転送URLはhttps）。
2. スマホのブラウザで：
   - **Android/Chrome**: 「アプリをインストール」バナー、または ⋮ →「アプリをインストール」。
   - **iOS/Safari**: 共有 → **「ホーム画面に追加」**。
3. ホームのアイコンから**全画面アプリ**として起動。オフラインでもシェルは開きます。

`web/public/manifest.webmanifest`・`icon.svg`・`sw.js` が同梱済みです。

---

## ②  Google Play（TWA / Bubblewrap）— PWAをそのままAndroidアプリに

前提：PWAが**公開HTTPS URL**で配信されていること（`manifest` と `sw.js` が有効）。

```bash
npm i -g @bubblewrap/cli
bubblewrap init --manifest https://<あなたのPWAのURL>/manifest.webmanifest
bubblewrap build         # 署名付き .aab / .apk を生成
```

- 生成された **`.aab`** を Google Play Console にアップロードして審査申請。
- `assetlinks.json`（Digital Asset Links）をサイトの `/.well-known/` に置くと、URLバーなしの全画面TWAになります（Bubblewrapが案内）。
- アイコンは現状SVG。Playは各サイズのPNGを推奨するので、必要なら `web/public/` にPNGアイコンを追加。

---

## ③ iOS / Android ネイティブ（Capacitor）— App Store も可

`web/` のビルド成果物（`dist/`）をネイティブの WebView でラップします。

### セットアップ
```bash
cd web
npm i -D @capacitor/cli
npm i @capacitor/core @capacitor/ios @capacitor/android

# バックエンドのホスト先を指定してビルド（同一オリジンが無いため必須）
VITE_API_BASE="https://<あなたのバックエンドURL>" npm run build

npx cap init "Investment Assistant" "com.example.investassist" --web-dir=dist
npx cap add ios
npx cap add android
npx cap copy
```

### `web/capacitor.config.ts`（`cap init` で生成。手書きする場合の例）
```ts
import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.example.investassist",
  appName: "Investment Assistant",
  webDir: "dist",
  // 既定の splash / status bar はお好みで
};

export default config;
```

### ビルド・申請
```bash
npx cap open ios       # Xcode が開く → 署名 → Archive → App Store Connect へ
npx cap open android   # Android Studio が開く → 署名付き .aab → Play へ
```

- **iOS の申請には Mac + Xcode + Apple Developer Program（有料）** が必要です。
- アプリ更新時は `npm run build && npx cap copy` を回してから再ビルド。

---

## バックエンドのホスティングと CORS（②③共通）

“アプリ単体”配布では、`investment_assistant.webapi` を**公開サーバー**で動かし、HTTPSで公開します。
- フロントは `VITE_API_BASE` でそのURLを向く（②のTWAはPWA配信元がそのままAPI元なので原則不要）。
- バックエンドは**アプリのオリジンからのCORS**を許可する必要があります
  （Capacitorは `capacitor://localhost` や `https://localhost`、TWAは配信ドメイン）。
- `EDINET_API_KEY` / `GEMINI_API_KEY` はサーバー側の環境変数に設定（アプリには含めない）。

> セキュリティ上、公開時は認証・レート制限・HTTPSを必ず付けてください。これは個人/ローカル用途を
> 前提とした構成のため、一般公開する場合はアクセス制御の追加が前提です。

---

## まとめ
- **今すぐ**：① PWA でホーム画面に追加（実装済み）。
- **Android配布**：② Bubblewrap で Play。
- **iOS/App Store**：③ Capacitor（Mac/Xcode/Developer Program 必須）。
- フロントは `VITE_API_BASE` でAPI先を切替可能（既定=同一オリジン＝Web/PWA）。
