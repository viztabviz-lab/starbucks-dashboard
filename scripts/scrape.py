from playwright.sync_api import sync_playwright
import json, os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SIDO_NAMES = ["서울","경기","인천","강원","충북","충남","대전",
              "경북","경남","부산","울산","대구","전북","전남","광주","제주","세종"]

def to_store(s, region):
    name = (s.get('s_name') or s.get('name') or '').strip()
    addr = (s.get('address') or s.get('addr') or '').replace('1522-3232','').strip()
    lat  = s.get('lat','')
    lng  = s.get('lot', s.get('lng', s.get('longitude','')))
    if not name or not lat or not lng:
        return None
    return {
        'r': region, 'n': name, 'a': addr,
        'lat': round(float(lat),5), 'lng': round(float(lng),5),
        'dt': 1 if ('DT' in name or '드라이브' in name) else 0,
        'rv': 1 if (name.endswith(' R') or '리저브' in name) else 0,
    }

def js_click(page, text):
    page.evaluate(f"""
    () => {{
        Array.from(document.querySelectorAll('*'))
            .filter(e => (e.textContent||'').trim() === '{text}' && e.children.length === 0)
            .forEach(e => e.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}})));
    }}
    """)

def is_store_response(data):
    lst = data.get('list', data.get('stores', []))
    if not isinstance(lst, list) or len(lst) == 0:
        return False
    sample = lst[0]
    return bool(sample.get('s_name') or (sample.get('lat') and sample.get('lot')))

def fetch_from_page(page, path, body):
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
                body: '{body}'
            }});
            if (r.ok) return await r.json();
            return {{error: r.status}};
        }} catch(e) {{
            return {{error: e.message}};
        }}
    }}
    """)

def scrape():
    all_stores = []
    seen = set()

    def add_stores(lst, region):
        for s in lst:
            store = to_store(s, region)
            if store:
                key = (store['n'], store['lat'], store['lng'])
                if key not in seen:
                    seen.add(key)
                    all_stores.append(store)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = ctx.new_page()

        responses = []
        def on_response(resp):
            if resp.status == 200:
                try:
                    if 'json' in resp.headers.get('content-type',''):
                        responses.append({'url': resp.url, 'data': resp.json()})
                except: pass
        page.on('response', on_response)

        print("페이지 접속...")
        page.goto('https://www.starbucks.co.kr/store/store_map.do?disp=locale',
                  wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)

        # ── 1. 서울 클릭 → 구군 목록 엔드포인트 ─────────────────
        responses.clear()
        js_click(page, '서울')
        page.wait_for_timeout(2500)

        gugun_ep = next((r['url'] for r in responses if 'gugun' in r['url'].lower()), None)
        gugun_data = next((r['data'] for r in responses if 'gugun' in r['url'].lower()), {})
        seoul_guguns = gugun_data.get('list', gugun_data.get('data', []))

        if not gugun_ep or not seoul_guguns:
            print(f"구군 목록 실패: {[r['url'] for r in responses]}")
            browser.close()
            return []

        gugun_path = '/' + '/'.join(gugun_ep.split('/')[3:]).split('?')[0]
        print(f"구군 엔드포인트: {gugun_path} ({len(seoul_guguns)}개)")

        # ── 2. 첫 구군 클릭 → 매장 엔드포인트 발견 ──────────────
        first_name = seoul_guguns[0].get('gugun_nm', seoul_guguns[0].get('name',''))
        responses.clear()
        js_click(page, first_name)
        page.wait_for_timeout(2500)

        store_ep  = next((r['url'] for r in responses if is_store_response(r['data'])), None)
        store_data = next((r['data'] for r in responses if is_store_response(r['data'])), {})

        if not store_ep:
            print(f"매장 엔드포인트 미발견. 캡처: {[r['url'] for r in responses]}")
            browser.close()
            return []

        store_path = '/' + '/'.join(store_ep.split('/')[3:]).split('?')[0]
        print(f"매장 엔드포인트: {store_path}")

        # 첫 구군 매장 저장
        add_stores(store_data.get('list', store_data.get('stores', [])), '서울')

        # ── 3. 전 시/도 순회 ──────────────────────────────────────
        for sido_nm in SIDO_NAMES:
            # 구군 목록 가져오기
            result = fetch_from_page(page, gugun_path, f'p_sido_nm={sido_nm}')
            guguns = result.get('list', result.get('data', [])) if result and 'error' not in result else []

            if not guguns:
                js_click(page, sido_nm)
                page.wait_for_timeout(1500)
                gugun_resp = next((r['data'] for r in responses if 'gugun' in r['url'].lower()), {})
                guguns = gugun_resp.get('list', gugun_resp.get('data', []))

            if not guguns:
                print(f"[{sido_nm}] 구군 목록 없음")
                continue

            sido_count = 0
            print(f"[{sido_nm}] {len(guguns)}개 구군 수집 중...")

            for gugun in guguns:
                gname = gugun.get('gugun_nm', gugun.get('name',''))
                gcd   = gugun.get('gugun_cd', gugun.get('cd',''))
                if not gname:
                    continue

                # 매장 목록 직접 호출
                body = f'p_sido_nm={sido_nm}&p_gugun_nm={gname}&p_gugun_cd={gcd}&iend=500'
                result2 = fetch_from_page(page, store_path, body)

                if result2 and 'list' in result2:
                    lst = result2['list']
                    add_stores(lst, sido_nm)
                    sido_count += len(lst)
                else:
                    # 클릭 폴백
                    responses.clear()
                    js_click(page, gname)
                    page.wait_for_timeout(1200)
                    for r in responses:
                        if is_store_response(r['data']):
                            lst2 = r['data'].get('list', r['data'].get('stores',[]))
                            add_stores(lst2, sido_nm)
                            sido_count += len(lst2)
                            break

                page.wait_for_timeout(200)

            print(f"  → {sido_count}개")

        browser.close()

    return all_stores

def build_summary(stores):
    rs, gc = {}, {}
    for s in stores:
        r = s['r']
        if r not in rs: rs[r] = {'total':0,'dt':0,'rv':0}
        rs[r]['total'] += 1
        rs[r]['dt'] += s['dt']
        rs[r]['rv'] += s['rv']
        p = s['a'].split()
        if len(p) >= 2: gc[p[1]] = gc.get(p[1],0)+1
    return rs, sorted(gc.items(), key=lambda x:-x[1])[:15]

if __name__ == '__main__':
    print("="*50)
    print("  스타벅스 코리아 전국 매장 데이터 수집")
    print("="*50)
    stores = scrape()
    print(f"\n총 수집: {len(stores):,}개")
    if not stores:
        exit(1)
    rs, top_gu = build_summary(stores)
    os.makedirs('data', exist_ok=True)
    payload = {
        'updated': datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
        'total': len(stores), 'dt_count': sum(s['dt'] for s in stores),
        'rv_count': sum(s['rv'] for s in stores),
        'region_stats': rs, 'top_gu': top_gu, 'stores': stores,
    }
    with open('data/stores.json','w',encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',',':'))
    print(f"저장 완료 ({os.path.getsize('data/stores.json')//1024} KB)")
