// Run against scripts/demo_request_flow.py only; this records its fake loan.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const origin = 'http://127.0.0.1:5055';
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    // The demo needs no requests to Reddit or other external services.
    await page.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort());
    await page.goto(`${origin}/auth/dev-login-as/demo_lender`);
    const response = await page.request.get(`${origin}/api/requests`);
    const records = await response.json();
    const request = records.find(r => r.borrower === 'demo_borrower' && r.status === 'open');
    assert.ok(request, 'Run a fresh offline demo before this test.');
    const code = request.request_id;

    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await page.goto(`${origin}/record-request/${code}`);
      await page.locator('#nlAutoFillBanner').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#nlBorrower').inputValue(), 'demo_borrower');
      assert.equal(await page.locator('#nlCurrency').inputValue(), 'CAD');
      assert.equal(await page.locator('#nlAmount').inputValue(), '150.00');
      assert.equal(await page.locator('#nlRepayAmount').inputValue(), '180.00');
      assert.equal(await page.locator('#nlAmount').getAttribute('readonly'), '');
      const modal = await page.locator('#newLoanModal .modal').boundingBox();
      assert.ok(modal.x >= 0 && modal.x + modal.width <= viewport.width + 1, 'Modal fits viewport');
      await page.screenshot({ path: path.resolve('data', `request-demo-${viewport.width}.png`) });
    }

    // Changing a looked-up code must not fund a different request with stale fields.
    await page.locator('#nlReqId').fill('notfound');
    await page.locator('#nlFundsSent').check();
    await page.locator('#nlSubmitButton').click();
    assert.match(await page.locator('#newLoanError').innerText(), /Look up this request/);
    await page.locator('#nlReqId').fill(code.slice(4).toLowerCase());
    await page.locator('#nlLookupButton').click();
    await page.locator('#nlAutoFillBanner').waitFor({ state: 'visible' });
    await page.locator('#nlSubmitButton').click();
    assert.match(await page.locator('#newLoanError').innerText(), /funds were sent/);
    await page.locator('#nlFundsSent').check();
    const funded = page.waitForResponse(r => r.url().endsWith(`/api/requests/${code}/fund`));
    await page.locator('#nlSubmitButton').click();
    const fundedResponse = await funded;
    assert.equal(fundedResponse.status(), 200, await fundedResponse.text());
    const result = await fundedResponse.json();
    await page.locator('#newLoanModal').waitFor({ state: 'hidden' });
    await page.getByText(result.paid_id, { exact: false }).first().waitFor();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ desktop: 'passed', mobile: 'passed', paidId: result.paid_id, errors }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
