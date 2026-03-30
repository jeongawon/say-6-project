// @ts-check
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
    testDir: '.',
    timeout: 180000,  // 3 minutes (ML pipeline can be slow)
    expect: {
        timeout: 120000,  // 2 minutes for expect assertions
    },
    retries: 1,
    reporter: [['html', { open: 'never' }], ['list']],
    use: {
        baseURL: process.env.API_BASE_URL || 'https://placeholder.execute-api.ap-northeast-2.amazonaws.com/test',
        extraHTTPHeaders: {
            'Content-Type': 'application/json',
        },
        trace: 'on-first-retry',
    },
    projects: [
        {
            name: 'api-tests',
            testMatch: /v2-pipeline\.spec\.js/,
        },
    ],
});
