// Sticky bottom composer: auto-growing textarea, send/mic buttons, mode
// toggle, real-AI toggle + budget meter, and a collapsed "detailed settings"
// disclosure. Voice input uses the (non-standard, Chrome/Edge-only) Web
// Speech API, feature-detected so it degrades to no mic button everywhere
// else -- entirely client-side, no backend involvement.
import { forwardRef, useEffect, useRef, useState, type MutableRefObject } from "react";
import type { BudgetInfo, ChatMode, SourceMode } from "./types";

// Minimal local typing for the Web Speech API: it is not part of the
// standard DOM lib, so we declare just enough surface here rather than
// augmenting the global scope.
interface SpeechRecognitionResultLike {
  0: { transcript: string };
  isFinal: boolean;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start(): void;
  stop(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  const ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as SpeechRecognitionCtor | undefined;
  return ctor ?? null;
}

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  sending: boolean;
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  sourceMode: SourceMode;
  onSourceModeChange: (mode: SourceMode) => void;
  realAi: boolean;
  onRealAiChange: (value: boolean) => void;
  budgetInfo: BudgetInfo | null;
  dbPath: string;
  onDbPathChange: (value: string) => void;
  limit: number;
  onLimitChange: (value: number) => void;
}

export const Composer = forwardRef<HTMLTextAreaElement, ComposerProps>(function Composer(props, forwardedRef) {
  const localRef = useRef<HTMLTextAreaElement | null>(null);
  const [listening, setListening] = useState(false);
  const [micAvailable, setMicAvailable] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const baseTextRef = useRef<string>("");
  const SpeechRecognitionCtorRef = useRef<SpeechRecognitionCtor | null>(null);

  // Feature-detect client-side only (guards against any SSR/build-time
  // evaluation where `window` would be undefined).
  useEffect(() => {
    const ctor = getSpeechRecognitionCtor();
    SpeechRecognitionCtorRef.current = ctor;
    setMicAvailable(ctor !== null);
  }, []);

  useEffect(() => {
    const el = localRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [props.value]);

  const setRefs = (el: HTMLTextAreaElement | null) => {
    localRef.current = el;
    if (typeof forwardedRef === "function") forwardedRef(el);
    else if (forwardedRef) (forwardedRef as MutableRefObject<HTMLTextAreaElement | null>).current = el;
  };

  const send = () => {
    const text = props.value.trim();
    if (!text || props.sending) return;
    stopListening();
    props.onSend(text);
  };

  const stopListening = () => {
    recognitionRef.current?.stop();
  };

  const toggleListening = () => {
    const Ctor = SpeechRecognitionCtorRef.current;
    if (!Ctor) return;
    if (listening) {
      stopListening();
      return;
    }
    const recognition = new Ctor();
    recognition.lang = "ja-JP";
    recognition.interimResults = true;
    recognition.continuous = true;
    baseTextRef.current = props.value ? `${props.value} ` : "";
    recognition.onresult = (event) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i]!;
        if (result.isFinal) final += result[0].transcript;
        else interim += result[0].transcript;
      }
      if (final) {
        baseTextRef.current = `${baseTextRef.current}${final}`;
        props.onChange(baseTextRef.current);
      } else {
        props.onChange(`${baseTextRef.current}${interim}`);
      }
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  };

  return (
    <div className="composer">
      <div className="composer-toprow">
        <div className="composer-mode-toggle" role="tablist" aria-label="回答モード">
          <button
            type="button"
            className={props.mode === "answer" ? "composer-mode-btn active" : "composer-mode-btn"}
            onClick={() => props.onModeChange("answer")}
          >
            かんたん
          </button>
          <button
            type="button"
            className={props.mode === "detailed" ? "composer-mode-btn active" : "composer-mode-btn"}
            onClick={() => props.onModeChange("detailed")}
            title="3案生成→批評→統合の多段処理（通常より時間がかかります）"
          >
            詳細分析
          </button>
        </div>
        <div className="composer-source-toggle" role="tablist" aria-label="検索範囲">
          <button
            type="button"
            className={props.sourceMode === "rag" ? "composer-source-btn active" : "composer-source-btn"}
            onClick={() => props.onSourceModeChange("rag")}
            title="蓄積したローカル文書だけを根拠に回答します"
          >
            ローカル
          </button>
          <button
            type="button"
            className={props.sourceMode === "web" ? "composer-source-btn active" : "composer-source-btn"}
            onClick={() => props.onSourceModeChange("web")}
            title="Gemini の Google 検索グラウンディングでWeb情報を根拠に回答します"
          >
            Web
          </button>
          <button
            type="button"
            className={props.sourceMode === "auto" ? "composer-source-btn active" : "composer-source-btn"}
            onClick={() => props.onSourceModeChange("auto")}
            title="まずローカル文書を検索し、根拠が見つからない場合のみWeb検索します"
          >
            自動
          </button>
        </div>
        <label className="composer-realai">
          <input
            type="checkbox"
            checked={props.realAi}
            onChange={(e) => props.onRealAiChange(e.target.checked)}
          />
          本物のAI (Gemini)
        </label>
        {props.realAi && props.budgetInfo && (
          <span className={props.budgetInfo.warning ? "badge warn" : "badge ready"}>
            残り {String(props.budgetInfo.daily_remaining)}/{String(props.budgetInfo.hard_daily_limit)}
          </span>
        )}
      </div>

      <div className="composer-box">
        <textarea
          ref={setRefs}
          className="composer-textarea"
          value={props.value}
          placeholder="質問を入力（Enterで送信、Shift+Enterで改行）"
          rows={1}
          onChange={(e) => props.onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <div className="composer-actions">
          {micAvailable && (
            <button
              type="button"
              className={listening ? "composer-mic listening" : "composer-mic"}
              onClick={toggleListening}
              aria-pressed={listening}
              aria-label={listening ? "音声入力を停止" : "音声入力を開始"}
              title={listening ? "音声入力を停止" : "音声入力"}
            >
              🎤
            </button>
          )}
          <button
            type="button"
            className="composer-send primary"
            onClick={send}
            disabled={props.sending || !props.value.trim()}
          >
            送信
          </button>
        </div>
      </div>

      <details className="composer-advanced">
        <summary>詳細設定</summary>
        <div className="composer-advanced-grid">
          <label>
            <span>件数</span>
            <input
              value={String(props.limit)}
              inputMode="numeric"
              onChange={(e) => props.onLimitChange(Number(e.target.value) || props.limit)}
            />
          </label>
          <label>
            <span>RAG DB</span>
            <input value={props.dbPath} onChange={(e) => props.onDbPathChange(e.target.value)} />
          </label>
        </div>
      </details>
    </div>
  );
});
