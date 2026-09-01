# 포항 축산·육류 학교급식 입찰 알리미

공공급식통합플랫폼(ns.eat.co.kr)의 공개 API를 매일 아침 자동으로 조회해,
포항시 소재 학교급식 입찰공고 중 축산/육류 관련 키워드가 들어간 공고만 걸러서

- 새 공고가 있으면 **이메일**로 알리고 (전체 현황 + 신규 표시)
- 현재 조건에 맞는 전체 목록을 **GitHub Pages**(`index.html`)로 공개합니다.

**GitHub Actions**로 매일 12:10(KST) 자동 실행됩니다 — 개인 PC가 꺼져 있어도 동작합니다.
(정각은 GitHub 서버 혼잡으로 지연되기 쉬워 10분 오프셋을 둠)

## 최초 설정 (한 번만)

### 1. Secrets 등록
저장소 **Settings → Secrets and variables → Actions → New repository secret** 에서 3개 등록:

| Name | 값 |
|---|---|
| `SMTP_USER` | 발신용 Gmail 주소 |
| `SMTP_APP_PASSWORD` | Gmail 앱 비밀번호 (myaccount.google.com/apppasswords 에서 발급) |
| `RECIPIENT_EMAIL` | 알림 받을 이메일 주소 |

### 2. GitHub Pages 활성화
**Settings → Pages → Build and deployment → Source**: "Deploy from a branch" 선택,
Branch: `main` / `/(root)` 선택 후 저장. 몇 분 뒤
`https://<계정>.github.io/<저장소이름>/` 링크가 활성화됩니다.

### 3. 확인
**Actions** 탭 → 왼쪽의 "포항 축산 입찰 알리미" 워크플로 → **Run workflow** 버튼으로
수동 실행해서 정상 작동하는지 확인할 수 있습니다.

## 필터 조건 조정

`config.json` 의 `region_keyword`/`ctpv_cd`/`sgg_cd`/`item_keywords`/`exclude_keywords` 를 수정하면 됩니다.
(비밀번호 관련 값은 Secrets로 관리되므로 이 파일에는 실제 값을 넣지 않습니다.)

- `item_keywords`: 입찰명에 이 중 하나라도 포함되면 매칭 (예: 육류, 축산 등)
- `exclude_keywords`: 입찰명에 이 중 하나라도 포함되면 다른 조건과 상관없이 제외.
  기본값 `["부식"]` — "부식(육류)"처럼 축산 키워드가 같이 있어도 "부식" 통합구매 공고는
  축산 전용 공고가 아니므로 제외한다.

## 동작 방식

- `bid_notifier.py`: 목록 API로 지역 필터링된 공고를 가져오고, 품목 키워드로 다시 걸러
  상세 API로 기초가격/입찰기간/개찰일시 등을 보강한 뒤, 이메일 발송 + `index.html` 생성.
- `seen_ids.json`: 이미 알림을 보낸 공고 ID 기록 (워크플로가 매 실행 후 자동 커밋).
- `.github/workflows/daily.yml`: 매일 UTC 03:10(KST 12:10)에 위 스크립트를 실행하고,
  변경된 `seen_ids.json`/`index.html`을 저장소에 자동 커밋·푸시.
