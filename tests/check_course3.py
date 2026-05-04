from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    errors = []
    page.on('console', lambda msg: errors.append({'type': msg.type, 'text': msg.text}))
    
    page.goto('http://localhost:8000', wait_until='networkidle')
    
    # Click on first course
    page.locator('.card.clickable').first.click()
    
    # Wait for content to load (not just network idle - the API takes time)
    try:
        page.wait_for_selector('.participant-row', timeout=30000)
        print('Participant rows appeared!')
    except Exception as e:
        print('Timeout waiting for participant rows:', e)
    
    # Check course-content
    course_content = page.evaluate("""() => {
        const el = document.getElementById('course-content');
        return el ? el.innerHTML.substring(0, 3000) : 'NOT FOUND';
    }""")
    print('course-content HTML (first 3000):')
    print(course_content[:3000])
    
    # Check for suggestion cards
    all_suggestions = page.evaluate("""() => {
        const els = document.querySelectorAll('.suggestion-card');
        return {count: els.length};
    }""")
    print('\nSuggestion cards:', all_suggestions)
    
    # Check all section titles
    all_titles = page.evaluate("""() => {
        const el = document.getElementById('course-content');
        if (!el) return [];
        return Array.from(el.querySelectorAll('.section-title')).map(e => e.textContent);
    }""")
    print('Section titles in course-content:', all_titles)
    
    # Console errors
    print('\nConsole errors:', [e for e in errors if e['type'] == 'error'][:5])
    
    browser.close()
