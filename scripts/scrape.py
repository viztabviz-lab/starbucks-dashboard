from playwright.sync_api import sync_playwright
import json, os, re
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

def scrape():
    all_stores = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = ctx.new_page()

        # ── 1. 모든 네트워크 요청 캡처 ──────────────────────────
        captured_requests  = []
        captured_responses = []

        def on_request(req):
            try:
                if req.resource_type in ('xhr','fetch'):
                    captured_requests.append({
                        'method': req.method,
                        'url': req.url,
                        'body': req.post_data or ''
                    })
            except:
                captured_requests.append({
                    'method': req.method,
                    'url': req.url,
                    'body': ''
                })

        def on_response(resp):
            if resp.status != 200:
                return
            try:
                ct = resp.headers.get('content-type','')
                if 'json' not in ct:
                    return
                d = resp.json()
                lst = d.get('list', d.get('stores', d.get('data',[])))
                if isinstance(lst, list) and len(lst) > 0:
                    captured_responses.append({
                        'url': resp.url,
                        'count': len(lst),
                        'data': d
                    })
            except:
                pass

        page.on('request',  on_request)
        page.on('response', on_response)

        print("페이지 접속 중...")
        page.goto('https://www.starbucks.co.kr/store/store_map.do?disp=locale',
                  wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)

        # ── 2. 페이지 소스에서 엔드포인트 패턴 탐색 ──────────────
        html = page.content()
        found_urls = set(re.findall(r'["\']([^"\']*\.do[^"\']*)["\']', html))
        store_urls = [u for u in found_urls if 'store' in u.lower() or 'Store' in u]
        print(f"\n[진단] 페이지 소스 내 store 관련 URL:")
        for u in sorted(store_urls)[:20]:
            print(f"  {u}")

        # ── 3. 지역 선택 UI 구조 탐색 ────────────────────────────
        ui_info = page.evaluate("""
        () => {
            const REGIONS = ['서울','경기','인천','강원','충북','충남','대전',
                             '경북','경남','부산','울산','대구','전북','전남','광주','제주','세종'];
            const found = [];
            document.querySelectorAll('*').forEach(el => {
                const t = (el.textContent || '').trim();
                if (!REGIONS.includes(t)) return;
                const rect = el.getBoundingClientRect();
                const oc = el.getAttribute('onclick') || '';
                found.push({
                    tag: el.tagName, text: t,
                    id: el.id || '', cls: (el.className||'').substring(0,60),
                    onclick: oc, href: el.getAttribute('href') || '',
                    visible: rect.width > 0 && rect.height > 0,
                    x: Math.round(rect.x), y: Math.round(rect.y)
                });
            });
            return found.slice(0, 30);
        }
        """)
        print(f"\n[진단] '서울' 등 지역명 보유 요소 ({len(ui_info)}개):")
        for el in ui_info:
            print(f"  <{el['tag']}> '{el['text']}' visible={el['visible']} onclick='{el['onclick'][:60]}' cls='{el['cls'][:40]}'")

        # ── 4. onclick 함수명 추출 후 JS로 직접 호출 ─────────────
        onclick_pattern = re.compile(r"(\w+)\s*\(")
        fn_candidates = set()
        for el in ui_info:
            m = onclick_pattern.match(el.get('onclick',''))
            if m:
                fn_candidates.add(m.group(1))
        print(f"\n[진단] onclick 함수 후보: {fn_candidates}")

        # 각 후보 함수에 sido_cd 인자 전달 시도
        for fn_name in fn_candidates:
            print(f"\n[시도] {fn_name}('01') 호출...")
            captured_requests.clear()
            captured_responses.clear()
            try:
                page.evaluate(f"if(typeof {fn_name}==='function') {fn_name}('01')")
                page.wait_for_timeout(2500)
            except: pass
            if captured_responses:
                r = captured_responses[-1]
                print(f"  ✅ 성공! URL={r['url']} count={r['count']}")
            else:
                req_urls = [r['url'] for r in captured_requests]
                print(f"  요청 발생: {req_urls[:3]}")

        # ── 5. 캡처된 응답이 있으면 전 지역 수집 ─────────────────
        if captured_responses:
            working_url = captured_responses[-1]['url']
            path = '/' + '/'.join(working_url.split('/')[3:]).split('?')[0]
            print(f"\n작동하는 엔드포인트: {path}")

            for region, (sido_cd, lat, lng) in SIDO.items():
                captured_responses.clear()
                print(f"  [{region}] ...", end=' ', flush=True)
                for fn_name in fn_candidates:
                    try:
                        page.evaluate(f"if(typeof {fn_name}==='function') {fn_name}('{sido_cd}')")
                        page.wait_for_timeout(2000)
                        if captured_responses: break
                    except: pass
                if captured_responses:
                    lst = captured_responses[-1]['data'].get('list',
                          captured_responses[-1]['data'].get('stores',[]))
                    stores = [to_store(s, region) for s in lst]
                    stores = [s for s in stores if s]
                    all_stores.extend(stores)
                    print(f"{len(stores)}개")
                else:
                    print("미수집")
        else:
            print("\n\n⚠️  자동 수집 실패. 위 [진단] 정보를 Claude에게 붙여넣어 주세요.")

        browser.close()

    return all_stores

if __name__ == '__main__':
    print("="*50)
    print("  스타벅스 코리아 전국 매장 데이터 수집")
    print("="*50)
    stores = scrape()
    print(f"\n총 수집: {len(stores):,}개")

    if not stores:
        exit(1)

    region_stats, gu_count = {}, {}
    for s in stores:
        r = s['r']
        if r not in region_stats: region_stats[r] = {'total':0,'dt':0,'rv':0}
        region_stats[r]['total'] += 1
        region_stats[r]['dt']    += s['dt']
        region_stats[r]['rv']    += s['rv']
        parts = s['a'].split()
        if len(parts) >= 2:
            gu_count[parts[1]] = gu_count.get(parts[1],0) + 1

    top_gu = sorted(gu_count.items(), key=lambda x:-x[1])[:15]
    os.makedirs('data', exist_ok=True)
    payload = {
        'updated': datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
        'total': len(stores), 'dt_count': sum(s['dt'] for s in stores),
        'rv_count': sum(s['rv'] for s in stores),
        'region_stats': region_stats, 'top_gu': top_gu, 'stores': stores,
    }
    with open('data/stores.json','w',encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',',':'))
    print(f"저장 완료 ({os.path.getsize('data/stores.json')//1024} KB)")
