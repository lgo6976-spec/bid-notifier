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
  등급별 목표 여유폭(0~1%p)과 맞먹을 정도로 커서, 예전 계산(아래 PLNPRC_BUFFER
  없이, %만 비교)으로 추정했던 성공률은 실제보다 크게 부풀려져 있었다.
  실제 174건에 그 금액을 대입해 재검증한 결과, 등급 구분 없이 35~49%가
  "예정가격 90% 미만 무효"로 튕겨나갔고, 진짜 성공률은 17~28%에 불과했다.
  아래 PLNPRC_BUFFER(등급별 안전여유 +%p)를 추가해 무효율을 0%로 낮추면
  (= 최소한 "자격 미달로 못 끼는" 최악의 경우는 없앤다는 뜻), 등급 간 차이가
  거의 사라지고 실제성공률은 9~10%대로 수렴한다(이 시장 자체가 등급을 나눠도
  경쟁사들이 다 바닥에 가깝게 써내는 초박빙 구조라서, 등급을 세분화해도
  실질적으로 큰 차이를 못 만든다는 뜻).

  학교별 예정가격비율도 별도로 확인했다: 대부분 학교는 전체평균과 통계적으로
  구분되지 않는 수준의 차이만 있었지만(표본이 적어 우연일 가능성이 큼),
  상도중학교는 전체평균보다 꾸준히 0.71%p 낮게 나오는 뚜렷한 패턴이 확인됐다
  (이 학교 실측 승률이 유독 높았던 이유). James-Stein류 축소추정으로,
  학교 자체 평균이 전체평균과 통계적으로 다르다는 근거가 강할 때만 그 학교
  값을 신뢰하고, 근거가 약하면(대부분의 학교) 전체평균 쪽으로 되돌아가게 했다.

174건 leave-one-out 백테스트로 각 등급의 "실제"(원화 금액 환산 + 그 날
진짜 예정가격 대입 + 무효 여부까지 반영) 성공률을 재검증했다(실제 predict()
함수를 그대로 돌려서 확인한 수치):
  공격적(내부목표50%) -> 실제성공률 9.8%  (버퍼 +1.9%p, 무효율 0%)
  표준(내부목표70%)   -> 실제성공률 10.3% (버퍼 +1.9%p, 무효율 0%)
  보수적(내부목표85%) -> 실제성공률 10.3% (버퍼 +2.0%p, 무효율 0%)
  최대안전(내부목표95%) -> 실제성공률 10.3% (버퍼 +2.0%p, 무효율 0%)
※ 4개 등급의 실제성공률이 거의 수렴하는 건 버그가 아니라, 이 시장 자체가
  경쟁사들이 다 예정가격 90% 바닥 근처에 몰려서 써내는 초박빙 구조라서
  등급을 세분화해도 실질적 차이를 만들기 어렵다는 뜻이다.
"""
import json
import os
from statistics import mean, pstdev
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DATA_PATH = os.path.join(BASE_DIR, "model_data.json")

BETA_PARTICIPANT = -0.080  # 학교 고정효과 통제 후, 참여업체 1개사당 margin 변화(%p)
BETA_PRICE_ON_N = 0.975 / 10_000_000  # 학교 고정효과 통제 후, 기초가격 1원당 참여업체수 변화(개사)
SAFETY_PAD = 8  # 소표본 극단분위수 과소추정 보정(백테스트로 검증된 값)
ROUND_UNIT = 100
MIN_RECORDS = 5

# 등급별 "예정가격 추첨 불확실성" 버퍼(%p). 금액 환산에 쓰는 목표비율에 얹어서,
# 예정가격이 과거 평균보다 낮게 나와도 최저가 미만(무효)으로 떨어지지 않게 한다.
# 174건 leave-one-out 백테스트로 "무효율이 0%가 되는 최소값"을 등급별로 산출했다.
PLNPRC_BUFFER = {
    "공격적": 1.9,
    "표준": 1.9,
    "보수적": 2.0,
    "최대안전": 2.0,
}

TIERS = [
    ("공격적", 50, 9.8),
    ("표준", 70, 10.3),
    ("보수적", 85, 10.3),
    ("최대안전", 95, 10.3),
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


def _shrunk_plnprc_ratio(recs):
    """James-Stein류 축소추정: 학교 자체 예정가격비율 평균이 전체평균과
    통계적으로 다르다는 근거(z)가 강할수록 학교값을 신뢰하고, 근거가 약하면
    (대부분의 경우 - 표본이 적어 우연히 벌어진 차이일 뿐) 전체평균으로 되돌린다.
    학교 기록이 1건뿐이거나 없으면 그냥 전체평균."""
    global_mean = mean(d["plnprc_ratio"] for d in _DATA)
    if len(recs) < 2:
        return global_mean
    global_std = pstdev(d["plnprc_ratio"] for d in _DATA)
    if global_std == 0:
        return global_mean
    n = len(recs)
    school_mean = mean(d["plnprc_ratio"] for d in recs)
    se = global_std / (n ** 0.5)
    z = (school_mean - global_mean) / se
    if z == 0:
        return global_mean
    shrink = max(0.0, 1 - 1 / (z ** 2))
    return global_mean + shrink * (school_mean - global_mean)


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
    plnprc_ratio = _shrunk_plnprc_ratio(recs)
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
        # 예정가격은 나중에 추첨으로 정해지므로, 평균으로 환산한 금액이 실제로는
        # 목표비율보다 낮게(=무효 위험) 나올 수 있다. 그 불확실성만큼 버퍼를 얹는다.
        safe_ratio = best_ratio + PLNPRC_BUFFER[label]
        actual_prob = win_prob(safe_ratio)
        amount = round(est_plnprc * safe_ratio / 100 / ROUND_UNIT) * ROUND_UNIT
        tiers.append({
            "label": label,
            "ratio": round(safe_ratio, 2),
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
