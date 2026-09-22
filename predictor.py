#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
과거 낙찰 이력(model_data.json, 포항 지역 축산 관련 174건 실낙찰 데이터) 기반
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

※ 예정가격 추첨 불확실성에 대해 (2026-09-22 재검증):
  우리는 "%"가 아니라 "원화 금액"을 확정 제출해야 하는데, 그 금액이 몇 %가
  되는지 판가름하는 예정가격은 제출 이후 15개 후보 중 4개를 뽑아 평균낸
  값으로 나중에 정해진다. 그래서 금액 환산에는 항상 "과거 평균 비율"을 쓸 수밖에
  없는데, 이 평균이 실제 추첨값과 어긋나는 폭(공고 간 표준편차 약 0.7%)이
  등급별 목표 여유폭(0~1%p)과 맞먹을 정도로 커서, 실제로는 등급 구분 없이
  34~49%가 "예정가격 최저가 미만 무효"로 튕겨나가고, 진짜 성공률은 17~25%
  수준이었다(화면에 뜨던 55.6~92.9%는 %만 비교한 이론값으로, 실제보다 부풀려져
  있었음). 이 오차 자체는 연도/기초가격/품목별 패턴을 다 확인해봤지만 어디에도
  체계적 신호가 없는 순수 무작위였다(줄일 방법 없음).

  이 무효 위험을 없애려면 등급별 안전버퍼(+2%p 안팎)를 얹으면 되지만, 그러면
  등급 구분이 거의 의미없어지고(실제성공률 9~10%대로 전부 수렴) 승률도
  17~32%대에서 9~10%대로 오히려 낮아진다는 게 leave-one-out 검증으로 확인됐다.
  즉 "무효를 원천봉쇄"와 "승률을 최대한 확보"는 같은 174건 안에서 상충되는
  목표라 동시에 만족시킬 수 없다 - 버퍼를 넣을지/뺄지는 무효(자격미달)를
  얼마나 나쁘게 볼지에 대한 가치판단이며, 여기서는 버퍼 없이(=무효 위험을
  감수하고 승률을 우선) 가는 쪽으로 결정했다.

  예정가격비율 추정 방식도 3가지(A.학교 자체 평균만 사용/B.전체 평균만 사용/
  C.James-Stein 축소추정)를 leave-one-out으로 비교했다: A가 C와 대등하거나
  등급별로 오히려 더 나았고(공격적 등급에서 A 19.5% vs C 16.1%), B가 항상
  가장 나빴다. 그래서 A(학교 자체 이력이 있으면 그대로 신뢰, 없으면 전체
  평균)로 확정했다 - 표본이 적어도(1~4건) 그 학교 고유의 신호를 담고 있어서,
  안전하게 전체평균 쪽으로 되돌리는 것(C)보다 있는 그대로 믿는 게 28개 학교
  전체로는 더 잘 맞았다.

버퍼 없음 + 학교 자체 평균(A) 조합으로 174건 leave-one-out 백테스트를
재검증한 "실제"(원화 금액 환산 + 그 날 진짜 예정가격 대입 + 무효 여부까지
반영) 성공률이다(실제 predict() 함수를 그대로 돌려서 확인한 수치):
  공격적(내부목표50%) -> 실제성공률 17.8%  (무효율 33.9%)
  표준(내부목표70%)   -> 실제성공률 19.0%  (무효율 43.1%)
  보수적(내부목표85%) -> 실제성공률 24.1%  (무효율 47.1%)
  최대안전(내부목표95%) -> 실제성공률 25.3% (무효율 48.9%)

  (2026-09-22 추가 검토: 91개 학교 전체를 재조회해서 품목명이 명확한 확정낙찰
  건 중 174건에 없던 145건(성공 조회 88건)을 찾아 262건으로 늘려본 적이
  있는데, 같은 174건을 테스트 대상으로 고정하고 학습 풀만 88건 추가해서
  비교하니 대부분 등급에서 오히려 승률이 소폭 하락(예: 최대안전 25.3%->
  22.4%)해서 174건 그대로 쓰는 것으로 되돌렸다. 표본을 더 넓힌다고 예측이
  좋아지는 게 아니라는 게 실측으로 확인된 셈 - 나중에 자동 누적으로 더 쌓이는
  것과는 별개로, 수동 백필은 보류.)
※ 무효율이 여전히 34~49%로 높다는 걸 이메일/대시보드에서 사람이 바로 알 수
  있게 표시해야 한다 - "예상확률"이 승률이지 "안전하다"는 뜻이 아니다.
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

# (label, 내부목표percentile, 실제성공률%, 실제무효율%) - 174건 leave-one-out 검증값
# (실제 predict() 함수를 그대로 돌려서 확인한 수치)
TIERS = [
    ("공격적", 50, 17.8, 33.9),
    ("표준", 70, 19.0, 43.1),
    ("보수적", 85, 24.1, 47.1),
    ("최대안전", 95, 25.3, 48.9),
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


def _school_plnprc_ratio(recs):
    """학교 자체 예정가격비율 이력이 있으면 그대로 신뢰하고, 없으면 전체평균.
    (A/B/C 세 방식을 leave-one-out으로 비교한 결과, 표본이 적어도(1~4건) 그
    학교 고유의 신호를 담고 있어서 축소추정보다 이 방식이 등급별로 같거나
    더 나은 성적을 냈다.)"""
    if not recs:
        return mean(d["plnprc_ratio"] for d in _DATA)
    return mean(d["plnprc_ratio"] for d in recs)


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

    school_avg_n = mean(d["n_participants"] for d in base_recs)
    school_avg_price = mean(d["bgng_prc"] for d in base_recs)
    plnprc_ratio = _school_plnprc_ratio(recs)
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
    for label, target_p, backtest_rate, invalid_rate in TIERS:
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
            "invalid_rate": invalid_rate,
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
