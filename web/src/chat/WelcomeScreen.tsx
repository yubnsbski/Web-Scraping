// Centered landing view shown when the active conversation has no messages
// yet -- Claude-style empty state with branding, a primary CTA that focuses
// the composer, and a few one-tap suggestion chips.
const SUGGESTIONS = [
  "KDDIの配当利回りは？",
  "高配当銘柄の根拠を探す",
  "保有の減配リスクを確認",
  "自己資本比率の推移を確認",
];

export function WelcomeScreen(props: { onStart: () => void; onSuggestion: (text: string) => void }) {
  return (
    <div className="chat-welcome">
      <div className="chat-welcome-inner">
        <p className="chat-welcome-eyebrow">non-advisory investment workflow</p>
        <h1 className="chat-welcome-title">投資AIアシスタント</h1>
        <p className="chat-welcome-tagline">根拠つきで、配当・銘柄・保有を一緒に確認します。</p>
        <button className="chat-welcome-cta" onClick={props.onStart}>
          タップして開始
        </button>
        <div className="chat-welcome-suggestions">
          {SUGGESTIONS.map((text) => (
            <button key={text} className="chat-suggestion-chip" onClick={() => props.onSuggestion(text)}>
              {text}
            </button>
          ))}
        </div>
        <p className="chat-welcome-note">売買推奨・自動売買は行いません。判断材料と根拠を整理します。</p>
      </div>
    </div>
  );
}
