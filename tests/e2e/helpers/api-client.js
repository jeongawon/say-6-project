/**
 * Async Polling API Client for Dr. AI Radiologist v2
 */

const POLL_INTERVAL = 3000;  // 3 seconds
const MAX_POLL_TIME = 180000;  // 3 minutes

/**
 * Start pipeline analysis
 */
async function startAnalysis(request, apiBase, payload) {
    const response = await request.post(`${apiBase}/analyze`, { data: payload });
    return response;
}

/**
 * Poll for execution completion
 */
async function pollForCompletion(request, apiBase, executionArn) {
    const startTime = Date.now();

    while (Date.now() - startTime < MAX_POLL_TIME) {
        const response = await request.get(
            `${apiBase}/analyze/status?id=${encodeURIComponent(executionArn)}`
        );
        const data = await response.json();

        if (data.status === 'SUCCEEDED') return data;
        if (data.status === 'FAILED') throw new Error(`Pipeline failed: ${data.error}`);
        if (data.status === 'TIMED_OUT') throw new Error('Pipeline timed out');
        if (data.status === 'ABORTED') throw new Error('Pipeline aborted');

        await new Promise(r => setTimeout(r, POLL_INTERVAL));
    }

    throw new Error(`Polling timed out after ${MAX_POLL_TIME / 1000}s`);
}

/**
 * Run full pipeline: start + poll until complete
 */
async function runFullPipeline(request, apiBase, testCase) {
    const payload = {
        image_base64: testCase._test_image_base64 || 'placeholder',
        patient_info: testCase.patient_info,
    };

    const startResp = await startAnalysis(request, apiBase, payload);
    const startData = await startResp.json();

    if (!startData.executionArn) {
        throw new Error('No executionArn in response');
    }

    return await pollForCompletion(request, apiBase, startData.executionArn);
}

module.exports = { startAnalysis, pollForCompletion, runFullPipeline, POLL_INTERVAL, MAX_POLL_TIME };
