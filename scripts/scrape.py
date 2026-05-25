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
        const els = Array.from(document.querySelectorAll('*'))
            .filter(e => (e.textContent||'').trim() === '{text}' && e.children.length === 0);
        els.forEach(e => e.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}})));
    }}
    """)

def is_store_list(data):
    lst = data.get('list', data.get('stores', []))
    if not isinstance(lst, list) or len(lst) == 0:
        return False
    s = lst[0]
    return bool(s.get('s_name') or (s.get('lat') and s.get('lot')))

def scrape():
    all_stores = []
    seen = set()

    def add(lst, region):
        for s in lst:
            st = to_store(s, region)
            if st:
                k = (st['n'], st['lat'], st['lng'])
                if k not in seen:
                    seen.add(k)
                    all_stores.append(st)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
                                    args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = ctx.new_page()

        responses = []
        requests  = []

        def on_response(resp):
            if resp.status == 200:
                try:
                    if 'json' in resp.headers.get('content-type',''):
                        responses.append({'url': resp.url, 'data': resp.json()})
                except: pass

        def on_request(req):
            if req.method == 'POST':
                requests.append({'url': req.url, 'body': req.post_data or ''})

        page.on('response', on_response)
        page.on('request',  on_request)

        print("페이지 접속...")
        page.goto('https://www.starbucks.co.kr/store/store_map.do?disp=locale',
                  wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)

        # ── 1. 서울 클릭 → 구군 엔드포인트 ──────────────────────
        responses.clear(); requests.clear()
        js_click(page, '서울')
        page.wait_for_timeout(2500)

        gugun_r = next((r for r in responses if 'gugun' in r['url'].lower()), None)
        if not gugun_r:
            print(f"구군 엔드포인트 미발견: {[r['url'] for r in responses]}")
            browser.close(); return []

        gugun_path   = '/' + '/'.join(gugun_r['url'].split('/')[3:]).split('?')[0]
        gugun_req    = next((r for r in requests if 'gugun' in r['url'].lower()), {})
        gugun_body_t = gugun_req.get('body','')  # 실제 요청 바디 템플릿

        seoul_guguns = gugun_r['data'].get('list', gugun_r['data'].get('data',[]))
        print(f"구군 엔드포인트: {gugun_path}")
        print(f"구군 요청 바디: {gugun_body_t}")
        print(f"서울 구군: {len(seoul_guguns)}개")

        if not seoul_guguns:
            print("구군 목록 비어 있음")
            browser.close(); return []

        first_gugun = seoul_guguns[0]
        fg_name = first_gugun.get('gugun_nm', first_gugun.get('name',''))
        fg_cd   = first_gugun.get('gugun_cd', first_gugun.get('cd',''))
        print(f"첫 구군: {fg_name} (cd={fg_cd})")

        # ── 2. 첫 구군 클릭 → 매장 엔드포인트 & 파라미터 ─────────
        responses.clear(); requests.clear()
        js_click(page, fg_name)
        page.wait_for_timeout(2500)

        store_r   = next((r for r in responses if is_store_list(r['data'])), None)
        store_req = next((r for r in requests if
                          r['url'] == (store_r['url'] if store_r else '')), {})

        if not store_r:
            print(f"매장 엔드포인트 미발견: {[r['url'] for r in responses]}")
            browser.close(); return []

        store_path = '/' + '/'.join(store_r['url'].split('/')[3:]).split('?')[0]
        sample_body = store_req.get('body','')
        print(f"\n✅ 매장 엔드포인트: {store_path}")
        print(f"   실제 요청 바디: {sample_body}")

        # 첫 구군 저장
        first_lst = store_r['data'].get('list', store_r['data'].get('stores',[]))
        add(first_lst, '서울')
        print(f"   첫 구군({fg_name}): {len(first_lst)}개")

        # ── 3. 요청 바디에서 파라미터 키 추출 ─────────────────────
        # 예: "p_sido_nm=서울&p_gugun_nm=강남구&p_gugun_cd=01&iend=100"
        import urllib.parse
        params = dict(urllib.parse.parse_qsl(sample_body))
        print(f"   파라미터 키: {list(params.keys())}")

        sido_key   = next((k for k in params if 'sido' in k.lower()), None)
        gugun_key  = next((k for k in params if 'gugun_n' in k.lower() or 'gugun_nm' in k.lower()), None)
        guguncd_key= next((k for k in params if 'gugun_cd' in k.lower()), None)
        iend_key   = next((k for k in params if 'iend' in k.lower()), 'iend')
        print(f"   sido키={sido_key}, gugun_nm키={gugun_key}, gugun_cd키={guguncd_key}, iend키={iend_key}")

        # ── 4. 전 시/도 × 구군 순회 ──────────────────────────────
        for sido_nm in SIDO_NAMES:
            # 시/도 클릭 → 구군 목록
            responses.clear()
            js_click(page, sido_nm)
            page.wait_for_timeout(1800)

            gr = next((r for r in responses if 'gugun' in r['url'].lower()), None)
            if gr:
                guguns = gr['data'].get('list', gr['data'].get('data',[]))
            else:
                # JS fetch 직접
                result = page.evaluate(f"""
                async () => {{
                    const r = await fetch('{gugun_path}', {{
                        method: 'POST', credentials: 'include',
                        headers: {{'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'}},
                        body: '{gugun_body_t}'.replace(/=\\S+(&|$)/g, m => m)
                            .replace(/(sido_nm=)[^&]+/, '$1{sido_nm}')
                    }});
                    return r.ok ? await r.json() : {{error: r.status}};
                }}
                """)
                guguns = result.get('list', result.get('data',[])) if result and 'error' not in result else []

            if not guguns:
                print(f"[{sido_nm}] 구군 목록 없음 — 건너뜀")
                continue

            print(f"[{sido_nm}] {len(guguns)}개 구군", end='', flush=True)
            sido_count = 0

            for gugun in guguns:
                gname = gugun.get('gugun_nm', gugun.get('name',''))
                gcd   = gugun.get('gugun_cd', gugun.get('cd',''))
                if not gname: continue

                # 실제 파라미터 키 사용
                body_parts = dict(params)  # 템플릿 복사
                body_parts[iend_key] = '2000'
                if sido_key:   body_parts[sido_key]    = sido_nm
                if gugun_key:  body_parts[gugun_key]   = gname
                if guguncd_key:body_parts[guguncd_key] = gcd

                body_str = urllib.parse.urlencode(body_parts)

                result = page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch('{store_path}', {{
                            method: 'POST', credentials: 'include',
                            headers: {{
                                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                                'X-Requested-With': 'XMLHttpRequest'
                            }},
                            body: decodeURIComponent('{urllib.parse.quote(body_str)}')
                        }});
                        return r.ok ? await r.json() : {{error: r.status}};
                    }} catch(e) {{ return {{error: e.message}}; }}
                }}
                """)

                lst = []
                if result and 'list' in result:
                    lst = result['list']
                elif result and 'stores' in result:
                    lst = result['stores']

                if lst:
                    add(lst, sido_nm)
                    sido_count += len(lst)
                else:
                    # 클릭 폴백
                    responses.clear()
                    js_click(page, gname)
                    page.wait_for_timeout(1200)
                    for r in responses:
                        if is_store_list(r['data']):
                            fl = r['data'].get('list', r['data'].get('stores',[]))
                            add(fl, sido_nm)
                            sido_count += len(fl)
                            break

                page.wait_for_timeout(150)

            print(f" → {sido_count}개")

        browser.close()

    return all_stores

def build_summary(stores):
    rs, gc = {}, {}
    for s in stores:
        r = s['r']
        if r not in rs: rs[r] = {'total':0,'dt':0,'rv':0}
        rs[r]['total'] += 1; rs[r]['dt'] += s['dt']; rs[r]['rv'] += s['rv']
        p = s['a'].split()
        if len(p) >= 2: gc[p[1]] = gc.get(p[1],0)+1
    return rs, sorted(gc.items(), key=lambda x:-x[1])[:15]

if __name__ == '__main__':
    print("="*50)
    print("  스타벅스 코리아 전국 매장 데이터 수집")
    print("="*50)
    stores = scrape()
    print(f"\n총 수집: {len(stores):,}개")
    if not stores: exit(1)
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
