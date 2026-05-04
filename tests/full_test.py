"""
Full test suite for PMU Smart Analyzer after bug fixes.
"""
from playwright.sync_api import sync_playwright
import time

results = []

def test(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append({"name": name, "status": status, "detail": detail})
    print(f"  [{status}] {name}" + (f" | {detail}" if detail else ""))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    errors = []
    page.on('console', lambda msg: errors.append({'type': msg.type, 'text': msg.text}))
    
    print("\n=== TEST 1: Dashboard Load ===")
    page.goto('http://localhost:8000', wait_until='networkidle')
    
    # Check no duplicates on dashboard
    dashboard_headers = page.evaluate("""() => {
        const el = document.getElementById('dashboard-content');
        return el ? el.querySelectorAll('.hipp-header').length : 0;
    }""")
    test("Dashboard: 14 reunions (no duplicates)", dashboard_headers == 14, f"got {dashboard_headers}")
    
    cards = page.evaluate("""() => {
        const el = document.getElementById('dashboard-content');
        return el ? el.querySelectorAll('.card.clickable').length : 0;
    }""")
    test("Dashboard: 74 clickable cards (no duplicates)", cards == 74, f"got {cards}")
    
    top_picks = page.evaluate("""() => {
        const el = document.getElementById('dashboard-content');
        if (!el) return 0;
        const titles = Array.from(el.querySelectorAll('.section-title'));
        const topPickTitle = titles.find(t => t.textContent.includes('Top Picks'));
        if (!topPickTitle) return 0;
        let count = 0;
        let el2 = topPickTitle.nextElementSibling;
        while (el2 && !el2.classList.contains('section-title')) {
            if (el2.classList.contains('card')) count++;
            el2 = el2.nextElementSibling;
        }
        return count;
    }""")
    test("Dashboard: Top Picks section present", top_picks > 0, f"got {top_picks} picks")
    
    console_errors = [e for e in errors if e['type'] == 'error']
    test("Dashboard: No console errors", len(console_errors) == 0, str(console_errors[:2]))
    errors.clear()
    
    print("\n=== TEST 2: Courses Page ===")
    page.locator('.nav-item').nth(1).click()
    # Wait for courses content to populate
    try:
        page.wait_for_selector('#courses-content .hipp-header', timeout=15000)
    except:
        pass
    
    courses_headers = page.evaluate("""() => {
        const el = document.getElementById('courses-content');
        return el ? el.querySelectorAll('.hipp-header').length : 0;
    }""")
    test("Courses: 14 reunions (no duplicates)", courses_headers == 14, f"got {courses_headers}")
    
    courses_cards = page.evaluate("""() => {
        const el = document.getElementById('courses-content');
        return el ? el.querySelectorAll('.card.clickable').length : 0;
    }""")
    test("Courses: 74 course cards (no duplicates)", courses_cards == 74, f"got {courses_cards}")
    errors.clear()
    
    print("\n=== TEST 3: Course Detail ===")
    # Click first course from courses page (which is currently active)
    first_course = page.locator('#courses-content .card.clickable').first
    first_course.click()
    
    # Wait for participants
    try:
        page.wait_for_selector('.participant-row', timeout=30000)
        loaded = True
    except:
        loaded = False
    test("Course detail: loaded with participants", loaded)
    
    # Check participant count in course-content
    participant_count = page.evaluate("""() => {
        const el = document.getElementById('course-content');
        return el ? el.querySelectorAll('.participant-row').length : 0;
    }""")
    test("Course detail: 16 participants (no duplicates)", participant_count == 16, f"got {participant_count}")
    
    # Check AI suggestions section
    suggestions_count = page.evaluate("""() => {
        const el = document.getElementById('course-content');
        return el ? el.querySelectorAll('.suggestion-card').length : 0;
    }""")
    test("Course detail: AI suggestions visible", suggestions_count > 0, f"got {suggestions_count} suggestion cards")
    
    # Check no duplicate horse names in couple suggestion
    couple_horses = page.evaluate("""() => {
        const el = document.getElementById('course-content');
        if (!el) return '';
        const cards = el.querySelectorAll('.suggestion-card');
        for (const card of cards) {
            const type = card.querySelector('.suggestion-type');
            if (type && type.textContent.includes('Coup')) {
                const horses = card.querySelector('.suggestion-horses');
                return horses ? horses.textContent : '';
            }
        }
        return '';
    }""")
    has_duplicate = couple_horses and '+' in couple_horses and couple_horses.split('+')[0].strip() == couple_horses.split('+')[1].strip()
    test("Suggestions: Couple has 2 different horses", not has_duplicate, f"couple: {couple_horses}")
    
    # Check suggestion buttons use registry key approach
    btn_onclicks = page.evaluate("""() => {
        const el = document.getElementById('course-content');
        if (!el) return [];
        return Array.from(el.querySelectorAll('.suggestion-btn')).map(b => b.getAttribute('onclick'));
    }""")
    btns_ok = all(onclick and 'placeSuggestedBetByKey' in onclick for onclick in btn_onclicks)
    test("Suggestions: Buttons use placeSuggestedBetByKey", btns_ok, str(btn_onclicks[:2]))
    
    # Check suggestion buttons are actually callable
    btn_result = page.evaluate("""() => {
        return typeof window.placeSuggestedBetByKey === 'function';
    }""")
    test("Suggestions: placeSuggestedBetByKey is defined", btn_result)
    
    # Check _suggestionPayloads registry
    payloads_count = page.evaluate("""() => {
        return window._suggestionPayloads ? Object.keys(window._suggestionPayloads).length : 0;
    }""")
    test("Suggestions: Payload registry populated", payloads_count > 0, f"got {payloads_count} keys")
    
    console_errors_course = [e for e in errors if e['type'] == 'error']
    test("Course detail: No console errors", len(console_errors_course) == 0, str(console_errors_course[:2]))
    errors.clear()
    
    print("\n=== TEST 4: Bet Modal ===")
    # Click Parier button on first participant
    try:
        page.locator('.bet-btn').first.click()
        page.wait_for_selector('.modal-overlay.open', timeout=5000)
        modal_open = True
    except Exception as e:
        modal_open = False
        print(f"    Modal error: {e}")
    test("Bet modal: Opens on Parier click", modal_open)
    
    if modal_open:
        # Check modal has horse list
        horse_rows = page.evaluate("""() => {
            return document.querySelectorAll('.bet-horse-row').length;
        }""")
        test("Bet modal: Shows horse list", horse_rows > 0, f"got {horse_rows} horses")
        
        # Close modal
        page.locator('.modal-close-btn').first.click()
        time.sleep(0.5)
    errors.clear()
    
    print("\n=== TEST 5: Mes Paris Page ===")
    page.locator('.nav-item').nth(2).click()
    page.wait_for_load_state('networkidle')
    time.sleep(1)
    
    bets_content = page.evaluate("""() => {
        const el = document.getElementById('bets-content');
        return el ? el.innerHTML.substring(0, 100) : 'NOT FOUND';
    }""")
    test("Bets page: Loaded", 'NOT FOUND' not in bets_content and len(bets_content) > 10)
    
    console_errors_bets = [e for e in errors if e['type'] == 'error']
    test("Bets page: No console errors", len(console_errors_bets) == 0, str(console_errors_bets[:2]))
    
    browser.close()

print("\n=== SUMMARY ===")
passed = sum(1 for r in results if r['status'] == 'PASS')
failed = sum(1 for r in results if r['status'] == 'FAIL')
print(f"Total: {len(results)} | PASS: {passed} | FAIL: {failed}")
if failed > 0:
    print("\nFailed tests:")
    for r in results:
        if r['status'] == 'FAIL':
            print(f"  - {r['name']}: {r['detail']}")
