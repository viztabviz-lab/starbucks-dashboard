from playwright.sync_api import sync_playwright
import json, os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SIDO = {
    "서울":("01","37.5665","126.9780"), "경기":("02","37.4138","127.5183"),
    "인천":("03","37.4563","126.7052"), "강원":("04","37.8228","128.1555"),
    "충북":("05","36.6357","127.4912"), "충남":("06","36.5184","126.8000"),
    "대전":("07","36.3504","127.3845"), "경북":("08","36.4919","128.8889"),
    "경남":("09","35.4606","128.2132"), "부산":("10","35.1796","129.0756"),
    "울산":("11","35.5384","129.3114"), "대구":("12","35.8714","128.6014"),
    "전북":("13","35.8202","127.1089"), "전남":("14","34.8679","126.9910"),
    "광주":("15","35.1595","126.8526"), "제주":("16","33.4996","126.5312"),
    "세종":("17","36.4801","127.2890"),
}

SIDO_CENTERS = {
    "서울":("37.5665","126.9780"), "경기":("37.4138","127.5183"),
    "인천":("37.4563","126.7052"), "강원":("37.8228","128.1555"),
    "충북":("36.6357","127.4912"), "충남":("36.5184","126.8000"),
    "대전":("36.3504","127.3845"), "경북":("36.4919","128.8889"),
    "경남":("35.4606","128.2132"), "부산":("35.1796","129.0756"),
    "울산":("35.5384","129.3114"), "대구":("35.8714","128.6014"),
    "전북":("35.8202","127.1089"), "전남":("34.8679","126.9910"),
    "광주":("35.1595","126.8526"), "제주":("33.4996","126.5312"),
    "세종":("36.4801","127.2890"),
}

# getSidoList.do 인접 후보 엔드포인트 (우선순위 순)
CANDIDATE_ENDPOINTS = [
    "/store/getStoreList.do",
    "/store/getStoreListJson.do",
    "/store/getStoreListMap.do",
    "/store/searchStore.do",
    "/store/getMapStoreList.do",
    "/store/storeMap.do",
    "/store/getStoreInfo.do",
    "/store/getLocaleStore.do",
    "/store/getLocalStoreList.do",
]

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

def try_endpoint(page, ep, sido_cd, lat, lng):
    """브라우저 컨텍스트에서 POST/GET 둘 다 시도"""
    body = f"ins_lat={lat}&ins_lng={lng}&p_sido_cd={sido_cd}&p_gugun_cd=&in_biz_cd=&set_date=&iend=2000"
    result = page.evaluate(f"""
    async () => {{
        // POST 시도
        try {{
            const r = await fetch('{ep}', {{
                method: 'POST',
                credentials: 'include',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json, text/javascript, */*; q=0.01'
                }},
                body: '{body}'
            }});
            if (r.ok) {{
                const d = await r.json();
                return {{method:'POST', status:200, data:d}};
            }}
            // GET 시도
            const r2 = await fetch('{ep}?{body}', {{
                credentials: 'include',
                headers: {{'X-Requested-With':'XMLHttpRequest', 'Accept':'application/json'}}
            }});
            if (r2.ok) {{
                const d2 = await r2.json();
                return {{method:'GET', status:200, data:d2}};
            }}
            return {{status: r.status}};
        }} catch(e) {{
            return {{error: e.message}};
        }}
    }}
    """)
    return result

def scrape():
    all_stores = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = ctx.new_page()

        # 클릭으로 발생하는 모든 JSON 응답 캡처
        click_responses = []
        def on_response(resp):
            if resp.status == 200:
                try:
                    ct = resp.headers.get('content-type','')
                    if 'json' in ct:
                        d = resp.json()
                        lst = d.get('list', d.get('stores', d.get('data',[])))
                        if isinstance(lst, list) and len(lst) > 5:
                            click_responses.append({'url': resp.url, 'data': d})
                            print(f"  [캡처] {resp.url} → {len(lst)}개")
                except: pass
        page.on('response', on_response)

        print("페이지 접속 중...")
        page.goto('https://www.starbucks.co.kr/store/store_map.do?disp=locale',
                  wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)

        # ── 1단계: 후보 엔드포인트 탐색 ─────────────────────────────
        print("\n[1단계] 후보 엔드포인트 탐색 중...")
        working_ep = None
        working_method = None
        test_sido, test_lat, test_lng = "01", "37.5665", "126.9780"

        for ep in CANDIDATE_ENDPOINTS:
            result = try_endpoint(page, ep, test_sido, test_lat, test_lng)
            status = result.get('status','?') if result else '?'
            data   = result.get('data',{}) if result else {}
            lst    = data.get('list', data.get('stores', data.get('data',[])))
            if isinstance(lst, list) and len(lst) > 0:
                print(f"  ✅ {ep} ({result.get('method')}) → {len(lst)}개!")
                working_ep     = ep
                working_method = result.get('method')
                break
            else:
                print(f"  ✗  {ep} → {status}")

        # ── 2단계: 작동 엔드포인트로 전 지역 수집 ───────────────────
        if working_ep:
            print(f"\n[2단계] 전 지역 수집: {working_ep}")
            for region, (sido_cd, lat, lng) in SIDO.items():
                print(f"  [{region}] ...", end=' ', flush=True)
                result = try_endpoint(page, working_ep, sido_cd, lat, lng)
                data   = result.get('data',{}) if result else {}
                lst    = data.get('list', data.get('stores', data.get('data',[])))
                if isinstance(lst, list):
                    stores = [to_store(s, region) for s in lst]
                    stores = [s for s in stores if s]
                    all_stores.extend(stores)
                    print(f"{len(stores)}개")
                else:
                    print(f"실패: {result}")
                page.wait_for_timeout(300)

        # ── 3단계: 엔드포인트 못 찾으면 UI 클릭으로 캡처 시도 ────────
        else:
            print("\n[3단계] UI 클릭으로 실제 API 탐색 중...")
            for region in list(SIDO.keys())[:3]:
                click_responses.clear()
                page.evaluate(f"""
                () => {{
                    document.querySelectorAll('*').forEach(el => {{
                        if ((el.textContent||'').trim() === '{region}'
                            && el.children.length === 0) {{
                            el.dispatchEvent(new MouseEvent('click',
                                {{bubbles:true, cancelable:true}}));
                        }}
                    }});
                }}
                """)
                page.wait_for_timeout(2500)
                if click_responses:
                    url = click_responses[-1]['url']
                    print(f"  클릭 후 발견: {url}")
                    break

            print("\n⚠️  자동 탐색 실패.")
            print("위 로그에 표시된 URL을 Claude에게 알려주세요.")

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
