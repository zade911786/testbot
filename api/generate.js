const { chromium } = require('playwright-core');
const chromiumPack = require('@sparticuz/chromium');

// Configs matching the original Python script
const API_BASE = "https://oai.bestimage.ai";
const PAGE_URL = "https://freeimgen.com/nano-banana-ai/";
const ORIGIN = "https://freeimgen.com";
const ACTION_GENERATE = "40db3a6ababdb69d077bb202d890a7dae1ebb5118a";

const MODELS = [
    { name: "gemini-25-flash-image-best", platform: 45 },
    { name: "gemini-25-flash-image-edit-best", platform: 45 },
    { name: "gpt-image-2-best", platform: 45 },
    { name: "gpt-image-2-edit-best", platform: 45 },
    { name: "flux-schnell-best", platform: 31 },
    { name: "janus-pro-best", platform: 32 }
];

const RATIOS = [
    { w: 16, h: 9 }, // 16:9
    { w: 1, h: 1 },  // 1:1
    { w: 9, h: 16 }, // 9:16
    { w: 4, h: 3 },  // 4:3
    { w: 3, h: 4 }   // 3:4
];

// Helper: Generate random fingerprint
function genFingerprint() {
    return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('');
}

// Helper: Sleep function
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

module.exports = async (req, res) => {
    // Only allow POST requests
    if (req.method !== 'POST') {
        return res.status(45).json({ error: 'Method not allowed. Use POST.' });
    }

    const { prompt, model_idx = 0, ratio_idx = 1 } = req.body;

    if (!prompt) {
        return res.status(400).json({ error: 'Prompt is required' });
    }

    let browser;
    try {
        const fingerprint = genFingerprint();
        const selectedModel = MODELS[model_idx] || MODELS[0];
        const selectedRatio = RATIOS[ratio_idx] || RATIOS[1];

        // ─── STEP 1: AUTO TURNSTILE TOKEN GRABBER ───
        console.log("Launching optimized headless browser...");
        
        browser = await chromium.launch({
            args: chromiumPack.args,
            executablePath: await chromiumPack.executablePath(),
            headless: true,
        });

        const context = await browser.newContext({
            userAgent: "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36"
        });
        const page = await context.newPage();

        let turnstileToken = null;

        // Listen to requests to catch the token
        page.on('request', request => {
            const postData = request.postData();
            if (postData && postData.includes('turnstileToken')) {
                try {
                    const body = JSON.parse(postData);
                    if (Array.isArray(body) && body[0]?.turnstileToken) {
                        turnstileToken = body[0].turnstileToken;
                    }
                } catch (e) {}
            }
        });

        await page.goto(PAGE_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });

        // Wait & Poll DOM for token if request interception missed it
        for (let i = 0; i < 15; i++) {
            if (turnstileToken) break;
            turnstileToken = await page.evaluate(() => {
                const input = document.querySelector('input[name="cf-turnstile-response"]');
                return input ? input.value : null;
            });
            await sleep(1000);
        }

        await browser.close();

        if (!turnstileToken) {
            return res.status(500).json({ error: "Failed to grab Turnstile Token automatically." });
        }

        console.log("Token Grabbed Successfully!");

        // ─── STEP 2: SEND GENERATION REQUEST ───
        const payload = [{
            prompt: prompt.trim(),
            modelName: selectedModel.name,
            platform: selectedModel.platform,
            browserFingerprint: fingerprint,
            width: selectedRatio.w,
            height: selectedRatio.h,
            turnstileToken: turnstileToken
        }];

        const response = await fetch(PAGE_URL, {
            method: 'POST',
            headers: {
                "Content-Type": "text/plain;charset=UTF-8",
                "Next-Action": ACTION_GENERATE,
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36...",
                "Origin": ORIGIN,
                "Referer": PAGE_URL
            },
            body: JSON.stringify(payload)
        });

        const resText = await response.text();
        
        // Extract Job Key using Regex (Match Python logic)
        const keyMatch = resText.match(/"key"\s*:\s*"([^"]+)"/) || resText.match(/"key":"([^"]+)"/);
        if (!keyMatch) {
            return res.status(500).json({ error: "Could not extract job key from server response.", debug: resText.slice(0, 500) });
        }
        const jobKey = keyMatch[1];

        // ─── STEP 3: POLL FOR RESULT ───
        const pollUrl = `${API_BASE}/image/getResult/free/${jobKey}`;
        let imageUrl = null;
        
        for (let attempt = 0; attempt < 30; attempt++) {
            await sleep(3000); // Poll every 3 seconds
            const pollResp = await fetch(pollUrl);
            const pollData = await pollResp.json();

            if (pollData.code === 200 && pollData.data) {
                const status = pollData.data.status;
                if (status === 'success') {
                    imageUrl = pollData.data.imageResponseVo?.url;
                    break;
                } else if (status === 'failed') {
                    return res.status(500).json({ error: "Generation failed on freeimgen server." });
                }
            }
        }

        if (imageUrl) {
            return res.status(200).json({
                success: true,
                model: selectedModel.name,
                url: imageUrl
            });
        } else {
            return res.status(504).json({ error: "Polling timed out. Image generation took too long." });
        }

    } catch (error) {
        if (browser) await browser.close();
        return res.status(500).json({ error: error.message });
    }
};
