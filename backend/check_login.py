import asyncio
from playwright.async_api import async_playwright

async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://testoperations.lab.gl/apps/operationservice/process-list",
                        wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Click the Login trigger (not the h3)
        clicked = await page.evaluate("""
            () => {
                const els = [...document.querySelectorAll('a,button,[role=button]')];
                const btn = els.find(e => e.textContent.trim() === 'Login' && e.tagName !== 'H3');
                if (btn) { btn.click(); return btn.tagName + ' | ' + btn.outerHTML.substring(0,200); }
                return 'not found';
            }
        """)
        print("Clicked:", clicked)
        await asyncio.sleep(1)

        # Dump all inputs and buttons after modal opens
        result = await page.evaluate("""
            () => [...document.querySelectorAll('input,button,[role=button]')].map(e => ({
                tag: e.tagName,
                type: e.type || '',
                text: e.textContent.trim().substring(0, 50),
                placeholder: e.placeholder || '',
                visible: e.offsetParent !== null,
                disabled: e.disabled,
                outerHTML: e.outerHTML.substring(0, 150)
            }))
        """)
        print("After modal open - inputs and buttons:")
        for r in result:
            print(r)

        await browser.close()

asyncio.run(check())
