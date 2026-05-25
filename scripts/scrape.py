from playwright.sync_api import sync_playwright
import json, os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

REGIONS = [
    "서울","경기","인천","강원","충북","충남","대전",
    "경북","경남","부산","울산","대구","전북","전남",
    "광주","제주","세종"
]

def extract_from_dom(page, region):
    stores = []
    try:
        items = page.query_selector_all('[data-name][data-lat][data-long]')
        for el in items:
            name = el.get_attribute('data-name') or ''
            lat  = el.get_attribute('data-lat')  or ''
            lng  = el.get_attribute('data-long') or ''
            addr_el = el.query_selector('.result_details, .addr, .address')
            addr = addr_el.inner_text().strip() if addr_el else el.inner_text().strip()[:80]
            if name and lat and lng:
                stores.append({
                    'r': region, 'n': name.strip(),
                    'a': addr.replace('1522-3232','').strip(),
                    'lat': round(float(lat), 5),
                    'lng': round(float(lng), 5),
                    'dt': 1 if ('DT' in name or '드라이브' in name) else 0,
                    'rv': 1 if (name.endswith(' R') or '리저브' in name) else 0,
                })
    except Exception as e:
        print(f"  DOM 추출 오류: {e}")
    return stores

def scrape():
    all_stores = []
    api_stores = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR'
        )
        page = ctx.new_page()

        # API 응답 가로채기
        def on_response(response):
            if response.status != 200: return
            try:
                if 'json' not in response.headers.get('content-type',''):
                    return
                data = response.json()
                stores = data.get('list', data.get('stores', []))
                if not stores: return
                for s in stores:
                    name = s.get('s_name', s.get('name','')).strip()
                    addr = s.get('address', s.get('addr','')).replace('1522-3232','').strip()
                    lat  = s.get('lat','')
                    lng  = s.get('lot', s.get('lng', s.get('longitude','')))
                    if name and lat and lng:
                        api_stores.append({
                            'r': '미분류', 'n': name, 'a': addr,
                            'lat': round(float(lat),5), 'lng': round(float(lng),5),
                            'dt': 1 if ('DT' in name or '드라이브' in name) else 0,
                            'rv': 1 if (name.endswith(' R') or '리저브' in name) else 0,
                        })
                print(f"  API 응답: {response.url.split('/')[-1]} ({len(stores)}개)")
            except: pass

        page.on('response', on_response)

        print("페이지 접속 중...")
        page.goto('https://www.starbucks.co.kr/store/store_map.do?disp=locale',
                  wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(2000)

        # 지역 버튼 탐색
        region_buttons = {}
        for btn in page.query_selector_all('a, button, li, span'):
            try:
                text = btn.inner_text().strip()
                if text in REGIONS and text not in region_buttons:
                    region_buttons[text] = btn
            except: pass

        print(f"지역 버튼 발견: {list(region_buttons.keys())}")

        if region_buttons:
            for region in REGIONS:
                if region not in region_buttons:
                    continue
                print(f"\n[{region}] 클릭 중...")
                api_stores.clear()
                try:
                    region_buttons[region].click()
                    page.wait_for_timeout(2500)
                    # API 먼저, 없으면 DOM
                    if api_stores:
                        for s in api_stores:
                            s['r'] = region
                        all_stores.extend(api_stores)
                        print(f"  API → {len(api_stores)}개")
                    else:
                        dom = extract_from_dom(page, region)
                        all_stores.extend(dom)
                        print(f"  DOM → {len(dom)}개")
                except Exception as e:
                    print(f"  오류: {e}")
        else:
            print("지역 버튼을 찾지 못했습니다. API 전체 수집 시도...")
            page.wait_for_timeout(3000)
            all_stores = api_stores[:]

        browser.close()

    return all_stores

def build_summary(stores):
    region_stats, gu_count = {}, {}
    for s in stores:
        r = s['r']
        if r not in region_stats:
            region_stats[r] = {'total':0,'dt':0,'rv':0}
        region_stats[r]['total'] += 1
        region_stats[r]['dt']    += s['dt']
        region_stats[r]['rv']    += s['rv']
        parts = s['a'].split()
        if len(parts) >= 2:
            gu_count[parts[1]] = gu_count.get(parts[1], 0) + 1
    return region_stats, sorted(gu_count.items(), key=lambda x:-x[1])[:15]

if __name__ == '__main__':
    print("=" * 50)
    print("  스타벅스 코리아 전국 매장 데이터 수집")
    print("=" * 50)
    stores = scrape()
    print(f"\n총 수집: {len(stores)}개")

    if not stores:
        print("수집 실패 — 스타벅스 웹사이트 구조를 확인하세요.")
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
    print(f"저장 완료: data/stores.json ({os.path.getsize('data/stores.json')//1024} KB)")
