# ☕ 스타벅스 코리아 전국 매장 현황 대시보드

> **GitHub Actions + GitHub Pages** 기반 자동화 대시보드  
> 매주 월요일 자동으로 데이터를 수집하고 대시보드를 갱신합니다.

---

## 📁 프로젝트 구조

```
starbucks-dashboard/
├── .github/
│   └── workflows/
│       └── update_data.yml     # GitHub Actions 스케줄 워크플로우
├── data/
│   └── stores.json             # 수집된 매장 데이터 (자동 생성)
├── scripts/
│   └── scrape.py               # 스타벅스 API 스크래퍼
├── index.html                  # 대시보드 (GitHub Pages)
└── README.md
```

---

## 🚀 설정 방법 (5단계)

### 1. 저장소 생성 및 코드 업로드

```bash
git init starbucks-dashboard
cd starbucks-dashboard
# 파일 복사 후
git add .
git commit -m "초기 커밋"
git remote add origin https://github.com/YOUR_USERNAME/starbucks-dashboard.git
git push -u origin main
```

### 2. GitHub Pages 활성화

1. 저장소 → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main** / **/ (root)**
4. **Save** 클릭
5. 약 2~3분 후 `https://YOUR_USERNAME.github.io/starbucks-dashboard/` 접근 가능

### 3. GitHub Actions 권한 설정

1. **Settings** → **Actions** → **General**
2. **Workflow permissions** → **Read and write permissions** 선택
3. **Save** 클릭

### 4. 첫 데이터 수집 (수동 실행)

1. **Actions** 탭 → **스타벅스 매장 데이터 자동 수집**
2. **Run workflow** → **Run workflow** 클릭
3. 약 3~5분 소요 후 `data/stores.json` 자동 커밋됨

### 5. 완료

`https://viztabviz-lab.github.io/starbucks-dashboard/` 에서 대시보드 확인 ✅

---

## ⏰ 자동화 스케줄

| 트리거 | 내용 |
|--------|------|
| `cron: '0 21 * * 0'` | 매주 일요일 21:00 UTC = **월요일 오전 6:00 KST** |
| `workflow_dispatch` | Actions 탭에서 수동 실행 가능 |

---

## 📊 대시보드 기능

| 기능 | 설명 |
|------|------|
| KPI 카드 | 전체 매장 수 · DT 비율 · 리저브 수 · 최다 집중 지역 |
| 지역별 차트 | 17개 시·도별 일반/DT 스택 바 차트 |
| 구·군별 차트 | 상위 15개 지역 가로 바 차트 |
| 인터랙티브 지도 | Leaflet 기반 전국 도트맵 · 지역별 색상 · 유형 필터 |
| 매장 검색 | 매장명·주소 텍스트 검색 + 지역·유형 필터 |
| 마지막 업데이트 | 헤더에 수집 시각 표시 |

---

## 🛠 로컬 실행

```bash
# 의존성 설치
pip install requests openpyxl pandas

# 데이터 수집
python scripts/scrape.py

# 로컬 서버 (data/stores.json 로드에 필요)
python -m http.server 8000
# → http://localhost:8000 접속
```

> ⚠️ `index.html`을 직접 파일로 열면 CORS 오류가 발생합니다.  
> 반드시 로컬 HTTP 서버를 통해 접근하세요.

---

## 🔧 커스터마이징

### 수집 주기 변경 (`.github/workflows/update_data.yml`)

```yaml
# 매일 오전 6시 KST 수집
- cron: '0 21 * * *'

# 매월 1일 수집
- cron: '0 21 1 * *'
```

### API 오류 시 확인 사항

스타벅스 웹사이트 구조가 변경된 경우 `scripts/scrape.py`의 다음을 수정:
- `API_ENDPOINTS` 목록
- 응답 JSON 필드명 (`s_name`, `address`, `lat`, `lot`)

---

## 📄 라이선스

매장 데이터는 Starbucks Korea 소유입니다. 본 프로젝트는 교육·분석 목적으로만 사용하세요.
