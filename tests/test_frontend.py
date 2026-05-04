"""
Test frontend PMU Smart Analyzer - verifie le chargement sans erreur JS
Utilise un viewport mobile car la nav est masquee en desktop
"""
import pytest
from playwright.sync_api import Page, Browser


BASE_URL = "http://localhost:8000"


@pytest.fixture
def mobile_page(browser: Browser):
    """Page avec viewport mobile pour afficher la bottom-nav."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    yield page
    context.close()


def test_page_loads_no_js_errors(mobile_page: Page):
    """La page se charge et n'a pas d'erreurs JS critiques."""
    js_errors = []
    mobile_page.on("pageerror", lambda err: js_errors.append(str(err)))

    mobile_page.goto(BASE_URL, wait_until="networkidle", timeout=30000)

    # Verifie que le titre est correct
    assert "PMU" in mobile_page.title()

    # Verifie que les elements cles existent
    assert mobile_page.locator("#app").count() == 1
    assert mobile_page.locator(".bottom-nav").count() == 1
    assert mobile_page.locator("#page-dashboard").count() == 1

    # Pas d'erreurs JS
    assert js_errors == [], f"Erreurs JS detectees: {js_errors}"


def test_dashboard_renders(mobile_page: Page):
    """Le dashboard se charge avec des donnees."""
    js_errors = []
    mobile_page.on("pageerror", lambda err: js_errors.append(str(err)))

    mobile_page.goto(BASE_URL, wait_until="networkidle", timeout=30000)

    # Attendre que le contenu dashboard soit charge (dans la page active)
    mobile_page.wait_for_selector("#page-dashboard.active .stats-row, #page-dashboard.active .empty-state, #page-dashboard.active .section-title", timeout=15000)

    # Le dashboard doit avoir du contenu
    content = mobile_page.locator("#dashboard-content").inner_text()
    assert len(content) > 10, "Dashboard vide"

    # Pas d'erreurs JS
    assert js_errors == [], f"Erreurs JS: {js_errors}"


def test_nav_courses(mobile_page: Page):
    """Navigation vers l'onglet Courses."""
    js_errors = []
    mobile_page.on("pageerror", lambda err: js_errors.append(str(err)))

    mobile_page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    mobile_page.wait_for_selector(".bottom-nav", timeout=10000)

    # Clic sur l'onglet Courses
    mobile_page.click("[data-nav='courses']")
    mobile_page.wait_for_selector("#page-courses.active", timeout=5000)
    # Attendre le contenu de la page courses (hipp-header ou empty-state visible)
    mobile_page.wait_for_selector("#page-courses.active .hipp-header, #page-courses.active .empty-state", timeout=15000)

    assert js_errors == [], f"Erreurs JS: {js_errors}"


def test_nav_bets(mobile_page: Page):
    """Navigation vers l'onglet Mes Paris."""
    js_errors = []
    mobile_page.on("pageerror", lambda err: js_errors.append(str(err)))

    mobile_page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    mobile_page.wait_for_selector(".bottom-nav", timeout=10000)

    # Clic sur l'onglet Mes Paris
    mobile_page.click("[data-nav='bets']")
    mobile_page.wait_for_selector("#page-bets.active", timeout=5000)
    mobile_page.wait_for_selector("#page-bets.active .empty-state, #page-bets.active .stat-card", timeout=5000)

    assert js_errors == [], f"Erreurs JS: {js_errors}"


def test_course_detail(mobile_page: Page):
    """Ouverture du detail d'une course."""
    js_errors = []
    mobile_page.on("pageerror", lambda err: js_errors.append(str(err)))

    mobile_page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    mobile_page.wait_for_selector(".bottom-nav", timeout=10000)

    # Naviguer sur courses
    mobile_page.click("[data-nav='courses']")
    mobile_page.wait_for_selector("#page-courses.active", timeout=5000)
    # Attendre que les courses soient chargees
    mobile_page.wait_for_selector("#page-courses.active .hipp-header", timeout=15000)

    # Cliquer sur la premiere course clickable dans la page courses
    mobile_page.locator("#page-courses .card.clickable").first.click()
    mobile_page.wait_for_selector("#page-course.active", timeout=5000)
    mobile_page.wait_for_selector("#page-course.active .participant-row, #page-course.active .empty-state", timeout=20000)

    assert js_errors == [], f"Erreurs JS: {js_errors}"


def test_alert_badge(mobile_page: Page):
    """Le badge alerte est present."""
    js_errors = []
    mobile_page.on("pageerror", lambda err: js_errors.append(str(err)))

    mobile_page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
    mobile_page.wait_for_selector("#alert-badge", timeout=10000)

    assert js_errors == [], f"Erreurs JS: {js_errors}"
