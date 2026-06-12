import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

type RootErrorBoundaryState = {
  error: unknown;
};

class RootErrorBoundary extends React.Component<
  React.PropsWithChildren,
  RootErrorBoundaryState
> {
  state: RootErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): RootErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: unknown, info: React.ErrorInfo) {
    console.error("App render failed", error, info);
  }

  render() {
    if (!this.state.error) {
      return this.props.children;
    }
    const message =
      this.state.error instanceof Error
        ? this.state.error.message
        : String(this.state.error);
    return (
      <main className="fatal-screen">
        <section>
          <p className="eyebrow">表示エラー</p>
          <h1>画面を表示できませんでした</h1>
          <p>
            アプリの起動中にエラーが発生しました。開発サーバーを再読み込みすると復旧する場合があります。
          </p>
          <pre>{message}</pre>
          <button onClick={() => window.location.reload()}>再読み込み</button>
        </section>
      </main>
    );
  }
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <App />
    </RootErrorBoundary>
  </React.StrictMode>,
);

async function clearDevelopmentServiceWorkers() {
  const registrations = await navigator.serviceWorker.getRegistrations();
  await Promise.all(registrations.map((registration) => registration.unregister()));
  if ("caches" in window) {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => caches.delete(key)));
  }
}

if ("serviceWorker" in navigator) {
  if (import.meta.env.PROD) {
    window.addEventListener("load", () => {
      void navigator.serviceWorker.register("/sw.js").catch(() => {});
    });
  } else {
    void clearDevelopmentServiceWorkers().catch(() => {});
  }
}
