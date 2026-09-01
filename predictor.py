#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
과거 낙찰 이력(model_data.json, 포항 지역 축산 관련 169건 실낙찰 데이터) 기반
낙찰 확률/추천 입찰가 예측 모듈.

핵심 아이디어:
- "마진" = 실제 낙찰비율(예정가격 대비 %) - 그 공고문에 적힌 최저가(%)
  공고문에 이미 적혀 나오는 최저가(法定/기관 문턱값)를 그대로 쓰고, 그 위에
  실제로 얼마나 더 얹어 써야 이겼는지만 통계로 추정한다.
- 참여업체 수는 학교별 과거 평균 + 이번 공고 기초가격이 그 학교 평균보다
  큰 만큼을 회귀계수로 가산해 자동 추정한다(직접 알 수 없으므로).
- 15개 복수예비가격 번호 중 어떤 걸 고르는지는 실측 결과(번호 위치와 실제
  요율이 무관함, 블라인드 추첨) 검증에 따라 추천하지 않는다.
- "달성불가" 판정 없이 항상 가격+확률을 계산하되, 반드시 공고문 최저가
  이상으로 하한선을 둔다(최저가 미만 입찰은 무효이므로).

169건 leave-one-out 백테스트로 각 등급의 실제성공률을 검증했다:
  공격적(내부목표50%) -> 실제성공률 55.6%
  표준(내부목표70%)   -> 실제성공률 74.6%
  보수적(내부목표85%) -> 실제성공률 88.8%
  최대안전(내부목표95%) -> 실제성공률 92.9%
"""
import json
import os
from statistics import mean
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DATA_PATH = os.path.join(BASE_DIR, "model_data.json")

BETA_PARTICIPANT = -0.080  # 학교 고정효과 통제 후, 참여업체 1개사당 margin 변화(%p)
BETA_PRICE_ON_N = 0.975 / 10_000_000  # 학교 고정효과 통제 후, 기초가격 1원당 참여업체수 변화(개사)
SAFETY_PAD = 8  # 소표본 극단분위수 과소추정 보정(백테스트로 검증된 값)
ROUND_UNIT = 100
MIN_RECORDS = 5

TIERS = [
    ("공격적", 50, 55.6),
    ("표준", 70, 74.6),
    ("보수적", 85, 88.8),
    ("최대안전", 95, 92.9),
]

_DATA = None
_BY_SCHOOL = None


def _load():
    global _DATA, _BY_SCHOOL
    if _DATA is not None:
        return
    if not os.path.exists(MODEL_DATA_PATH):
        _DATA = []
        _BY_SCHOOL = {}
        return
    with open(MODEL_DATA_PATH, encoding="utf-8") as f:
        _DATA = json.load(f)
    by_school = defaultdict(list)
    for d in _DATA:
        by_school[d["school"]].append(d)
    _BY_SCHOOL = by_school


def predict(school, bgng_prc, min_price_pct, n_participants=None):
    """
    school: 학교명(수요기관명, PURR_NM)
    bgng_prc: 기초가격(원, int)
    min_price_pct: 공고문에 적힌 최저가(%) - 예: "예정가격의 88% 이상"이면 88.0
    n_participants: 예상 참여업체수(없으면 학교평균+가격보정으로 자동추정)

    반환: dict 또는 데이터가 없으면 None
    """
    _load()
    if not _DATA or not bgng_prc or not min_price_pct:
        return None

    recs = _BY_SCHOOL.get(school, [])
    use_school = len(recs) >= MIN_RECORDS
    base_recs = recs if use_school else _DATA
    source = f"{school} 자체 이력 {len(recs)}건" if use_school else f"전체 이력 {len(_DATA)}건 (해당 학교 이력 부족)"

    school_avg_n = mean(d["n_participants"] for d in recs) if recs else mean(d["n_participants"] for d in _DATA)
    school_avg_price = mean(d["bgng_prc"] for d in recs) if recs else mean(d["bgng_prc"] for d in _DATA)
    plnprc_ratio = mean(d["plnprc_ratio"] for d in recs) if recs else mean(d["plnprc_ratio"] for d in _DATA)
    est_plnprc = round(bgng_prc * plnprc_ratio)

    if n_participants is None:
        n_participants = max(1, round(school_avg_n + BETA_PRICE_ON_N * (bgng_prc - school_avg_price)))
        n_note = f"자동추정 (학교평균 {school_avg_n:.1f}개사 + 가격보정)"
    else:
        n_note = "직접 입력값"
    adjust = BETA_PARTICIPANT * (n_participants - school_avg_n)

    margins = sorted(d["margin"] for d in base_recs)
    n = len(margins)

    def win_prob(bid_ratio_pct):
        target_margin = bid_ratio_pct - min_price_pct - adjust
        cnt = sum(1 for m in margins if m >= target_margin)
        return cnt / n * 100

    def margin_at_percentile(target_p):
        internal_target = min(99, target_p + SAFETY_PAD)
        k_max = int(n * (1 - internal_target / 100))
        k_max = max(0, min(n - 1, k_max))
        return margins[k_max]

    tiers = []
    for label, target_p, backtest_rate in TIERS:
        target_margin = margin_at_percentile(target_p)
        # 최저가 미만 입찰은 법적으로 무효이므로 반드시 min_price_pct 이상으로 하한선
        best_ratio = max(min_price_pct, min_price_pct + adjust + target_margin)
        actual_prob = win_prob(best_ratio)
        amount = round(est_plnprc * best_ratio / 100 / ROUND_UNIT) * ROUND_UNIT
        tiers.append({
            "label": label,
            "ratio": round(best_ratio, 2),
            "amount": amount,
            "prob": round(actual_prob),
            "backtest_rate": backtest_rate,
        })

    return {
        "school": school,
        "bgng_prc": bgng_prc,
        "min_price_pct": min_price_pct,
        "est_plnprc": est_plnprc,
        "plnprc_ratio": plnprc_ratio,
        "n_participants": n_participants,
        "n_note": n_note,
        "source": source,
        "use_school": use_school,
        "tiers": tiers,
    }
