from playwright.sync_api import sync_playwright
import time
import os

def take_screenshot():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://localhost:5173/")
        
        # Upload resume
        file_input = page.locator("input[type='file']")
        file_input.set_input_files(r"C:\Users\anujr\OneDrive\Desktop\PlacementPilot\backend\tests\fixtures\valid_resume.pdf")
        
        # Fill JD
        jd_input = page.locator("textarea")
        jd_input.fill("Looking for a backend engineer with Python, FastAPI, SQL, and Kubernetes experience.")
        
        # Click Analyze Match
        page.get_by_role("button", name="Analyze Match").click()
        
        # Wait for results to load (wait for the unsupported skills container or supported skills)
        page.wait_for_selector("text=Supported Requirements", timeout=15000)
        time.sleep(2) # Give it a moment to render everything
        
        # Take screenshot
        os.makedirs(r"C:\Users\anujr\OneDrive\Desktop\PlacementPilot\docs\verification\phase6", exist_ok=True)
        page.screenshot(path=r"C:\Users\anujr\OneDrive\Desktop\PlacementPilot\docs\verification\phase6\partial_mismatch.png", full_page=True)
        
        browser.close()
        print("Screenshot saved to docs/verification/phase6/partial_mismatch.png")

if __name__ == "__main__":
    take_screenshot()
