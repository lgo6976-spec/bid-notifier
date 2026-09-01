#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
공공급식통합플랫폼(NeaT, ns.eat.co.kr) 입찰공고 알리미

- 로그인 없이 조회 가능한 내부 API(selectTmBidMBidPbancList.do)를 호출해
  전국 학교급식 입찰공고 목록을 가져온다.
- config.json 의 지역/품목 키워드로 필터링한다.
- 새로 발견된 공고가 있으면 이메일로 알린다 (전체 목록 + 신규 표시, seen_ids.json 으로 중복 방지).
- 현재 조건에 맞는 전체 공고를 dashboard.html(또는 DASHBOARD_FILENAME) 로 생성한다.
"""

import json
import os
import re
import smtplib
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.header import Header
from xml.etree import ElementTree as ET

import predictor

_BAD_AMP_RE = re.compile(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|amp;|lt;|gt;|apos;|quot;)")
_BAD_CTRL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")


def sanitize_xml(text):
    """서버 응답에 이스케이프되지 않은 '&'나 XML 금지 제어문자가 섞여 오는 경우가 있어 보정한다."""
    text = _BAD_AMP_RE.sub("&amp;", text)
    text = _BAD_CTRL_RE.sub("", text)
    return text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
SEEN_PATH = os.path.join(BASE_DIR, "seen_ids.json")
DASHBOARD_PATH = os.path.join(BASE_DIR, os.environ.get("DASHBOARD_FILENAME", "dashboard.html"))
LOG_PATH = os.path.join(BASE_DIR, "run.log")
SITE_DIR = os.path.join(BASE_DIR, "site")
SITE_INDEX_PATH = os.path.join(SITE_DIR, "index.html")

API_URL = "https://ns.eat.co.kr/nm/ep/600/selectTmBidMBidPbancList.do"
REFERER = "https://ns.eat.co.kr/NeaT/eats/index.html"
NS = "http://www.nexacroplatform.com/platform/dataset"

REQUEST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<Root xmlns="{ns}">
\t<Parameters />
\t<Dataset id="ds_searchParam">
\t\t<ColumnInfo>
\t\t\t<Column id="P_BID_NM" type="STRING" size="256" />
\t\t\t<Column id="P_ELCTRN_BID_NO" type="STRING" size="256" />
\t\t\t<Column id="P_BID_BGNG_DT" type="STRING" size="256" />
\t\t\t<Column id="P_BID_END_DT" type="STRING" size="256" />
\t\t\t<Column id="P_PRGRS_STAT_CD" type="STRING" size="256" />
\t\t\t<Column id="P_INST_NM" type="STRING" size="256" />
\t\t\t<Column id="P_CTPV_CD" type="STRING" size="256" />
\t\t\t<Column id="P_SGG_CD" type="STRING" size="256" />
\t\t\t<Column id="P_SRTNG_SEQN" type="STRING" size="256" />
\t\t\t<Column id="P_DNTT_CNPT_CD" type="STRING" size="256" />
\t\t\t<Column id="P_INST_GB_CD" type="STRING" size="256" />
\t\t\t<Column id="EXCEL_GB_CD" type="STRING" size="256" />
\t\t\t<Column id="JSP_YN" type="STRING" size="256" />
\t\t</ColumnInfo>
\t\t<Rows>
\t\t\t<Row>
\t\t\t\t<Col id="P_PRGRS_STAT_CD">{status}</Col>
\t\t\t\t<Col id="P_CTPV_CD">{ctpv_cd}</Col>
\t\t\t\t<Col id="P_SGG_CD">{sgg_cd}</Col>
\t\t\t</Row>
\t\t</Rows>
\t</Dataset>
\t<Dataset id="_ds_pagingInfo">
\t\t<ColumnInfo>
\t\t\t<Column id="START_PAGE" type="STRING" size="255" />
\t\t\t<Column id="PAGE_SIZE" type="STRING" size="255" />
\t\t</ColumnInfo>
\t\t<Rows>
\t\t\t<Row>
\t\t\t\t<Col id="START_PAGE">{page}</Col>
\t\t\t\t<Col id="PAGE_SIZE">{page_size}</Col>
\t\t\t</Row>
\t\t</Rows>
\t</Dataset>
\t<Dataset id="_ds_tranInfo">
\t\t<ColumnInfo>
\t\t\t<Column id="STM_ID" type="STRING" size="255" />
\t\t\t<Column id="MENU_ID" type="STRING" size="255" />
\t\t\t<Column id="MENU_NO" type="STRING" size="255" />
\t\t\t<Column id="PRGRM_ID" type="STRING" size="255" />
\t\t\t<Column id="PRGRM_URL" type="STRING" size="255" />
\t\t\t<Column id="POPUP_YN" type="STRING" size="255" />
\t\t\t<Column id="OPERSYSM_NM" type="STRING" size="255" />
\t\t\t<Column id="WBSR_VER_VL" type="STRING" size="255" />
\t\t\t<Column id="LG_MNG_YN" type="STRING" size="255" />
\t\t\t<Column id="NEXA_CNPT" type="STRING" size="255" />
\t\t</ColumnInfo>
\t\t<Rows>
\t\t\t<Row>
\t\t\t\t<Col id="STM_ID">NEAT</Col>
\t\t\t\t<Col id="MENU_ID">80013</Col>
\t\t\t\t<Col id="MENU_NO">8060100</Col>
\t\t\t\t<Col id="PRGRM_ID">EPTM600M01</Col>
\t\t\t\t<Col id="PRGRM_URL">ep_tm</Col>
\t\t\t\t<Col id="POPUP_YN">N</Col>
\t\t\t\t<Col id="OPERSYSM_NM">Windows 10 64bit</Col>
\t\t\t\t<Col id="WBSR_VER_VL">Chrome 120.0</Col>
\t\t\t\t<Col id="NEXA_CNPT" />
\t\t\t</Row>
\t\t</Rows>
\t</Dataset>
</Root>
"""

DETAIL_API_URL = "https://ns.eat.co.kr/nm/ep/600/selectBidDtl.do"

DETAIL_REQUEST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<Root xmlns="{ns}">
\t<Parameters />
\t<Dataset id="ds_searchParam">
\t\t<ColumnInfo>
\t\t\t<Column id="ELCTRN_BID_ID" type="STRING" size="256" />
\t\t\t<Column id="ACT_TYPE" type="STRING" size="256" />
\t\t\t<Column id="SUCBID_RSN" type="STRING" size="256" />
\t\t</ColumnInfo>
\t\t<Rows>
\t\t\t<Row>
\t\t\t\t<Col id="ELCTRN_BID_ID">{bid_id}</Col>
\t\t\t\t<Col id="ACT_TYPE">S</Col>
\t\t\t</Row>
\t\t</Rows>
\t</Dataset>
\t<Dataset id="_ds_tranInfo">
\t\t<ColumnInfo>
\t\t\t<Column id="STM_ID" type="STRING" size="255" />
\t\t</ColumnInfo>
\t\t<Rows>
\t\t\t<Row>
\t\t\t\t<Col id="STM_ID">NEAT</Col>
\t\t\t</Row>
\t\t</Rows>
\t</Dataset>
</Root>
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Content-Type": "text/xml",
    "Accept": "application/xml, text/xml, */*",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": REFERER,
}


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # GitHub Actions 등 CI 환경에서는 비밀번호를 config.json이 아니라
    # 환경변수(= GitHub Secrets)로 주입한다. 있으면 우선 사용.
    if os.environ.get("SMTP_USER"):
        config["smtp"]["user"] = os.environ["SMTP_USER"]
    if os.environ.get("SMTP_APP_PASSWORD"):
        config["smtp"]["app_password"] = os.environ["SMTP_APP_PASSWORD"]
    if os.environ.get("RECIPIENT_EMAIL"):
        config["recipient_email"] = os.environ["RECIPIENT_EMAIL"]

    return config


def load_seen():
    if not os.path.exists(SEEN_PATH):
        return {}
    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen):
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def http_post(url, body, timeout=60):
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def fetch_page(status, ctpv_cd, sgg_cd, page, page_size):
    body = REQUEST_TEMPLATE.format(ns=NS, status=status, ctpv_cd=ctpv_cd, sgg_cd=sgg_cd, page=page, page_size=page_size)
    text = http_post(API_URL, body, timeout=60)
    root = ET.fromstring(sanitize_xml(text))
    err = root.find(f"{{{NS}}}Parameters/{{{NS}}}Parameter[@id='ErrorCode']")
    if err is not None and err.text and err.text.strip() not in ("0",):
        msg_el = root.find(f"{{{NS}}}Parameters/{{{NS}}}Parameter[@id='ErrorMsg']")
        raise RuntimeError(f"API ErrorCode={err.text} msg={msg_el.text if msg_el is not None else ''}")

    rows = []
    ds = root.find(f"{{{NS}}}Dataset[@id='ds_list']")
    if ds is None:
        return rows
    for row in ds.findall(f"{{{NS}}}Rows/{{{NS}}}Row"):
        d = {}
        for col in row.findall(f"{{{NS}}}Col"):
            d[col.get("id")] = (col.text or "").strip()
        rows.append(d)
    return rows


def fetch_all_bids(status, ctpv_cd, sgg_cd, page_size):
    """P_CTPV_CD/P_SGG_CD로 서버 단에서 이미 해당 시/군 소재 기관으로 걸러서 받아온다
    (전국 데이터를 받아 클라이언트에서 지역 문자열로 거르지 않는다).
    결과가 ETN_BID_ID 내림차순(최신순)으로 오는 것을 이용해, 한 페이지 전체가 이미
    마감된(BID_END_DT < 지금) 공고뿐이면 그 뒤로는 더 오래된 데이터만 나온다고 보고
    조기 종료한다."""
    all_rows = []
    page = 1
    now_str = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
    while True:
        rows = fetch_page(status, ctpv_cd, sgg_cd, page, page_size)
        all_rows.extend(rows)
        log(f"  page {page}: {len(rows)}건 (누적 {len(all_rows)}건)")

        if rows and all(r.get("BID_END_DT", "") < now_str for r in rows):
            log("  페이지 전체가 이미 마감된 공고 -> 조기 종료")
            break
        if len(rows) < page_size:
            break
        page += 1
        if page > 80:  # safety cap
            log("WARNING: page cap reached (80 pages), stopping pagination")
            break
    return all_rows


def fetch_bid_detail(bid_id):
    """공고 상세(기초가격/공고게시일/입찰기간/개찰일시/자격조건 등)를 가져온다.
    실패해도 목록 알림 자체는 계속 진행할 수 있도록 예외를 삼키고 빈 dict를 돌려준다."""
    body = DETAIL_REQUEST_TEMPLATE.format(ns=NS, bid_id=bid_id)
    try:
        text = http_post(DETAIL_API_URL, body, timeout=30)
        root = ET.fromstring(sanitize_xml(text))
    except Exception as e:
        log(f"  WARNING: 상세정보 조회 실패 (ETN_BID_ID={bid_id}): {e}")
        return {}

    ds = root.find(f"{{{NS}}}Dataset[@id='ds_info']")
    if ds is None:
        return {}
    row = ds.find(f"{{{NS}}}Rows/{{{NS}}}Row")
    if row is None:
        return {}
    d = {}
    for col in row.findall(f"{{{NS}}}Col"):
        d[col.get("id")] = (col.text or "").strip()
    return d


def matches_filter(row, item_keywords, exclude_keywords, now_str):
    # 지역(시/군)은 이미 API 요청 단계에서 P_CTPV_CD/P_SGG_CD로 서버가 걸러줬으므로
    # 여기서는 마감 여부와 품목 키워드만 확인하면 된다.
    if row.get("BID_END_DT", "") < now_str:
        return False  # 이미 마감된 공고는 제외
    bid_nm = row.get("BID_NM", "")
    if any(kw in bid_nm for kw in exclude_keywords):
        return False  # "부식"처럼 축산/육류 전용이 아닌 통합구매 공고는 제외
    return any(kw in bid_nm for kw in item_keywords)


def fmt_dt(s):
    # e.g. 20260826090000000 -> 2026-08-26 09:00
    if not s or len(s) < 12:
        return s
    try:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"
    except Exception:
        return s


def fmt_date(s):
    if not s or len(s) < 8:
        return s
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def fmt_price(s):
    try:
        n = int(str(s).strip())
    except (ValueError, TypeError):
        return s or "-"
    if n <= 0:
        return "비공개"
    return f"{n:,}원"


def dday_info(bid_end_dt):
    """마감까지 남은 기간에 따라 (표시용 라벨, 색상 등급) 을 돌려준다."""
    try:
        end = datetime.strptime(bid_end_dt[:14], "%Y%m%d%H%M%S")
    except Exception:
        return "", "ok"
    delta_days = (end - datetime.now()).total_seconds() / 86400
    if delta_days <= 2:
        tier = "urgent"
    elif delta_days <= 5:
        tier = "soon"
    else:
        tier = "ok"
    d = max(0, round(delta_days))
    label = "D-DAY" if d == 0 else f"D-{d}"
    return label, tier


def dday_from_date(date8):
    """YYYYMMDD 형식 날짜까지 남은/지난 일수를 D-N / D-DAY / D+N 형태로 돌려준다."""
    try:
        target = datetime.strptime(date8[:8], "%Y%m%d").date()
    except Exception:
        return ""
    days = (target - datetime.now().date()).days
    if days > 0:
        return f"D-{days}"
    elif days == 0:
        return "D-DAY"
    return f"D+{-days}"


def html_escape(s):
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def enrich_with_detail(matches):
    """목록 API에는 없는 기초가격/공고게시일/입찰기간/개찰일시·장소/자격조건 등을
    상세 API(selectBidDtl.do)로 보강한다. 매칭된 소수 건만 호출하므로 부담이 적다."""
    for r in matches:
        bid_id = r.get("ETN_BID_ID")
        if not bid_id:
            continue
        detail = fetch_bid_detail(bid_id)
        r["_detail"] = detail
        r["_prediction"] = compute_prediction(r, detail)
    return matches


def compute_prediction(r, detail):
    """과거 169건 낙찰이력 기반 낙찰 확률/추천 입찰가 예측(predictor.py).
    기초가격이나 공고문 최저가(PLNPRCE_SUCBD_STD)를 못 구하면 조용히 None을 돌려준다
    (알림 자체는 예측 없이도 계속 진행되어야 하므로)."""
    try:
        school = r.get("PURR_NM", "")
        bgng_prc = int(detail.get("BGNG_PRC") or r.get("STRPRCE") or 0)
        min_price_pct = float(detail.get("PLNPRCE_SUCBD_STD") or 0)
        if not school or bgng_prc <= 0 or min_price_pct <= 0:
            return None
        return predictor.predict(school, bgng_prc, min_price_pct)
    except Exception as e:
        log(f"  WARNING: 낙찰 예측 계산 실패: {e}")
        return None


def format_prediction_text(pred):
    """예측 결과를 이메일용 텍스트 블록으로 포맷. pred가 None이면 빈 문자열."""
    if not pred:
        return ""
    lines = [f"   ── 낙찰 예측 (과거 {pred['source']} 기반, 참여 {pred['n_participants']}개사 {pred['n_note']}) ──"]
    for t in pred["tiers"]:
        lines.append(
            f"     {t['label']:<4} {t['ratio']:.2f}% -> {t['amount']:,}원  "
            f"(이 공고 예상확률 약 {t['prob']}% / 등급 검증성공률 {t['backtest_rate']:.1f}%)"
        )
    lines.append("     ※ 참고용 통계 추정치이며 실제 결과를 보장하지 않습니다.\n")
    return "\n".join(lines) + "\n"


def send_email(matches, new_count, config):
    """matches: 현재 조건에 맞는 전체 목록(마감순 정렬). 그 중 신규인 것만 앞에
    [신규] 표시를 붙여서, 한 메일 안에서 전체 현황 + 무엇이 새로 생겼는지를
    같이 보여준다. new_count == 0 이면 호출하지 않는다(호출부에서 체크)."""
    smtp_cfg = config["smtp"]
    recipients = [e.strip() for e in config["recipient_email"].split(",") if e.strip()]

    lines = []
    for r, is_new in matches:
        d = r.get("_detail", {})
        base_price = d.get("BGNG_PRC") or r.get("STRPRCE", "")
        opng_place = d.get("DOG_ADDR") or r.get("DLVRY_PLACE", "")
        flag = "[신규] " if is_new else "[기존] "
        lines.append(
            f"■ {flag}{r.get('BID_NM','')}\n"
            f"   수요기관: {r.get('PURR_NM','')}\n"
            f"   전자입찰번호: {r.get('ETN_BID_NO','')}\n"
            f"   진행상태: {r.get('ETN_BID_STT_NM','')}\n"
            f"   기초가격: {fmt_price(base_price)}\n"
            f"   공고게시일: {fmt_date(d.get('PBANC_YMD') or r.get('PBANC_YMD',''))}\n"
            f"   입찰기간: {fmt_dt(d.get('BID_BGNG_DT',''))} ~ {fmt_dt(d.get('BID_END_DT') or r.get('BID_END_DT',''))}\n"
            f"   개찰일시: {fmt_dt(d.get('OPNG_DT',''))} ({dday_info(d.get('OPNG_DT',''))[0]})\n"
            f"   개찰장소: {opng_place}\n"
            f"   납품기간: {fmt_date(r.get('DLVRY_STRT_DT',''))} ~ {fmt_date(r.get('DLVRY_END_DT',''))} ({dday_from_date(r.get('DLVRY_STRT_DT',''))})\n"
            f"   지역제한: {d.get('LIMIT_CONDITION_NM') or r.get('LIMIT_CONDITION_NM','')}\n"
            f"   낙찰방법: {d.get('SUCBD_DECISION_MTHD_NM') or r.get('SUCBD_DECISION_MTHD_NM','')}\n"
            + (f"   자격조건: {d.get('ETC_QLFC_LMT_CN')}\n" if d.get("ETC_QLFC_LMT_CN") else "")
            + format_prediction_text(r.get("_prediction"))
        )

    body = (
        f"신규 {new_count}건 (현재 조건에 맞는 전체 {len(matches)}건 중)\n\n"
        + "\n".join(lines)
        + f"\n\n※ 상세/공고문 확인: {REFERER} (로그인 후 '입찰정보 > 입찰공고' 메뉴)\n"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(f"[입찰정보 알리미] 신규 {new_count}건 · 전체 {len(matches)}건 ({config['region_keyword']})", "utf-8")
    msg["From"] = f"{smtp_cfg['from_name']} <{smtp_cfg['user']}>"
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"]) as server:
        server.starttls()
        server.login(smtp_cfg["user"], smtp_cfg["app_password"])
        server.sendmail(smtp_cfg["user"], recipients, msg.as_string())


DASHBOARD_CSS = """
  :root {
    --bg: #f5f3ee;
    --surface: #ffffff;
    --surface-2: #eaf0ee;
    --ink: #1c211f;
    --ink-dim: #5c6360;
    --ink-faint: #6f766f;
    --accent: #1f5e57;
    --accent-soft: #dcebe8;
    --urgent: #b23a2c;
    --urgent-soft: #f6e2de;
    --soon: #93641a;
    --soon-soft: #f3e7d3;
    --ok: #2f7d4f;
    --ok-soft: #dcefe1;
    --border: #e1ddd2;
    --shadow: 0 1px 2px rgba(28,33,31,.04), 0 4px 16px rgba(28,33,31,.05);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #14181a; --surface: #1b2122; --surface-2: #202927;
      --ink: #edf1ee; --ink-dim: #a7b0ab; --ink-faint: #74807a;
      --accent: #63cabb; --accent-soft: #1e3532;
      --urgent: #ff8770; --urgent-soft: #3a2320;
      --soon: #e8b45a; --soon-soft: #362a17;
      --ok: #74d999; --ok-soft: #1c3325;
      --border: #2b3335; --shadow: 0 1px 2px rgba(0,0,0,.3), 0 4px 20px rgba(0,0,0,.35);
    }
  }
  :root[data-theme="dark"] {
    --bg: #14181a; --surface: #1b2122; --surface-2: #202927;
    --ink: #edf1ee; --ink-dim: #a7b0ab; --ink-faint: #74807a;
    --accent: #63cabb; --accent-soft: #1e3532;
    --urgent: #ff8770; --urgent-soft: #3a2320;
    --soon: #e8b45a; --soon-soft: #362a17;
    --ok: #74d999; --ok-soft: #1c3325;
    --border: #2b3335; --shadow: 0 1px 2px rgba(0,0,0,.3), 0 4px 20px rgba(0,0,0,.35);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
    font-family: "Pretendard", "Malgun Gothic", sans-serif; line-height: 1.5; }
  .page { max-width: 920px; margin: 0 auto; padding: 48px 24px 80px; }
  header { display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }
  .eyebrow { font-size: 12.5px; font-weight: 600; letter-spacing: .09em;
    text-transform: uppercase; color: var(--accent); }
  h1 { font-family: "Pretendard", "Malgun Gothic", sans-serif; font-weight: 700;
    font-size: clamp(26px, 4vw, 34px); margin: 0; text-wrap: balance; letter-spacing: -.02em; }
  .subhead { color: var(--ink-dim); font-size: 15px; max-width: 60ch; }
  .keyword-line { font-size: 13px; color: var(--ink-dim); margin-top: 10px; }
  .keyword-line .k { color: var(--ink-faint); margin-right: 6px; }
  .keyword-line .v { color: var(--accent); font-weight: 500; }
  .stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px; margin: 24px 0 32px; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 16px 18px; box-shadow: var(--shadow); }
  .stat .num { font-family: "Pretendard", "Malgun Gothic", sans-serif; font-variant-numeric: tabular-nums;
    font-size: 24px; font-weight: 600; color: var(--ink); }
  .stat .label { font-size: 12.5px; color: var(--ink-faint); margin-top: 2px; }
  .section-label { font-size: 13px; font-weight: 600; letter-spacing: .04em; color: var(--ink-dim);
    margin: 0 0 14px; display: flex; align-items: baseline; gap: 8px; }
  .section-label .count { font-family: "IBM Plex Mono", monospace; color: var(--accent); }
  .cards { display: flex; flex-direction: column; gap: 10px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 18px; box-shadow: var(--shadow); display: grid;
    grid-template-columns: 1fr auto; gap: 8px 16px; }
  .card.is-new { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
  .card-title-row { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
  .new-flag { font-size: 10px; font-weight: 700; letter-spacing: .06em; background: var(--accent);
    color: var(--surface); padding: 1px 6px; border-radius: 4px; margin-top: 3px; flex-shrink: 0; }
  .card-title { font-family: "Pretendard", "Malgun Gothic", sans-serif; font-size: 15px; font-weight: 700;
    line-height: 1.4; text-wrap: balance; letter-spacing: -.01em; }
  .deadline-chip { justify-self: end; align-self: start; display: flex; flex-direction: column;
    align-items: flex-end; gap: 1px; padding: 5px 10px; border-radius: 7px;
    font-family: "IBM Plex Mono", monospace; white-space: nowrap; }
  .deadline-chip .d-label { font-size: 9.5px; font-weight: 600; letter-spacing: .05em;
    font-family: "Pretendard", sans-serif; }
  .deadline-chip .d-time { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .deadline-chip.urgent { background: var(--urgent-soft); color: var(--urgent); }
  .deadline-chip.soon   { background: var(--soon-soft);   color: var(--soon); }
  .deadline-chip.ok     { background: var(--ok-soft);     color: var(--ok); }
  .meta-grid { grid-column: 1 / -1; display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 20px;
    border-top: 1px solid var(--border); padding-top: 11px; margin-top: 1px; }
  .meta-item.wide { grid-column: span 2; }
  .meta-item .k { font-size: 11px; color: var(--ink-faint); letter-spacing: .02em; }
  .meta-item .v { font-size: 13px; font-weight: 500; color: var(--ink); margin-top: 2px;
    line-height: 1.4; }
  .meta-item .v.mono { font-family: "IBM Plex Mono", monospace; font-variant-numeric: tabular-nums; }
  .meta-item.wide .v.mono { white-space: nowrap; }
  .tags { grid-column: 1 / -1; display: flex; gap: 5px; flex-wrap: wrap; }
  .tag { font-size: 11px; background: var(--accent-soft); color: var(--accent);
    padding: 2px 9px; border-radius: 999px; font-weight: 500; }
  .qlfc-note { grid-column: 1 / -1; border-top: 1px dashed var(--border); padding-top: 9px;
    margin-top: 1px; font-size: 12.5px; line-height: 1.65; color: var(--ink-dim); }
  .qlfc-note .k { display: block; font-size: 11px; color: var(--ink-faint);
    letter-spacing: .02em; margin-bottom: 3px; }
  .predict-box { grid-column: 1 / -1; border-top: 1px solid var(--border); padding-top: 11px;
    margin-top: 1px; }
  .predict-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
  .predict-head .k { font-size: 11px; color: var(--ink-faint); letter-spacing: .02em; }
  .predict-head .v { font-size: 11.5px; color: var(--ink-dim); }
  .predict-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; }
  .predict-tier { border-radius: 8px; padding: 8px 10px; background: var(--surface-2); }
  .predict-tier.t-aggr { background: var(--urgent-soft); }
  .predict-tier.t-std  { background: var(--soon-soft); }
  .predict-tier.t-cons { background: var(--ok-soft); }
  .predict-tier.t-safe { background: var(--accent-soft); }
  .predict-tier .p-label { font-size: 10.5px; font-weight: 700; letter-spacing: .03em; }
  .predict-tier.t-aggr .p-label { color: var(--urgent); }
  .predict-tier.t-std  .p-label { color: var(--soon); }
  .predict-tier.t-cons .p-label { color: var(--ok); }
  .predict-tier.t-safe .p-label { color: var(--accent); }
  .predict-tier .p-amt { font-family: "IBM Plex Mono", monospace; font-size: 13px; font-weight: 600;
    color: var(--ink); margin-top: 3px; white-space: nowrap; }
  .predict-tier .p-prob { font-size: 11px; color: var(--ink-dim); margin-top: 2px; }
  .predict-note { grid-column: 1 / -1; font-size: 11px; color: var(--ink-faint); margin-top: 8px; }
  footer { margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--border);
    color: var(--ink-faint); font-size: 12.5px; line-height: 1.7; }
  footer code { font-family: "IBM Plex Mono", monospace; background: var(--surface-2);
    padding: 1px 5px; border-radius: 4px; }
  @media (max-width: 560px) {
    .card { grid-template-columns: 1fr; }
    .deadline-chip { justify-self: start; align-items: flex-start; }
  }
"""


def password_gate_html(password):
    """단순 클라이언트 사이드 비밀번호 입력창. 진짜 보안은 아니고(페이지 소스에 값이
    그대로 보임) 우연히 링크로 들어온 사람을 막는 정도의 용도. password가 비어있으면
    아무것도 넣지 않는다(비밀번호 없이 그대로 공개). 한 번 맞히면 같은 브라우저에서는
    다시 안 물어본다(localStorage)."""
    if not password:
        return ""
    pw_js = json.dumps(password)
    return f"""<script>
(function() {{
  var PW = {pw_js};
  if (localStorage.getItem('bn_unlocked') === PW) return;
  var overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:#f5f3ee;display:flex;' +
    'align-items:center;justify-content:center;font-family:sans-serif;z-index:9999;';
  overlay.innerHTML = '<div style="text-align:center">' +
    '<p style="margin-bottom:10px">비밀번호를 입력하세요</p>' +
    '<input type="password" id="bn_pw" style="padding:8px;font-size:16px;border:1px solid #ccc;border-radius:6px">' +
    '<button id="bn_go" style="padding:8px 16px;margin-left:6px;border-radius:6px;border:1px solid #ccc;cursor:pointer">확인</button>' +
    '<p id="bn_err" style="color:#b23a2c;display:none;margin-top:8px">비밀번호가 틀렸습니다</p></div>';
  document.body.appendChild(overlay);
  function check() {{
    var v = document.getElementById('bn_pw').value;
    if (v === PW) {{
      localStorage.setItem('bn_unlocked', PW);
      overlay.remove();
    }} else {{
      document.getElementById('bn_err').style.display = 'block';
    }}
  }}
  document.getElementById('bn_go').addEventListener('click', check);
  document.getElementById('bn_pw').addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') check();
  }});
  document.getElementById('bn_pw').focus();
}})();
</script>"""


_TIER_CLASS = {"공격적": "t-aggr", "표준": "t-std", "보수적": "t-cons", "최대안전": "t-safe"}


def predict_box_html(pred):
    """예측 결과를 카드 안에 넣을 HTML 블록으로 렌더링. pred가 None이면 빈 문자열."""
    if not pred:
        return ""
    tiers_html = "".join(f"""
        <div class="predict-tier {_TIER_CLASS.get(t['label'], '')}">
          <div class="p-label">{html_escape(t['label'])}</div>
          <div class="p-amt">{t['amount']:,}원</div>
          <div class="p-prob">{t['ratio']:.2f}% · 예상 {t['prob']}%</div>
        </div>""" for t in pred["tiers"])
    return f"""
      <div class="predict-box">
        <div class="predict-head">
          <span class="k">낙찰 예측</span>
          <span class="v">{html_escape(pred['source'])} · 예상참여 {pred['n_participants']}개사({html_escape(pred['n_note'])})</span>
        </div>
        <div class="predict-grid">{tiers_html}
        </div>
        <div class="predict-note">참고용 통계 추정치이며 실제 결과를 보장하지 않습니다. (등급별 %는 169건 백테스트 검증 성공률)</div>
      </div>"""


def write_dashboard(matches, seen_before_this_run, config):
    matches_sorted = sorted(matches, key=lambda r: r.get("BID_END_DT", ""))
    region = config["region_keyword"]
    new_count = sum(1 for r in matches_sorted if r.get("ETN_BID_ID") not in seen_before_this_run)

    cards_html = []
    for r in matches_sorted:
        d = r.get("_detail", {})
        is_new = r.get("ETN_BID_ID") not in seen_before_this_run
        base_price = d.get("BGNG_PRC") or r.get("STRPRCE", "")
        opng_place = html_escape(d.get("DOG_ADDR") or r.get("DLVRY_PLACE", ""))
        qlfc_cn = d.get("ETC_QLFC_LMT_CN", "")
        bid_nm = r.get("BID_NM", "")
        matched_kw = [kw for kw in config["item_keywords"] if kw in bid_nm]
        limit_cond = d.get("LIMIT_CONDITION_NM") or r.get("LIMIT_CONDITION_NM", "")
        tags = matched_kw + ([limit_cond] if limit_cond else [])
        tags_html = "".join(f'<span class="tag">{html_escape(t)}</span>' for t in tags)
        d_label, d_tier = dday_info(d.get("BID_END_DT") or r.get("BID_END_DT", ""))

        cards_html.append(f"""
    <div class="card {'is-new' if is_new else ''}">
      <div class="card-title-row">
        {'<span class="new-flag">NEW</span>' if is_new else ''}
        <span class="card-title">{html_escape(bid_nm)}</span>
      </div>
      <div class="deadline-chip {d_tier}">
        <span class="d-label">마감 {d_label}</span>
        <span class="d-time">{fmt_dt(d.get('BID_END_DT') or r.get('BID_END_DT',''))}</span>
      </div>
      <div class="meta-grid">
        <div class="meta-item"><div class="k">수요기관</div><div class="v">{html_escape(r.get('PURR_NM',''))}</div></div>
        <div class="meta-item"><div class="k">기초가격</div><div class="v mono">{fmt_price(base_price)}</div></div>
        <div class="meta-item"><div class="k">공고게시일</div><div class="v mono">{fmt_date(d.get('PBANC_YMD') or r.get('PBANC_YMD',''))}</div></div>
        <div class="meta-item wide"><div class="k">입찰기간</div><div class="v mono">{fmt_dt(d.get('BID_BGNG_DT',''))} ~ {fmt_dt(d.get('BID_END_DT') or r.get('BID_END_DT',''))}</div></div>
        <div class="meta-item"><div class="k">개찰일시</div><div class="v mono">{fmt_dt(d.get('OPNG_DT',''))} ({dday_info(d.get('OPNG_DT',''))[0]})</div></div>
        <div class="meta-item wide"><div class="k">개찰장소</div><div class="v">{opng_place}</div></div>
        <div class="meta-item wide"><div class="k">납품기간</div><div class="v mono">{fmt_date(r.get('DLVRY_STRT_DT',''))} ~ {fmt_date(r.get('DLVRY_END_DT',''))} ({dday_from_date(r.get('DLVRY_STRT_DT',''))})</div></div>
        <div class="meta-item wide"><div class="k">낙찰방법 · 계약방법</div><div class="v">{html_escape(d.get('SUCBD_DECISION_MTHD_NM') or r.get('SUCBD_DECISION_MTHD_NM',''))} · {html_escape(d.get('CNTRCT_FORM_NM',''))}</div></div>
        <div class="meta-item"><div class="k">전자입찰번호</div><div class="v mono">{r.get('ETN_BID_NO','')}</div></div>
      </div>
      {f'<div class="qlfc-note"><span class="k">자격조건</span>{html_escape(qlfc_cn)}</div>' if qlfc_cn else ''}
      {f'<div class="tags">{tags_html}</div>' if tags else ''}
      {predict_box_html(r.get("_prediction"))}
    </div>""")

    html = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{region} 축산·육류 입찰 알리미</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" as="style" crossorigin
  href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">
<style>{DASHBOARD_CSS}</style>
</head>
<body>
{password_gate_html(config.get("page_password", ""))}
<div class="page">
  <header>
    <div class="eyebrow">공공급식통합플랫폼 · 자동 수집</div>
    <h1>{region} 축산·육류 입찰 알리미</h1>
    <div class="subhead">전국 학교급식 입찰공고 중 배송지가 {region}시인 건만 걸러 모았습니다.</div>
    <div class="keyword-line"><span class="k">필터 키워드</span><span class="v">{' · '.join(config['item_keywords'])}</span></div>
  </header>
  <div class="stat-row">
    <div class="stat"><div class="num">{len(matches_sorted)}</div><div class="label">조건에 맞는 공고</div></div>
    <div class="stat"><div class="num">{new_count}</div><div class="label">신규 (이번 실행)</div></div>
    <div class="stat"><div class="num">{region}</div><div class="label">지역 필터</div></div>
    <div class="stat"><div class="num">{datetime.now().month}월 {datetime.now().day}일</div><div class="label">수집 시각 {datetime.now():%H:%M}</div></div>
  </div>
  <p class="section-label">진행중인 공고 <span class="count">{len(matches_sorted)}건</span></p>
  <div class="cards">
    {"".join(cards_html) if cards_html else '<p style="color:var(--ink-dim)">현재 조건에 맞는 공고가 없습니다.</p>'}
  </div>
  <footer>
    이 페이지는 {datetime.now():%Y-%m-%d %H:%M} 수집 결과입니다. 실시간 데이터가 아니라, 하루 한 번(오전 7시) 자동 실행되어 갱신됩니다.<br>
    새 공고는 이메일로 별도 안내됩니다. 기초가격·입찰기간·개찰일시 등은 공고 목록 API와 별도로,
    건별 상세 API(<code>selectBidDtl.do</code>)를 추가 호출해 보강한 값입니다.
  </footer>
</div>
</body>
</html>
"""
    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    if config.get("github_pages", {}).get("enabled"):
        os.makedirs(SITE_DIR, exist_ok=True)
        with open(SITE_INDEX_PATH, "w", encoding="utf-8") as f:
            f.write(html)


def publish_to_github(config):
    """site/index.html 을 GitHub 저장소로 push 해서 GitHub Pages 링크가
    최신 상태로 유지되게 한다. site/ 가 이미 git 저장소로 초기화되어
    (git init + remote add + 최초 push) 있어야 동작한다.
    (GitHub Actions 배포에서는 워크플로 자체가 커밋/푸시를 처리하므로 보통 비활성 상태로 둔다.)"""
    gh_cfg = config.get("github_pages", {})
    if not gh_cfg.get("enabled"):
        return
    if not os.path.isdir(os.path.join(SITE_DIR, ".git")):
        log("  WARNING: site/ 가 아직 git 저장소로 초기화되지 않아 GitHub 발행을 건너뜁니다 (README 참고)")
        return

    commit_msg = f"update {datetime.now():%Y-%m-%d %H:%M}"
    try:
        subprocess.run(["git", "add", "index.html"], cwd=SITE_DIR, check=True,
                        capture_output=True, text=True)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=SITE_DIR)
        if diff.returncode == 0:
            log("  변경사항 없음 -> git push 생략")
            return
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=SITE_DIR, check=True,
                        capture_output=True, text=True)
        subprocess.run(["git", "push"], cwd=SITE_DIR, check=True,
                        capture_output=True, text=True)
        log("  GitHub Pages 로 발행 완료")
    except subprocess.CalledProcessError as e:
        log(f"  WARNING: GitHub 발행 실패: {e.stderr or e}")


def main():
    config = load_config()
    seen = load_seen()  # {etn_bid_id: first_seen_iso_date}

    log(f"입찰공고 수집 시작 ({config['region_keyword']} 지역만 서버에서 필터링)")
    all_rows = fetch_all_bids(config["bid_status_code"], config["ctpv_cd"], config["sgg_cd"], config["page_size"])
    log(f"{config['region_keyword']} 지역 공고 {len(all_rows)}건 수집")

    now_str = datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]
    matches = [r for r in all_rows if matches_filter(r, config["item_keywords"], config.get("exclude_keywords", []), now_str)]
    log(f"품목 키워드에 맞는 공고 {len(matches)}건")

    enrich_with_detail(matches)
    log("상세정보(기초가격/입찰기간/개찰일시 등) 보강 완료")

    seen_before = dict(seen)  # snapshot for dashboard/email "NEW" marking
    matches_sorted = sorted(matches, key=lambda r: r.get("BID_END_DT", ""))
    new_count = sum(1 for r in matches_sorted if r.get("ETN_BID_ID") not in seen_before)
    log(f"신규 공고 {new_count}건")

    if new_count:
        try:
            tagged = [(r, r.get("ETN_BID_ID") not in seen_before) for r in matches_sorted]
            send_email(tagged, new_count, config)
            log(f"이메일 발송 완료 (신규 {new_count}건 · 전체 {len(matches_sorted)}건)")
        except Exception as e:
            log(f"ERROR: 이메일 발송 실패: {e}")

    today = datetime.now().strftime("%Y-%m-%d")
    for r in matches:
        bid_id = r.get("ETN_BID_ID")
        if bid_id and bid_id not in seen:
            seen[bid_id] = today

    # prune bids not seen again for 60+ days (closed/expired, keep file small)
    cutoff = datetime.now() - timedelta(days=60)
    current_ids = {r.get("ETN_BID_ID") for r in matches}
    pruned = {}
    for bid_id, first_seen in seen.items():
        if bid_id in current_ids:
            pruned[bid_id] = first_seen
        else:
            try:
                if datetime.strptime(first_seen, "%Y-%m-%d") > cutoff:
                    pruned[bid_id] = first_seen
            except Exception:
                pruned[bid_id] = first_seen
    seen = pruned

    save_seen(seen)
    write_dashboard(matches, seen_before, config)
    log(f"dashboard.html 갱신 완료 -> {DASHBOARD_PATH}")

    publish_to_github(config)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        sys.exit(1)
