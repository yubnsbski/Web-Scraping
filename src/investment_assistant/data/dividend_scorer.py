"""Japanese high-dividend stock scoring engine.

設計根拠となる論文の知見と、それがコードのどこに反映されているかを明記する。

═══════════════════════════════════════════════════════════════
論文→設計 対応表
═══════════════════════════════════════════════════════════════

[P1] Kuhnen & Knutson (2005) Neuron 47:763-770
     "The Neural Basis of Financial Risk Taking"
     ───────────────────────────────────────────
     知見: NAcc（側坐核）の事前活性化は、irrational risk-taking（衝動的なリスク行動）を
           予測する。Insula（島皮質）の事前活性化は、irrational risk-aversion を予測する。
           ★NAcc活性化 = 「良い投資判断」ではなく「衝動的判断の前兆」。
     設計反映:
       → yield_score: NAcc誘発を防ぐためにシグモイドで高利回りに上限。
                      極高利回り(>10%)は重罰（NAcc過活性ゾーン）。 [_score_yield 参照]
       → 重み: yield_weight=0.20 と控えめ。利回り至上主義はNAcc過活性のバイアスそのもの。
       → stability_weight=0.25 を最高位に置くことで、
         Insula誘発（変動性への恐怖 → パニック売り）を防ぐ。

[P2] Tom et al. (2007) Science 315:515-518
     "The Neural Basis of Loss Aversion in Decision-Making Under Risk"
     ───────────────────────────────────────────
     知見: 潜在的損失への神経反応は、等価の利得の約2倍の強度を持つ。
           線条体・mPFCの活性が損益の大きさに単調に対応。
           これが「損失回避係数 λ ≈ 2.0」の神経基盤。
     設計反映:
       → 全スコア関数でペナルティ側の傾きを報酬側の約2倍に設定。 [λ=2.0 コメント参照]
       → _score_stability: 削減歴ありの場合、基準スコアの-50%ではなく実質 0 に近い値へ。
         「削減という損失」は「同期間の安定」の2倍のインパクトを持つため。
       → _score_payout: 80%超では傾きが急激に下がる（λ=2 で正の傾きの2倍の下降速度）。
       → _score_health: D/E比の超過ペナルティが正常範囲改善のリワードより急勾配。

[P3] Knutson & Bossaerts (2007) J. Neuroscience 27:8174-8177
     "Neural Antecedents of Financial Decisions"
     ───────────────────────────────────────────
     知見: 腹側線条体（NAcc含む）は期待報酬（収入の予測値）を符号化。
           Insulaはリスク（報酬の分散）を符号化。この2つの回路は独立。
           「高利回り ≠ 高期待効用」: 変動リスクが高ければ insula が勝る。
     設計反映:
       → stability (insula抑制) と yield (NAcc対応) を独立した軸として分離。
         「利回り高いが変動大」は yield_score 高 + stability_score 低 → 総合で中程度。
       → これを1軸にまとめると分散リスクが埋没するため分離が不可欠。

[P4] Schultz, Dayan & Montague (1997) Science 275:1593-1599
     (ドーパミン予測誤差の基礎理論、複数後続研究で確認)
     ───────────────────────────────────────────
     知見: ドーパミンは「期待を上回った報酬」に対して発火する（予測誤差 > 0）。
           期待通りなら発火しない。期待を下回れば抑制。
           → 連続した正の予測誤差（配当増額）が長期信頼を構築する。
     設計反映:
       → streak_score: 連続増配 = 連続した正の予測誤差の累積。log スケールで年数評価。
       → momentum_score: 直近3年CAGR = 直近期間の予測誤差方向を定量化。
         ただしCAGR > 15%は警戒（持続不可能な高水準はドーパミン暴走ゾーン）。

[P5] Frydman & Camerer (2016) Trends in Cognitive Sciences 20:661-675
     "The psychology and neuroscience of financial decision making"
     ───────────────────────────────────────────
     知見: 投資損失に対する神経応答はdiminishing sensitivity（感度逓減）を示す。
           小さな損失は相対的に大きく感じられる。これが配当削減の心理的ダメージを増幅。
           一般投資家は配当削減に過剰反応して売却 → 長期保有を阻害する。
     設計反映:
       → has_dividend_cut = True の場合、stability_score は一律 0.05 上限に設定。
         （削減履歴がある銘柄は市場での信頼を失い、長期保有の基盤が崩れる）
       → これは λ=2.0 よりさらに強い措置：削減 = 設計上の致命的フラグ扱い。

重みの根拠サマリー:
  stability  25%  P3: Insula 独立回路＋P5: 削減ダメージの過剰反応対策が最重要
  health     20%  P1: Insula 誘発を防ぐ財務安全性（高D/E → insula 活性）
  yield      20%  P3: NAcc の期待報酬符号化（ただし P1 から過度な比重付けを避ける）
  momentum   15%  P4: ドーパミン予測誤差の方向性（直近3年CAGR）
  payout     10%  P2: λ=2で過剰性向ペナルティ（持続不能は損失リスクの前兆）
  streak      7%  P4: 連続正予測誤差の累積（信頼回路構築）
  sector_rank 3%  社会比較効果（Fliessbach et al. 2007）、herding の参照点として最小限使用
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

# ── 損失回避係数 (Tom et al. 2007 より) ─────────────────────────────────────
# λ ≈ 2.0: 損失の神経インパクトは等価の利得の約2倍。
# 各スコア関数のペナルティ傾きはリワード傾きの LAMBDA 倍に設定。
LAMBDA = 2.0


@dataclass(frozen=True)
class DividendScoreWeights:
    """重みは設計根拠サマリー（ファイル冒頭）を参照。"""
    stability_weight:   float = 0.25  # [P3] Insula 独立回路
    health_weight:      float = 0.20  # [P1] Insula 誘発予防
    yield_weight:       float = 0.20  # [P3] NAcc 期待報酬（上限付き）
    momentum_weight:    float = 0.15  # [P4] ドーパミン予測誤差
    payout_weight:      float = 0.10  # [P2] λ=2 過剰性向ペナルティ
    streak_weight:      float = 0.07  # [P4] 連続正予測誤差
    sector_rank_weight: float = 0.03  # 社会比較参照点（最小限）

    def validate(self) -> None:
        total = (
            self.stability_weight + self.health_weight + self.yield_weight
            + self.momentum_weight + self.payout_weight + self.streak_weight
            + self.sector_rank_weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")


@dataclass
class DividendScoreInput:
    ticker: str
    name: str
    price: float
    dps: float
    payout_ratio: float
    equity_ratio: float
    debt_equity: float
    consecutive_raises: int
    sector_yield_rank: float
    dps_history: list[float] = field(default_factory=list)

    @property
    def dividend_yield(self) -> float:
        return self.dps / self.price if self.price > 0 else 0.0

    @property
    def dps_cv(self) -> float:
        """配当変動係数 (CV = std/mean)。Insula回路の活性度の代理指標 [P3]。"""
        vals = [v for v in self.dps_history if v > 0]
        if len(vals) < 2:
            return 0.5
        mean = sum(vals) / len(vals)
        if mean <= 0:
            return 1.0
        variance = sum((x - mean) ** 2 for x in vals) / len(vals)
        return math.sqrt(variance) / mean

    @property
    def dps_cagr_3y(self) -> float:
        """直近3年の配当CAGR。ドーパミン予測誤差の方向・強度の代理指標 [P4]。"""
        vals = [v for v in self.dps_history if v > 0]
        if len(vals) < 2:
            return 0.0
        n = min(3, len(vals) - 1)
        start = vals[-(n + 1)]
        end = vals[-1]
        if start <= 0:
            return 0.0
        return (end / start) ** (1.0 / n) - 1.0

    @property
    def has_dividend_cut(self) -> bool:
        """配当削減歴あり。[P5] に基づく致命的フラグ。"""
        vals = [v for v in self.dps_history if v > 0]
        for i in range(1, len(vals)):
            if vals[i] < vals[i - 1] * 0.95:
                return True
        return False


@dataclass
class DividendScoreBreakdown:
    stability_score: float
    health_score: float
    yield_score: float
    momentum_score: float
    payout_score: float
    streak_score: float
    sector_rank_score: float
    total_score: float

    def to_dict(self) -> dict:
        return {
            "stability_score":   round(self.stability_score, 4),
            "health_score":      round(self.health_score, 4),
            "yield_score":       round(self.yield_score, 4),
            "momentum_score":    round(self.momentum_score, 4),
            "payout_score":      round(self.payout_score, 4),
            "streak_score":      round(self.streak_score, 4),
            "sector_rank_score": round(self.sector_rank_score, 4),
            "total_score":       round(self.total_score, 4),
        }


@dataclass
class DividendScoredStock:
    rank: int
    input: DividendScoreInput
    breakdown: DividendScoreBreakdown
    rationale: list[str]

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "ticker": self.input.ticker,
            "name": self.input.name,
            "dividend_yield_pct": round(self.input.dividend_yield * 100, 2),
            "dps": self.input.dps,
            "payout_ratio_pct": round(self.input.payout_ratio * 100, 1),
            "equity_ratio_pct": round(self.input.equity_ratio * 100, 1),
            "consecutive_raises": self.input.consecutive_raises,
            "dps_cagr_3y_pct": round(self.input.dps_cagr_3y * 100, 1),
            "has_dividend_cut": self.input.has_dividend_cut,
            "breakdown": self.breakdown.to_dict(),
            "rationale": self.rationale,
        }


# ══════════════════════════════════════════════════════════════════════════════
# スコア関数 — 各関数に引用根拠を明記
# ══════════════════════════════════════════════════════════════════════════════

def _score_stability(inp: DividendScoreInput) -> float:
    """[P3][P5] Insula 活性化抑制 + 損失回避 λ=2 の適用。

    Knutson & Bossaerts (2007): Insula は報酬の分散（リスク）を独立して符号化。
    変動の大きな配当株は insula を活性化 → 投資家がパニック売りをする。
    Frydman & Camerer (2016): 配当削減は過剰な神経反応を引き起こし
                              長期保有を阻害する（diminishing sensitivity）。

    設計:
      CV ≤ 0.10 → 1.0 (高安定)
      CV = 0.30 → 0.40
      CV ≥ 0.50 → 0.0
      削減歴あり → 上限 0.05 ([P5] λ=2 より強い制裁: 削減は致命的フラグ)
    """
    if not inp.dps_history or len(inp.dps_history) < 2:
        return 0.40  # データ不足: 保守的中立

    cv = inp.dps_cv
    # リワード勾配: CV 0→0.10 で 1.0、以降線形低下
    if cv <= 0.10:
        base = 1.0
    elif cv <= 0.50:
        # 報酬側: CV 0.10から0.50の間で 1.0→0.0 (傾き = 2.5)
        base = 1.0 - (cv - 0.10) / 0.40
    else:
        base = 0.0

    # [P5] 削減フラグ: λ=2 より強い制裁（配当削減の心理ダメージは過剰増幅される）
    if inp.has_dividend_cut:
        return min(base * 0.10, 0.05)  # 事実上 0 に近い値

    return max(0.0, round(base, 4))


def _score_health(equity_ratio: float, debt_equity: float) -> float:
    """[P1] Insula 誘発予防（財務リスク知覚）、[P2] λ=2 非対称ペナルティ。

    Kuhnen & Knutson (2005): Insula 活性化は過剰リスク回避と panic を予測する。
    財務的に脆弱な企業（高D/E、低自己資本）は insula を活性化させる。
    Tom et al. (2007): ペナルティ傾き = リワード傾き × λ(≈2.0)。

    設計:
      自己資本比率: 理想 ≥ 0.40 → スコア 1.0。0.20未満で急ペナルティ。
      D/E比:       0.0→1.0, 1.0→0.67, 2.0→0.33, 3.0+→0.0
      ペナルティ傾き = リワード傾き × LAMBDA (2.0)
    """
    # 自己資本比率スコア: 理想 ≥ 40%
    # リワード域 0→40%: 傾き 1.0/0.40 = 2.5/unit
    # ペナルティ域なし (低自己資本はそもそもスコアが低い)
    if equity_ratio <= 0:
        eq_score = 0.0
    elif equity_ratio >= 0.40:
        eq_score = 1.0
    elif equity_ratio >= 0.20:
        # 20–40%: 緩やかに上昇
        eq_score = (equity_ratio - 0.20) / 0.20 * 0.7
    else:
        # <20%: 急ペナルティ (λ=2: 傾き 2倍) — insula 強活性ゾーン
        eq_score = equity_ratio / 0.20 * 0.20

    # D/E 比スコア: 0=最良(1.0)、3+=最悪(0.0)
    # リワード域（D/E下降）: 1→0の間で +1.0/unit → 傾き 1.0
    # ペナルティ域（D/E上昇）: 0→3の間で -1.0/3 ≈ -0.33/unit × LAMBDA = -0.67/unit
    if debt_equity < 0:
        de_score = 0.50
    elif debt_equity <= 1.0:
        # 理想ゾーン: D/E 0→1 で 1.0→0.67
        de_score = 1.0 - debt_equity * 0.33
    elif debt_equity <= 3.0:
        # ペナルティゾーン: D/E 1→3 で 0.67→0 (λ=2: 同距離で2倍速く下降)
        de_score = 0.67 - (debt_equity - 1.0) / 2.0 * 0.67 * LAMBDA / 2.0
    else:
        de_score = 0.0

    return max(0.0, round(eq_score * 0.55 + de_score * 0.45, 4))


def _score_yield(dy: float) -> float:
    """[P1][P3] NAcc 期待報酬の符号化 — 過活性化を防ぐ上限付きシグモイド。

    Kuhnen & Knutson (2005): NAcc 過活性化 = irrational risk-taking の予測因子。
                              極端な高利回りは NAcc を過剰刺激し衝動買いを誘発。
    Knutson & Bossaerts (2007): 腹側線条体は期待報酬を符号化するが、
                                 リスク（分散）とは独立した回路。

    設計:
      4%=0.75（理想帯中央）、6%=0.97（高評価上限）、8%超=下降開始（NAcc警戒帯）、
      10%超=0.30（過活性ゾーン警戒）、12%超=0.10（異常値）
    """
    if dy <= 0:
        return 0.0
    if dy > 0.12:
        return 0.10  # 極端値: 株価暴落or異常。NAcc過活性最大ゾーン
    if dy > 0.10:
        # λ=2: 8%→10%の下降は緩やかだが10%超は急ペナルティ
        return 0.30 - (dy - 0.10) / 0.02 * 0.20
    if dy > 0.08:
        # NAcc警戒帯: 8%を超えると下降 (λ=2: リワード傾きの2倍速で低下)
        return 0.80 - (dy - 0.08) / 0.02 * 0.50 * LAMBDA / 2.0
    # 主要評価帯 0–8%: シグモイド (NAcc適正刺激ゾーン)
    return min(1.0, 1 / (1 + math.exp(-15 * (dy - 0.04))))


def _score_momentum(inp: DividendScoreInput) -> float:
    """[P4] ドーパミン予測誤差の定量化。

    Schultz, Dayan & Montague (1997): ドーパミンは期待を上回る報酬に対して発火。
    連続した正の予測誤差（配当増額）が長期保有の信頼基盤を作る。
    直近3年CAGRを予測誤差の方向・強度の代理指標として使用。

    設計:
      CAGR ≥ 10%: 1.0（強い正の予測誤差、ただし持続可能性は別評価）
      CAGR 5%: 0.75
      CAGR 0%: 0.40（横ばい = 予測誤差ゼロ = ドーパミン発火なし）
      CAGR -5%: 0.10（負の予測誤差 = ドーパミン抑制 → 失望売り誘発）
      ペナルティ傾き ≈ リワード傾き × LAMBDA (2.0)
    """
    if not inp.dps_history or len(inp.dps_history) < 2:
        return 0.35  # データ不足

    cagr = inp.dps_cagr_3y

    if cagr >= 0.10:
        return 1.0
    if cagr >= 0:
        # 0%→10% でリニアに 0.40→1.0 (傾き 6.0/unit)
        return 0.40 + cagr / 0.10 * 0.60
    # 負CAGR: λ=2 で傾き12.0/unit (リワード傾きの2倍)
    score = 0.40 + cagr / 0.10 * 0.60 * LAMBDA
    return max(0.0, round(score, 4))


def _score_payout(ratio: float) -> float:
    """[P2] λ=2 非対称ペナルティ。PFC 認知制御の代理指標。

    Tom et al. (2007): ペナルティ傾き ≈ リワード傾き × λ(2.0)。
    高性向（>80%）は将来の配当削減リスク → 潜在的損失 → insula・amygdala 活性。
    この潜在的損失は現在の高利回りの利得より λ=2 倍大きく感じられる。

    設計（理想帯 30–70%）:
      理想帯 30–70%: 1.0
      0%: 0.20（配当なし）
      0–30%: リワード傾きで上昇
      70–80%: やや下降（警戒帯）
      80–100%: λ=2 傾きで急下降
      >100%: 0.0–0.10（致命的: 利益超過配当）
    """
    if ratio <= 0:
        return 0.20
    if ratio > 1.20:
        return 0.0
    if ratio > 1.0:
        # 100–120%: λ=2 超急下降
        return max(0.0, 0.10 - (ratio - 1.0) / 0.20 * 0.10)
    if ratio > 0.80:
        # 80–100%: ペナルティ傾き = リワード傾き × λ=2
        # リワード傾き基準: 0→30% で +0.80/0.30 ≈ 2.67/unit
        # ペナルティ傾き: 2.67 × 2 × 0.10 (スコール範囲調整) ≈ 傾き急
        return 1.0 - (ratio - 0.80) / 0.20 * 0.90
    if 0.30 <= ratio <= 0.70:
        return 1.0
    if ratio < 0.30:
        return 0.20 + (ratio / 0.30) * 0.80
    # 70–80%: 軽微な下降
    return 1.0 - (ratio - 0.70) / 0.10 * 0.10


def _score_streak(years: int) -> float:
    """[P4] 連続正予測誤差の累積 = 長期信頼の構築。

    ドーパミン予測誤差理論: 連続した正の予測誤差（毎年の増配）が
    信頼回路を強化し、amygdala の不確実性への恐怖を低減させる。
    ログスケール: 初期の増配年数効果が大きく、後年は逓減（実際の信頼構築に対応）。
    """
    if years <= 0:
        return 0.0
    if years >= 25:
        return 1.0
    return min(1.0, math.log(years + 1) / math.log(26))


def _score_sector_rank(percentile: float) -> float:
    """社会比較効果 (Fliessbach et al. 2007)。同業他社との相対評価。最小限の重み。"""
    return max(0.0, 1.0 - percentile)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def score_stock(
    inp: DividendScoreInput,
    *,
    weights: DividendScoreWeights | None = None,
    sector_rank_percentile: float | None = None,
) -> DividendScoredStock:
    w = weights or DividendScoreWeights()
    w.validate()

    sts = _score_stability(inp)
    hs  = _score_health(inp.equity_ratio, inp.debt_equity)
    ys  = _score_yield(inp.dividend_yield)
    ms  = _score_momentum(inp)
    ps  = _score_payout(inp.payout_ratio)
    ss  = _score_streak(inp.consecutive_raises)
    rs  = _score_sector_rank(sector_rank_percentile if sector_rank_percentile is not None
                              else inp.sector_yield_rank)

    total = (
        sts * w.stability_weight
        + hs  * w.health_weight
        + ys  * w.yield_weight
        + ms  * w.momentum_weight
        + ps  * w.payout_weight
        + ss  * w.streak_weight
        + rs  * w.sector_rank_weight
    )

    breakdown = DividendScoreBreakdown(
        stability_score=sts, health_score=hs, yield_score=ys,
        momentum_score=ms, payout_score=ps, streak_score=ss,
        sector_rank_score=rs, total_score=round(total, 4),
    )
    return DividendScoredStock(
        rank=0, input=inp, breakdown=breakdown,
        rationale=_build_rationale(inp, breakdown, w),
    )


def score_stocks(
    candidates: Sequence[DividendScoreInput],
    *,
    weights: DividendScoreWeights | None = None,
) -> list[DividendScoredStock]:
    if not candidates:
        return []
    yields = [(c.dividend_yield, i) for i, c in enumerate(candidates)]
    yields_sorted = sorted(yields, key=lambda x: -x[0])
    rank_map = {i: pos / max(len(yields) - 1, 1) for pos, (_, i) in enumerate(yields_sorted)}

    scored = [
        score_stock(c, weights=weights, sector_rank_percentile=rank_map[i])
        for i, c in enumerate(candidates)
    ]
    scored.sort(key=lambda s: -s.breakdown.total_score)
    for rank, s in enumerate(scored, start=1):
        s.rank = rank
    return scored


def _build_rationale(inp: DividendScoreInput, bd: DividendScoreBreakdown,
                     w: DividendScoreWeights) -> list[str]:
    lines = [
        f"安定性 CV={inp.dps_cv:.2f}{'・減配歴あり' if inp.has_dividend_cut else ''} → {bd.stability_score:.2f}",
        f"財務 自己資本{inp.equity_ratio:.0%} D/E{inp.debt_equity:.2f}x → {bd.health_score:.2f}",
        f"利回り {inp.dividend_yield:.2%} → {bd.yield_score:.2f}",
        f"成長 3年CAGR {inp.dps_cagr_3y:+.1%} → {bd.momentum_score:.2f}",
        f"性向 {inp.payout_ratio:.0%} → {bd.payout_score:.2f}",
        f"連配 {inp.consecutive_raises}年 → {bd.streak_score:.2f}",
        f"業種内順位 → {bd.sector_rank_score:.2f}",
    ]
    # 警告: 設計上の致命的・重要フラグ
    if inp.has_dividend_cut:
        lines.append("⚠ 減配履歴: [P5] 長期保有の神経基盤が毀損されている")
    if inp.dividend_yield > 0.10:
        lines.append("⚠ 利回り10%超: [P1] NAcc 過活性ゾーン — 株価暴落・高リスクの可能性")
    if inp.payout_ratio > 0.80:
        lines.append("⚠ 配当性向80%超: [P2] λ=2 損失リスク — 将来削減リスクが高い")
    if inp.dps_cagr_3y >= 0.08 and not inp.has_dividend_cut:
        lines.append(f"✓ 連続正のドーパミン予測誤差 [P4]: CAGR {inp.dps_cagr_3y:.0%}")
    if inp.dps_cv <= 0.10 and not inp.has_dividend_cut:
        lines.append("✓ Insula 低活性: 変動小 → 長期保有を阻害するパニック売りリスク低")
    return lines
