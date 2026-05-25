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

def to_store(s, region):
    name = s.get('s_name', s.get('name', '')).strip()
    addr = s.get('address', s.get('addr', '')).replace('1522-3232','').strip()
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
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage']
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = ctx.new_page()

        print("스타벅스 페이지 접속 중...")
        page.goto(
            'https://www.starbucks.co.kr/store/store_map.do?disp=locale',
            wait_until='networkidle', timeout=30000
        )
        page.wait_for_timeout(3000)
        print(f"접속 완료: {page.title()}")

        for region, (sido_cd, lat, lng) in SIDO.items():
            print(f"  [{region}] 수집 중...", end=' ', flush=True)
            try:
                result = page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch('/store/getStoreListJson.do', {{
                            method: 'POST',
                            credentials: 'include',
                            headers: {{
                                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                                'X-Requested-With': 'XMLHttpRequest',
                                'Accept': 'application/json, text/javascript, */*; q=0.01'
                            }},
                            body: new URLSearchParams({{
                                ins_lat: '{lat}', ins_lng: '{lng}',
                                p_sido_cd: '{sido_cd}', p_gugun_cd: '',
                                in_biz_cd: '', set_date: '', iend: '2000'
                            }}).toString()
                        }});
                        if (!r.ok) return {{error: r.status}};
                        return await r.json();
                    }} catch(e) {{
                        return {{error: e.message}};
                    }}
                }}
                """)

                if result and 'list' in result:
                    stores = [to_store(s, region) for s in result['list']]
                    stores = [s for s in stores if s]
                    all_stores.extend(stores)
                    print(f"{len(stores)}개")
                else:
                    print(f"응답 없음: {result}")

            except Exception as e:
                print(f"오류: {e}")

            page.wait_for_timeout(400)

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
            gu_count[parts[1]] = gu_count.get(parts[1],0) + 1
    return region_stats, sorted(gu_count.items(), key=lambda x:-x[1])[:15]

if __name__ == '__main__':
    print("="*50)
    print("  스타벅스 코리아 전국 매장 데이터 수집")
    print("="*50)
    stores = scrape()
    print(f"\n총 수집: {len(stores):,}개")

    if not stores:
        print("수집 실패")
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
    with open('data/stores.json','w',encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, separators=(',',':'))
    kb = os.path.getsize('data/stores.json')//1024
    print(f"저장 완료: data/stores.json ({kb} KB)")
