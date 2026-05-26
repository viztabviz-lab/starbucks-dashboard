"""
스타벅스 코리아 전국 매장 데이터 수집 스크립트 (Playwright 기반)
================================================================
실행: python scripts/scrape.py
출력: data/stores.json
"""

from playwright.sync_api import sync_playwright
import json, os, urllib.parse
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SIDO_NAMES = [
    "서울","경기","인천","강원","충북","충남","대전",
    "경북","경남","부산","울산","대구","전북","전남","광주","제주","세종"
]

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def to_store(s, region):
    name = (s.get('s_name') or s.get('name') or '').strip()
    addr = (s.get('address') or s.get('addr') or '').replace('1522-3232','').strip()
    lat  = s.get('lat','')
    lng  = s.get('lot', s.get('lng', s.get('longitude','')))
    if not name or not lat or not lng:
        return None
    return {
        'r': region, 'n': name, 'a': addr,
        'lat': round(float(lat), 5),
        'lng': round(float(lng), 5),
        'dt':  1 if name.endswith('DT') else 0,
        'rv':  1 if name.endswith('R')  else 0,
    }

def js_click(page, text):
    """JavaScript 이벤트로 텍스트 요소 클릭 (visibility 무관)"""
    page.evaluate(f"""
    () => {{
        Array.from(document.querySelectorAll('*'))
            .filter(e => (e.textContent||'').trim() === '{text}' && e.children.length === 0)
            .forEach(e => e.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}})));
    }}
    """)

def is_store_list(data):
    lst = data.get('list', data.get('stores', []))
    if not isinstance(lst, list) or len(lst) == 0:
        return False
    s = lst[0]
    return bool(s.get('s_name') or (s.get('lat') and s.get('lot')))

def fetch_from_page(page, path, body_str):
    """브라우저 컨텍스트에서 POST fetch (쿠키·세션 자동 포함)"""
    escaped = body_str.replace("'", "\\'")
    return page.evaluate(f"""
    async () => {{
        try {{
            const r = await fetch('{path}', {{
                method: 'POST',
                credentials: 'include',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest'
                }},
                body: '{escaped}'
            }});
            return r.ok ? await r.json() : {{error: r.status}};
        }} catch(e) {{
            return {{error: e.message}};
        }}
    }}
    """)

# ── 메인 수집 ─────────────────────────────────────────────────────────────────

def scrape():
    all_stores = []
    seen = set()

    def add(lst, region):
        count = 0
        for s in lst:
            st = to_store(s, region)
            if st:
                k = (st['n'], st['lat'], st['lng'])
                if k not in seen:
                    seen.add(k)
                    all_stores.append(st)
                    count += 1
        return count

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage']
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = ctx.new_page()

        responses = []
        requests_log = []

        def on_response(resp):
            if resp.status == 200:
                try:
                    if 'json' in resp.headers.get('content-type',''):
                        responses.append({'url': resp.url, 'data': resp.json()})
                except: pass

        def on_request(req):
            if req.method == 'POST':
                requests_log.append({'url': req.url, 'body': req.post_data or ''})

        page.on('response', on_response)
        page.on('request',  on_request)

        # ── 1. 페이지 접속 ──────────────────────────────────────────────────────
        print("페이지 접속...")
        page.goto(
            'https://www.starbucks.co.kr/store/store_map.do?disp=locale',
            wait_until='networkidle', timeout=30000
        )
        page.wait_for_timeout(3000)

        # ── 2. 서울 클릭 → 구군 엔드포인트 발견 ────────────────────────────────
        responses.clear(); requests_log.clear()
        js_click(page, '서울')
        page.wait_for_timeout(2500)

        gugun_r   = next((r for r in responses if 'gugun' in r['url'].lower()), None)
        gugun_req = next((r for r in requests_log if 'gugun' in r['url'].lower()), {})

        if not gugun_r:
            print(f"❌ 구군 엔드포인트 미발견: {[r['url'] for r in responses]}")
            browser.close()
            return []

        gugun_path   = '/' + '/'.join(gugun_r['url'].split('/')[3:]).split('?')[0]
        gugun_body_t = gugun_req.get('body','')
        seoul_guguns = gugun_r['data'].get('list', gugun_r['data'].get('data',[]))
        print(f"구군 엔드포인트: {gugun_path}")
        print(f"서울 구군: {len(seoul_guguns)}개")

        # ── 3. 첫 구군 클릭 → 매장 엔드포인트 발견 ─────────────────────────────
        first_name = seoul_guguns[0].get('gugun_nm', seoul_guguns[0].get('name',''))
        responses.clear(); requests_log.clear()
        js_click(page, first_name)
        page.wait_for_timeout(2500)

        store_r   = next((r for r in responses if is_store_list(r['data'])), None)
        store_req = next((r for r in requests_log
                          if r['url'] == (store_r['url'] if store_r else '')), {})

        if not store_r:
            print(f"❌ 매장 엔드포인트 미발견: {[r['url'] for r in responses]}")
            browser.close()
            return []

        store_path   = '/' + '/'.join(store_r['url'].split('/')[3:]).split('?')[0]
        sample_body  = store_req.get('body','')
        params       = dict(urllib.parse.parse_qsl(sample_body))

        print(f"매장 엔드포인트: {store_path}")
        print(f"파라미터 키: {list(params.keys())}")

        # 첫 구군 매장 저장
        first_lst = store_r['data'].get('list', store_r['data'].get('stores',[]))
        cnt = add(first_lst, '서울')
        print(f"\n[서울] {len(seoul_guguns)}개 구군 수집 중...")
        print(f"  {first_name}: {cnt}개")

        # 파라미터 키 추출
        sido_key    = next((k for k in params if 'sido'    in k.lower()), None)
        gugun_key   = next((k for k in params if 'gugun_n' in k.lower() or 'gugun_nm' in k.lower()), None)
        guguncd_key = next((k for k in params if 'gugun_cd' in k.lower()), None)
        iend_key    = next((k for k in params if 'iend'    in k.lower()), 'iend')

        def build_body(sido_nm, gname, gcd, iend='2000'):
            p = dict(params)
            p[iend_key] = iend
            if sido_key:    p[sido_key]    = sido_nm
            if gugun_key:   p[gugun_key]   = gname
            if guguncd_key: p[guguncd_key] = gcd
            return urllib.parse.urlencode(p)

        def collect_gugun(sido_nm, gname, gcd):
            """구군별 매장 수집 (fetch 우선, 클릭 폴백)"""
            body = build_body(sido_nm, gname, gcd)
            result = fetch_from_page(page, store_path, body)
            lst = []
            if result and 'list' in result:
                lst = result['list']
            elif result and 'stores' in result:
                lst = result['stores']
            if lst:
                return add(lst, sido_nm)
            # 클릭 폴백
            responses.clear()
            js_click(page, gname)
            page.wait_for_timeout(1200)
            for r in responses:
                if is_store_list(r['data']):
                    fl = r['data'].get('list', r['data'].get('stores',[]))
                    return add(fl, sido_nm)
            return 0

        def collect_sido_all(sido_nm):
            """
            시/도 전체 한 번에 수집 (누락 방지용 보완 수집)
            구군을 빈 값으로 보내면 해당 시도 전체 매장을 반환함
            """
            body = build_body(sido_nm, '', '', iend='2000')
            result = fetch_from_page(page, store_path, body)
            lst = []
            if result and 'list' in result:
                lst = result['list']
            elif result and 'stores' in result:
                lst = result['stores']
            return add(lst, sido_nm)

        # ── 4. 서울 나머지 구군 수집 ────────────────────────────────────────────
        for gugun in seoul_guguns[1:]:
            gname = gugun.get('gugun_nm', gugun.get('name',''))
            gcd   = gugun.get('gugun_cd', gugun.get('cd',''))
            if not gname: continue
            cnt = collect_gugun('서울', gname, gcd)
            print(f"  {gname}: {cnt}개")
            page.wait_for_timeout(150)

        # 서울 전체 보완 수집 (누락 방지)
        extra = collect_sido_all('서울')
        if extra: print(f"  ↳ 전체 보완: +{extra}개")

        # ── 5. 나머지 시/도 수집 ────────────────────────────────────────────────
        for sido_nm in SIDO_NAMES[1:]:   # 서울은 위에서 처리
            responses.clear()
            js_click(page, sido_nm)
            page.wait_for_timeout(1800)

            gr = next((r for r in responses if 'gugun' in r['url'].lower()), None)
            if gr:
                guguns = gr['data'].get('list', gr['data'].get('data',[]))
            else:
                # 직접 fetch
                body_g = gugun_body_t
                if sido_nm and sido_key:
                    # sido_nm으로 교체
                    parts_g = dict(urllib.parse.parse_qsl(body_g))
                    for k in parts_g:
                        if 'sido' in k.lower():
                            parts_g[k] = sido_nm
                    body_g = urllib.parse.urlencode(parts_g)
                result_g = fetch_from_page(page, gugun_path, body_g)
                guguns = result_g.get('list', result_g.get('data',[])) if result_g and 'error' not in result_g else []

            if not guguns:
                print(f"[{sido_nm}] 구군 목록 없음 — 건너뜀")
                continue

            print(f"[{sido_nm}] {len(guguns)}개 구군 수집 중...")
            sido_count = 0

            for gugun in guguns:
                gname = gugun.get('gugun_nm', gugun.get('name',''))
                gcd   = gugun.get('gugun_cd', gugun.get('cd',''))
                if not gname: continue
                cnt = collect_gugun(sido_nm, gname, gcd)
                sido_count += cnt
                page.wait_for_timeout(150)

            # 시/도 전체 보완 수집 (누락 방지)
            extra = collect_sido_all(sido_nm)
            if extra:
                sido_count += extra
                print(f"  ↳ 전체 보완: +{extra}개")

            print(f"  → 합계: {sido_count}개")

        browser.close()

    return all_stores

# ── 집계 & 저장 ───────────────────────────────────────────────────────────────

def build_summary(stores):
    rs, gc = {}, {}
    for s in stores:
        r = s['r']
        if r not in rs: rs[r] = {'total':0,'dt':0,'rv':0}
        rs[r]['total'] += 1
        rs[r]['dt']    += s['dt']
        rs[r]['rv']    += s['rv']
        parts = s['a'].split()
        if len(parts) >= 2:
            gc[parts[1]] = gc.get(parts[1], 0) + 1
    return rs, sorted(gc.items(), key=lambda x:-x[1])[:15]

if __name__ == '__main__':
    print("=" * 55)
    print("  스타벅스 코리아 전국 매장 데이터 수집")
    print("=" * 55)

    stores = scrape()
    print(f"\n총 수집: {len(stores):,}개")

    if not stores:
        print("❌ 수집 실패")
        exit(1)

    region_stats, top_gu = build_summary(stores)
    os.makedirs('data', exist_ok=True)

    payload = {
        'updated':      datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
        'total':        len(stores),
        'dt_count':     sum(s['dt'] for s in stores),
        'rv_count':     sum(s['rv'] for s in stores),
        'region_stats': region_stats,
        'top_gu':       top_gu,
        'stores':       stores,
    }

    with open('data/stores.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',',':'))

    kb = os.path.getsize('data/stores.json') // 1024
    print(f"✅ 저장 완료: data/stores.json ({kb} KB)")
    print(f"   업데이트: {payload['updated']}")
