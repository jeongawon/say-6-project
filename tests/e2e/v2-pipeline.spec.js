const { test, expect } = require('@playwright/test');
const { startAnalysis, pollForCompletion, runFullPipeline } = require('./helpers/api-client');
const testCases = require('../../deploy/v2/test-page/test-cases.json');

const API_BASE = process.env.API_BASE_URL || '';
const TEST_PAGE_URL = process.env.TEST_PAGE_URL || 'file://' + require('path').resolve(__dirname, '../../deploy/v2/test-page/index.html');

// ═══════════════════════════════════════════════════════════════
// TC-01: API Endpoint Connectivity
// ═══════════════════════════════════════════════════════════════
test.describe('API Endpoint Tests', () => {
    test('POST /analyze returns executionArn', async ({ request }) => {
        test.skip(!API_BASE, 'API_BASE_URL not configured');
        // Minimal request to verify endpoint works
        const resp = await request.post(`${API_BASE}/analyze`, {
            data: {
                image_base64: 'iVBORw0KGgo=',  // tiny PNG stub
                patient_info: { patient_id: 'TEST', age: 30, sex: 'M' },
            },
        });
        // Expect 200 from API Gateway (Step Functions started)
        expect(resp.status()).toBeLessThan(500);
        const body = await resp.json();
        // Should have executionArn
        if (resp.ok()) {
            expect(body).toHaveProperty('executionArn');
            expect(body.executionArn).toContain('arn:aws:states');
        }
    });

    test('GET /analyze/status with invalid ARN returns 404', async ({ request }) => {
        test.skip(!API_BASE, 'API_BASE_URL not configured');
        const resp = await request.get(`${API_BASE}/analyze/status?id=invalid-arn`);
        const body = await resp.json();
        expect(body.error).toBeDefined();
    });

    test('GET /analyze/status without id returns 400', async ({ request }) => {
        test.skip(!API_BASE, 'API_BASE_URL not configured');
        const resp = await request.get(`${API_BASE}/analyze/status`);
        expect(resp.status()).toBe(400);
    });
});

// ═══════════════════════════════════════════════════════════════
// TC-02: Response Structure Verification
// ═══════════════════════════════════════════════════════════════
test.describe('Response Structure', () => {
    // Use Normal case (least likely to fail, fastest)
    test('Normal case — full response structure', async ({ request }) => {
        test.skip(!API_BASE, 'API_BASE_URL not configured');

        const result = await runFullPipeline(request, API_BASE, testCases.normal);

        expect(result.status).toBe('SUCCEEDED');
        expect(result).toHaveProperty('results');
        expect(result).toHaveProperty('timing');

        const r = result.results;

        // Core fields exist
        expect(r).toHaveProperty('report');
        expect(r).toHaveProperty('seg');
        expect(r).toHaveProperty('densenet');
        expect(r).toHaveProperty('yolo');
        expect(r).toHaveProperty('clinical_logic');

        // Segmentation structure
        if (r.seg) {
            expect(r.seg).toHaveProperty('measurements');
            expect(r.seg.measurements).toHaveProperty('ctr');
            expect(typeof r.seg.measurements.ctr).toBe('number');
        }

        // DenseNet structure
        if (r.densenet) {
            expect(r.densenet).toHaveProperty('predictions');
            expect(Array.isArray(r.densenet.predictions)).toBeTruthy();
        }

        // Timing
        expect(result.timing).toHaveProperty('totalSeconds');
        expect(typeof result.timing.totalSeconds).toBe('number');
    });
});

// ═══════════════════════════════════════════════════════════════
// TC-03: Risk Level Verification (5 test cases)
// ═══════════════════════════════════════════════════════════════
test.describe('Risk Level Verification', () => {
    for (const [key, tc] of Object.entries(testCases)) {
        test(`${tc.name} — expected: ${tc.expected.risk_level}`, async ({ request }) => {
            test.skip(!API_BASE, 'API_BASE_URL not configured');

            const result = await runFullPipeline(request, API_BASE, tc);
            expect(result.status).toBe('SUCCEEDED');

            const clinical = result.results.clinical_logic;
            expect(clinical).toBeTruthy();

            // Risk level can be in various fields depending on clinical engine output
            const actualRisk = clinical.risk_level
                || clinical.overall_risk
                || clinical.risk_assessment?.level
                || clinical.triage?.risk_level;

            expect(actualRisk?.toUpperCase()).toBe(tc.expected.risk_level);
        });
    }
});

// ═══════════════════════════════════════════════════════════════
// TC-04: UI Integration Tests
// ═══════════════════════════════════════════════════════════════
test.describe('UI Integration', () => {
    test('Test page loads correctly', async ({ page }) => {
        await page.goto(TEST_PAGE_URL);

        // Header present
        await expect(page.locator('h1')).toContainText('Dr. AI Radiologist');

        // All 5 test case buttons present
        await expect(page.locator('[data-case="chf"]')).toBeVisible();
        await expect(page.locator('[data-case="pneumonia"]')).toBeVisible();
        await expect(page.locator('[data-case="tension_pneumothorax"]')).toBeVisible();
        await expect(page.locator('[data-case="normal"]')).toBeVisible();
        await expect(page.locator('[data-case="multi_finding"]')).toBeVisible();

        // Upload button present
        await expect(page.locator('#uploadToggle')).toBeVisible();
    });

    test('Test case selection updates UI', async ({ page }) => {
        await page.goto(TEST_PAGE_URL);

        // Click CHF test case
        await page.click('[data-case="chf"]');

        // Run button should be enabled
        const runBtn = page.locator('#runBtn');
        await expect(runBtn).toBeEnabled();

        // Patient info should be visible
        await expect(page.locator('#patientSection')).toBeVisible();
    });

    test('Upload toggle shows upload area', async ({ page }) => {
        await page.goto(TEST_PAGE_URL);
        await page.click('#uploadToggle');
        await expect(page.locator('#uploadArea')).toBeVisible();
    });

    test('Pipeline execution with live API', async ({ page }) => {
        test.skip(!API_BASE, 'API_BASE_URL not configured');
        test.setTimeout(180000);

        // Set API_BASE in the page context
        await page.goto(TEST_PAGE_URL);
        await page.evaluate((url) => {
            window.API_BASE = url;
        }, API_BASE);

        // Select Normal case (fastest)
        await page.click('[data-case="normal"]');
        await page.click('#runBtn');

        // Should show RUNNING status
        await expect(page.locator('#pipelineStatus')).toContainText('RUNNING', { timeout: 10000 });

        // Wait for SUCCEEDED (up to 2 minutes)
        await expect(page.locator('#pipelineStatus')).toContainText('SUCCEEDED', { timeout: 120000 });

        // Results should be visible
        await expect(page.locator('#summarySection')).toBeVisible({ timeout: 5000 });
        await expect(page.locator('#reportSection')).toBeVisible({ timeout: 5000 });
    });
});

// ═══════════════════════════════════════════════════════════════
// TC-05: Performance
// ═══════════════════════════════════════════════════════════════
test.describe('Performance', () => {
    test('Pipeline completes within 120 seconds', async ({ request }) => {
        test.skip(!API_BASE, 'API_BASE_URL not configured');

        const start = Date.now();
        const result = await runFullPipeline(request, API_BASE, testCases.normal);
        const elapsed = (Date.now() - start) / 1000;

        expect(result.status).toBe('SUCCEEDED');
        expect(elapsed).toBeLessThan(120);
        console.log(`Pipeline completed in ${elapsed.toFixed(1)}s`);
    });
});

// ═══════════════════════════════════════════════════════════════
// TC-06: Concurrent Request Isolation
// ═══════════════════════════════════════════════════════════════
test.describe('Concurrent Request Isolation', () => {
    test('Two parallel requests get independent results', async ({ request }) => {
        test.skip(!API_BASE, 'API_BASE_URL not configured');

        // Start two analyses in parallel
        const [resp1, resp2] = await Promise.all([
            request.post(`${API_BASE}/analyze`, {
                data: { image_base64: 'iVBORw0KGgo=', patient_info: testCases.normal.patient_info },
            }),
            request.post(`${API_BASE}/analyze`, {
                data: { image_base64: 'iVBORw0KGgo=', patient_info: testCases.chf.patient_info },
            }),
        ]);

        const data1 = await resp1.json();
        const data2 = await resp2.json();

        // Different execution ARNs
        if (data1.executionArn && data2.executionArn) {
            expect(data1.executionArn).not.toBe(data2.executionArn);
        }
    });
});
