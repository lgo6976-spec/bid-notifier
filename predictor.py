#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
과거 낙찰 이력(model_data.json, 포항 지역 축산 관련 174건 실낙찰 데이터) 기반
낙찰 확률/추천 입찰가 예측 모듈.

핵심 아이디어 (2026-09-22 학교별 최적화로 전면 개편):
- 우리는 "%"가 아니라 "원화 금액"을 확정 제출해야 하는데, 그 금액이 몇 %가
  되는지 판가름하는 예정가격은 제출 이후 15개 후보 중 4개를 뽑아 평균낸 값으로
  나중에 정해진다. 그래서 금액 환산에는 항상 "과거 평균 비율"을 쓸 수밖에 없고,
  이 평균이 실제 추첨값과 어긋나는 폭(공고 간 표준편차 약 0.7%)만큼은 어떻게
  해도 못 줄인다(연도/기초가격/품목별 패턴을 다 확인했지만 순수 무작위).
- "마진"(=학교별 목표 여유폭, 최저가 위로 몇 %p를 더 얹어 쓸지)을 예전에는
  전체 174건에 공통된 percentile 공식(SAFETY_PAD)으로 계산했는데, 이러면
  학교마다 실제 경쟁 강도가 다른 걸 못 살린다. 대신 **학교 자체 과거 기록에
  0~3.0%p 사이 여유폭을 촘촘히(0.02%p 단위) 대입해보고, 그 학교 역사에서
  실제로 무효/승/패가 어떻게 나왔을지 직접 계산**해서, "허용 무효율 상한" 안에서
  승 건수가 최대가 되는 여유폭을 학교마다 따로 찾는다(school_offset 방식).
  참여업체수 회귀보정(예전 BETA_PARTICIPANT)은 실제 설명력이 R²=1.2%로
  거의 없었던 게 확인되어 제거했다 - 이 여유폭 자체가 그 학교의 실제 참여
  구도를 이미 암묵적으로 반영한다.
- 학교 자체 이력이 4건 미만이면(소표본이라 여유폭 탐색이 못 미더우므로)
  전체 174건 풀로 대체해서 여유폭을 찾는다(MIN_RECORDS=5 -> 4로 leave-one-out
  검증 후 하향, 아래 참고). 예정가격비율(mean_ratio) 자체는 1건이라도 있으면
  그 학교 값을 그대로 신뢰한다(A/B/C 세 방식 비교에서 검증됨 - 표본이 적어도
  학교 고유 신호가 있어서 전체평균보다 나음).
- 등급은 "허용 무효율 상한"으로 정의한다: 공격적(사실상 무제한, 승률만 최대화)
  / 표준(무효 20% 이내) / 보수적(무효 5% 이내) / 최대안전(무효 0%, 즉 그
  학교 역사에서 단 한 번도 무효였던 적 없는 여유폭).

174건 leave-one-out 백테스트로 검증한 실제 성공률/무효율(실제 predict()
함수를 그대로 돌려서 확인한 수치, MIN_RECORDS=4 + 아래 동률 버그수정 기준):
  공격적   -> 실제성공률 27.6%  (무효율 40.8%)
  표준     -> 실제성공률 18.4%  (무효율  9.8%)
  보수적   -> 실제성공률 17.2%  (무효율  7.5%)
  최대안전 -> 실제성공률 13.8%  (무효율  6.3%)

※ 2026-09-22 버그 수정: _pick_offset가 승 건수가 동률인 여유폭 중 "가장 먼저
  찾은(=가장 작은)" 걸 그냥 채택하고 있었다. 포항장성고에서 발견됨 - 공격적
  등급 기준 offset=0.0과 0.94가 승 3/13으로 동률인데, 무효율은 69%대 0%로
  전혀 달랐다. 즉 무효 위험만 더 지고 승률 이득은 없는 선택을 하고 있었던
  것. 동률이면 무효율이 더 낮은 쪽을 고르도록 수정 - 위 수치는 수정 후 값
  (표준 등급이 특히 개선됨: 16.7%/14.4% -> 18.4%/9.8%, 승률/무효율 둘 다 좋아짐).
※ 이전(전체 공통 percentile) 방식 대비 무효율이 크게 낮아졌다(최대안전 기준
  48.9% -> 6.3%). 승률은 등급별로 비슷하거나 소폭 낮아졌지만, 무효(자격
  미달로 아예 경쟁도 못 해보는 것)를 훨씬 많이 피할 수 있다는 게 핵심 이득.
  등급 간 승률이 100% 단조롭게 깔끔히 줄어들지 않는 것(표준<보수적 등)은
  학교마다 최적 여유폭이 들쭉날쭉하게 흩어져 있어서 생기는 leave-one-out
  특유의 잡음이다 - 절대적인 무효/승 트레이드오프 방향 자체는 일관된다.

※ 2026-09-22 추가 검토(이력 1~3건짜리 소표본 학교를 어떻게 다룰지):
  MIN_RECORDS(여유폭 탐색용 풀 전환 문턱값)를 5/4/3/2로 바꿔가며 검증한 결과
  4(또는 3, 결과 동일)가 5보다 나았고(위 수치), 2는 오히려 더 나빠졌다.
  그래서 4로 확정. 그런데 이력이 1~3건뿐인 학교(여전히 전체풀로 대체되는
  경우, 예: 포항항도중학교 1건)를 "그 학교 자체 기록만으로" 여유폭을 찾게
  하면 안 되는지도 검토했다 - 자기 자신의 1건으로 자기 자신을 검증하면
  추정오차가 0이 되어버리는 순환논리라 그 자체로는 못 쓴다. 그래서 "전체
  풀에 그 학교 자체 기록을 K번 중복해서 가중치를 주는" 절충안도 leave-one-out
  으로 검증했는데(K=3/5/10/20), 개선 효과가 거의 없었고 K가 클수록 오히려
  살짝 나빠졌다(순환논리가 완전히 사라지지 않아서). 즉 이력 1~3건 학교는
  지금 갖고 있는 데이터 안에서는 "전체 풀로 대체"보다 나은 검증된 대안이
  없다 - 그 학교 자체 이력이 4건 이상 쌓이기 전까지는 이 한계를 감수해야 한다.
"""
import json
import os
from statistics import mean
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DATA_PATH = os.path.join(BASE_DIR, "model_data.json")

ROUND_UNIT = 100
MIN_RECORDS = 4  # 이 미만이면 여유폭 탐색은 전체 풀로 대체(예정가격비율 추정은 별개)
OFFSET_MAX = 3.0  # 여유폭 탐색 범위 상한(%p)
OFFSET_STEP = 0.02

# (label, 허용 무효율 상한, 실제성공률%, 실제무효율%) - 174건 leave-one-out 검증값
TIERS = [
    ("공격적", 1.01, 27.6, 40.8),   # 사실상 무제한 - 승률만 최대화
    ("표준", 0.20, 18.4, 9.8),
    ("보수적", 0.05, 17.2, 7.5),
    ("최대안전", 0.0, 13.8, 6.3),
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
    """학교 자체 예정가격비율 이력이 있으면 그대로 신뢰하고, 없으면 전체평균."""
    if not recs:
        return mean(d["plnprc_ratio"] for d in _DATA)
    return mean(d["plnprc_ratio"] for d in recs)


def _eval_offset(pool, mean_ratio, offset):
    """pool(학습 풀)에 이 여유폭을 적용했다면 각 건이 무효/승/패 중 뭐가
    됐을지 실제 금액 환산 + 그 건의 진짜 예정가격을 대입해서 센다."""
    invalid = win = 0
    n = len(pool)
    for rec in pool:
        std_pct = float(rec["std_pct"])
        best_ratio = std_pct + offset
        est_plnprc = rec["bgng_prc"] * mean_ratio
        amount = round(est_plnprc * best_ratio / 100 / ROUND_UNIT) * ROUND_UNIT
        eff = amount / rec["plnprc"] * 100
        if eff < std_pct - 1e-9:
            invalid += 1
        elif eff <= rec["win_sajeong_pct"] + 1e-9:
            win += 1
    return invalid, win, n


def _pick_offset(pool, mean_ratio, invalid_cap):
    """pool 안에서, 무효율이 invalid_cap 이하이면서 승 건수가 최대가 되는
    여유폭(%p)을 찾는다. 승 건수가 같은 여유폭이 여럿이면(흔함) 그중 무효율이
    가장 낮은 걸 고른다 - 승률 이득 없이 무효 위험만 더 지는 선택을 피하기
    위함(예: 포항장성고 공격적 등급에서 offset=0.0과 0.94가 승 3/13으로
    똑같았는데 무효율은 69%대 0%로 차이가 컸던 사례로 발견됨).
    invalid_cap을 만족하는 여유폭이 아예 없으면(극단적으로 흩어진 경우)
    무효율이 최소가 되는 여유폭으로 대체."""
    n = len(pool)
    steps = int(round(OFFSET_MAX / OFFSET_STEP)) + 1
    best_offset, best_win, best_invalid = None, -1, None
    fallback_offset, fallback_invalid, fallback_win = 0.0, n + 1, -1
    for i in range(steps):
        offset = round(i * OFFSET_STEP, 4)
        invalid, win, _ = _eval_offset(pool, mean_ratio, offset)
        # invalid_cap을 만족하는 여유폭이 하나도 없을 때 쓸 대체값: 무효율이
        # 최소인 여유폭들 중에서도(흔히 여럿 동률) 승 건수가 최대인 걸 고른다
        # (위 본 로직과 같은 이유 - 동률이면 공짜로 얻을 수 있는 승률을 버리지 않기 위함).
        if invalid < fallback_invalid or (invalid == fallback_invalid and win > fallback_win):
            fallback_invalid, fallback_offset, fallback_win = invalid, offset, win
        if n and invalid / n <= invalid_cap:
            if win > best_win or (win == best_win and invalid < best_invalid):
                best_offset, best_win, best_invalid = offset, win, invalid
    return best_offset if best_offset is not None else fallback_offset


def predict(school, bgng_prc, min_price_pct):
    """
    school: 학교명(수요기관명, PURR_NM)
    bgng_prc: 기초가격(원, int)
    min_price_pct: 공고문에 적힌 최저가(%) - 예: "예정가격의 88% 이상"이면 88.0

    반환: dict 또는 데이터가 없으면 None
    """
    _load()
    if not _DATA or not bgng_prc or not min_price_pct:
        return None

    recs = _BY_SCHOOL.get(school, [])
    use_school = len(recs) >= MIN_RECORDS
    pool = recs if use_school else _DATA
    source = f"{school} 자체 이력 {len(recs)}건" if use_school else f"전체 이력 {len(_DATA)}건 (해당 학교 이력 부족)"

    plnprc_ratio = _school_plnprc_ratio(recs)
    est_plnprc = round(bgng_prc * plnprc_ratio)
    n_participants = round(mean(d["n_participants"] for d in pool))

    tiers = []
    for label, invalid_cap, backtest_rate, invalid_rate in TIERS:
        offset = _pick_offset(pool, plnprc_ratio, invalid_cap)
        # 최저가 미만 입찰은 법적으로 무효이므로 반드시 min_price_pct 이상으로 하한선
        best_ratio = max(min_price_pct, min_price_pct + offset)
        amount = round(est_plnprc * best_ratio / 100 / ROUND_UNIT) * ROUND_UNIT
        invalid_n, win_n, pool_n = _eval_offset(pool, plnprc_ratio, offset)
        actual_prob = round(win_n / pool_n * 100) if pool_n else 0
        tiers.append({
            "label": label,
            "ratio": round(best_ratio, 2),
            "amount": amount,
            "prob": actual_prob,
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
        "n_note": "학교 평균",
        "source": source,
        "use_school": use_school,
        "tiers": tiers,
    }
