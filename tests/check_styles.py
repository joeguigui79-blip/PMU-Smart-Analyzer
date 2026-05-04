from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    page.goto('http://localhost:8000', wait_until='networkidle')
    
    result1 = page.evaluate("""() => {
        const dashboard = document.getElementById('page-dashboard');
        const styles = window.getComputedStyle(dashboard);
        return {display: styles.display, visibility: styles.visibility, opacity: styles.opacity, position: styles.position};
    }""")
    print('Dashboard (active) styles:', result1)
    
    result2 = page.evaluate("""() => {
        const courses = document.getElementById('page-courses');
        const styles = window.getComputedStyle(courses);
        return {display: styles.display, visibility: styles.visibility, opacity: styles.opacity, position: styles.position};
    }""")
    print('Courses (inactive) styles:', result2)
    
    # Check if navigating to courses page shows duplicates visually
    # Look for the courses-content div
    courses_content_html = page.evaluate("""() => {
        const el = document.getElementById('courses-content');
        return el ? el.innerHTML.substring(0, 200) : 'NOT FOUND';
    }""")
    print('courses-content initial:', courses_content_html)
    
    # Navigate to courses
    page.locator('.nav-item').nth(1).click()
    page.wait_for_load_state('networkidle')
    
    # Now check courses-content
    courses_content_html2 = page.evaluate("""() => {
        const el = document.getElementById('courses-content');
        return el ? el.innerHTML.substring(0, 500) : 'NOT FOUND';
    }""")
    print('courses-content after nav:', courses_content_html2[:200])
    
    # Check dashboard still has its content
    dashboard_content_html = page.evaluate("""() => {
        const el = document.getElementById('dashboard-content');
        return el ? el.innerHTML.substring(0, 200) : 'NOT FOUND';
    }""")
    print('dashboard-content after nav to courses:', dashboard_content_html[:200])
    
    # Count hipp-headers in courses-content only
    courses_headers = page.evaluate("""() => {
        const el = document.getElementById('courses-content');
        return el ? el.querySelectorAll('.hipp-header').length : 0;
    }""")
    print('hipp-headers in courses-content:', courses_headers)
    
    dashboard_headers = page.evaluate("""() => {
        const el = document.getElementById('dashboard-content');
        return el ? el.querySelectorAll('.hipp-header').length : 0;
    }""")
    print('hipp-headers in dashboard-content:', dashboard_headers)
    
    browser.close()
