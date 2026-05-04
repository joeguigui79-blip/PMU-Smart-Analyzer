from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    errors = []
    page.on('console', lambda msg: errors.append({'type': msg.type, 'text': msg.text}))
    
    page.goto('http://localhost:8000', wait_until='networkidle')
    
    # Click on first course
    page.locator('.card.clickable').first.click()
    page.wait_for_load_state('networkidle')
    
    # Check the course detail page
    course_page = page.query_selector('#page-course')
    is_active = 'active' in (course_page.get_attribute('class') or '')
    print('page-course is active:', is_active)
    
    # Check course-content
    course_content = page.evaluate("""() => {
        const el = document.getElementById('course-content');
        return el ? el.innerHTML.substring(0, 2000) : 'NOT FOUND';
    }""")
    print('course-content HTML (first 2000):')
    print(course_content[:2000])
    
    # Check all section titles in entire DOM
    all_titles = page.evaluate("""() => {
        const els = document.querySelectorAll('.section-title');
        return Array.from(els).map(e => ({text: e.textContent, visible: e.offsetParent !== null}));
    }""")
    print('\nAll section titles:', all_titles)
    
    # Check suggestion cards
    all_suggestions = page.evaluate("""() => {
        const els = document.querySelectorAll('.suggestion-card');
        return {count: els.length, visible: Array.from(els).filter(e => e.offsetParent !== null).length};
    }""")
    print('Suggestion cards:', all_suggestions)
    
    # Check participant rows
    all_participants = page.evaluate("""() => {
        const els = document.querySelectorAll('.participant-row');
        return {count: els.length, visible: Array.from(els).filter(e => e.offsetParent !== null).length};
    }""")
    print('Participant rows:', all_participants)
    
    # Console errors
    print('\nConsole errors:', [e for e in errors if e['type'] == 'error'])
    print('Console logs:', [e for e in errors if e['type'] != 'error'][:10])
    
    browser.close()
