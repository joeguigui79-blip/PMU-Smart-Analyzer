from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    api_calls = []
    page.on('request', lambda req: api_calls.append(req.url) if '/api/' in req.url else None)
    
    page.goto('http://localhost:8000', wait_until='networkidle')
    
    print('API calls on page load:')
    for url in api_calls:
        print(' -', url)
    
    print('\nTotal /api/dashboard calls:', api_calls.count('http://localhost:8000/api/dashboard'))
    print('Total /api/stats calls:', api_calls.count('http://localhost:8000/api/stats'))
    print('Total /api/scoring/accuracy calls:', api_calls.count('http://localhost:8000/api/scoring/accuracy'))
    
    # Now check course detail  
    api_calls.clear()
    
    # Click on first course
    page.locator('.card.clickable').first.click()
    page.wait_for_load_state('networkidle')
    
    print('\nAPI calls on course click:')
    for url in api_calls:
        print(' -', url)
    
    # Check if participants are shown twice
    participant_rows = page.query_selector_all('.participant-row')
    print('\nParticipant rows visible:', len([r for r in participant_rows if r.is_visible()]))
    
    # Check AI suggestions
    suggestion_cards = page.query_selector_all('.suggestion-card')
    print('Suggestion cards visible:', len([s for s in suggestion_cards if s.is_visible()]))
    
    section_titles = page.query_selector_all('.section-title')
    titles = [t.inner_text() for t in section_titles if t.is_visible()]
    print('Visible section titles on course page:', titles)
    
    browser.close()
