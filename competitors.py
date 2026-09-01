#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
과거 입찰의 전체 참가업체 이력(company_stats.json) 기반
미보축산 vs 경쟁사 현황 집계 모듈. 연도별 조회를 지원한다.

company_stats.json 은 각 업체별로:
  participations/wins/win_rate/win_amt_total: 전체 기간 누적
  schools: {학교명: 참여횟수}
  last_pbanc: 가장 최근 참여한 공고의 공고일(YYYYMMDD)
  by_year: {"YYYY": {participations, wins, win_amt_total, win_rate}}

이 데이터는 매일 실행되는 bid_notifier.py의 update_historical_data()가
새로 개찰 결과가 나올 때마다 계속 누적 갱신한다(정적 스냅샷이 아님).
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_PATH = os.path.join(BASE_DIR, "company_stats.json")

OUR_COMPANY = "장기농장 미보축산"

_STATS = None


def _load():
    global _STATS
    if _STATS is not None:
        return
    if not os.path.exists(STATS_PATH):
        _STATS = {}
        return
    with open(STATS_PATH, encoding="utf-8") as f:
        _STATS = json.load(f)


def available_years():
    """데이터에 존재하는 연도 목록(최신순)."""
    _load()
    years = set()
    for s in _STATS.values():
        years.update(s.get("by_year", {}).keys())
    return sorted(years, reverse=True)


def _stats_for_year(name, s, year):
    if year is None:
        return {
            "participations": s["participations"],
            "wins": s["wins"],
            "win_rate": s["win_rate"],
            "win_amt_total": s["win_amt_total"],
        }
    y = s.get("by_year", {}).get(year)
    if not y:
        return None
    return {
        "participations": y["participations"],
        "wins": y["wins"],
        "win_rate": y["win_rate"],
        "win_amt_total": y["win_amt_total"],
    }


def get_us(year=None):
    """미보축산 본인 통계(연도 지정 가능). 데이터에 없으면 None."""
    _load()
    s = _STATS.get(OUR_COMPANY)
    if not s:
        return None
    stat = _stats_for_year(OUR_COMPANY, s, year)
    if not stat:
        return None
    return {"name": OUR_COMPANY, "last_pbanc": s["last_pbanc"], **stat}


def get_leaderboard(year=None, min_participations=3, top_n=8):
    """경쟁사 순위표(연도 지정 가능). 낙찰횟수 desc, 참여횟수 desc 순.
    미보축산은 min_participations 미달이어도, 해당 연도 참여 이력이 있으면 항상 포함."""
    _load()
    rows = []
    for name, s in _STATS.items():
        stat = _stats_for_year(name, s, year)
        if not stat:
            continue
        is_us = name == OUR_COMPANY
        if stat["participations"] < min_participations and not is_us:
            continue
        rows.append({"name": name, "is_us": is_us, "last_pbanc": s["last_pbanc"], **stat})
    rows.sort(key=lambda r: (-r["wins"], -r["participations"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    top = rows[:top_n]
    if not any(r["is_us"] for r in top):
        us_row = next((r for r in rows if r["is_us"]), None)
        if us_row:
            top = top + [us_row]
    return top
