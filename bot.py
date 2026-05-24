#!/usr/bin/env python3
import os
import re
import json
import time
import sys
import random
import pathlib
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests

# ─── AUTOMATIC PLAYWRIGHT BROWSER INSTALLER ───────────────────────────────────
# This forces the hosting platform to download the missing headless binaries on boot.
print("📦 Checking Playwright browser dependencies...")
try:
    import playwright
    # Execute the command programmatically within the server environment
    os.system(f"{sys.executable} -m playwright install chromium")
    print("✅ Playwright browser installation check complete.")
except Exception as e:
    print(f"⚠️ Automatic browser installation warning: {e}")
# ──────────────────────────────────────────────────────────────────────────────

# ─── Config From Original Script ──────────────────────────────────────────────
MODELS = [
    {"name": "gemini-25-flash-image-best",      "platform": 45, "label": "Gemini 2.5 Flash (Text→Img)", "type": "text"},
    {"name": "gemini-25-flash-image-edit-best",  "platform": 45, "label": "Gemini 2.5 Flash (Edit)",     "type": "edit"},
    {"name": "gpt-image-2-best",                "platform": 45, "label": "GPT Image 2 (Text→Img)",      "type": "text"},
    {"name": "gpt-image-2-edit-best",           "platform": 45, "label": "GPT Image 2 (Edit)",          "type": "edit"},
    {"name": "flux-schnell-best",               "platform": 31, "label": "Flux Schnell",                 "type": "text"},
    {"name": "janus-pro-best",                  "platform": 32, "label": "Janus Pro",                    "type": "text"},
]

API_BASE = "https://oai.bestimage.ai"
PAGE_URL = "https://freeimgen.com/nano-banana-ai/"
ORIGIN   = "https://freeimgen.com"
ACTION_GENERATE = "40db3a6ababdb69d077bb202d890a7dae1ebb5118a"
OUTPUT_DIR = pathlib.Path("generated_images")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TOKEN = "8632040165:AAFd0mBYQop7cI5Q6Z8dM0-2acoD48VNkhQ"

# ─── Helpers From Original Script ─────────────────────────────────────────────
def gen_fingerprint():
    return "".join(random.choices("0123456789abcdef", k=32))

def get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
        "Accept": "text/x-component",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Origin": ORIGIN,
        "Referer": PAGE_URL,
        "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    })
    return s

def call_server_action(session, action_id, body):
    headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Next-Action": action_id,
    }
    payload = json.dumps([body])
    resp = session.post(PAGE_URL, data=payload, headers=headers, timeout=60)
    return resp

def poll_result(session, key, max_wait=180):
    url = f"{API_BASE}/image/getResult/free/{key}"
    start = time.time()
    attempt = 0
    while time.time() - start < max_wait:
        attempt += 1
        try:
            resp = session.get(url, timeout=30)
            data = resp.json()
            if data.get("code") == 200 and data.get("data"):
                result = data["data"]
                status = result.get("status", "")
                if status == "success":
                    img_url = result.get("imageResponseVo", {}).get("url")
                    if img_url:
                        return {"status": "success", "url": img_url}
                elif status == "failed":
                    return {"status": "failed", "error": "Generation failed on server"}
            elif data.get("code") == 500:
                return {"status": "failed", "error": data.get("msg", "Server error")}
        except Exception:
            pass
        
        if attempt <= 5:
            wait = 2
        elif attempt <= 15:
            wait = 5
        else:
            wait = 8
        time.sleep(wait)
    return {"status": "timeout", "error": f"Timed out after {max_wait}s"}

# ─── UNIVERSAL ASYNC PLAYWRIGHT TOKEN CAPTURE ──────────────────────────────────
async def capture_token_playwright_async():
    from playwright.async_api import async_playwright
    import asyncio
    
    print("🌐 Launching standard headless browser for Turnstile verification...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
        )
        page = await context.new_page()
        
        token_holder = {"token": None}
        
        async def on_request(request):
            if "turnstileToken" in (request.post_data or ""):
                try:
                    body = json.loads(request.post_data)
                    if isinstance(body, list) and len(body) > 0:
                        t = body[0].get("turnstileToken")
                        if t:
                            token_holder["token"] = t
                except:
                    pass
        
        async def on_response(response):
            req = response.request
            if "turnstileToken" in (req.post_data or ""):
                try:
                    body = json.loads(req.post_data)
                    if isinstance(body, list) and len(body) > 0:
                        t = body[0].get("turnstileToken")
                        if t:
                            token_holder["token"] = t
                except:
                    pass
        
        page.on("request", on_request)
        page.on("response", on_response)
        
        await page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=30000)
        
        print("⏳ Waiting for Turnstile verification...")
        for i in range(60):
            if token_holder["token"]:
                break
            
            try:
                token = await page.evaluate("""() => {
                    const input = document.querySelector('input[name="cf-turnstile-response"]');
                    if (input && input.value) return input.value;
                    if (window.turnstile) {
                        const widgets = document.querySelectorAll('.cf-turnstile');
                        for (const w of widgets) {
                            const resp = window.turnstile.getResponse(w);
                            if (resp) return resp;
                        }
                    }
                    return null;
                }""")
                if token:
                    token_holder["token"] = token
                    break
            except:
                pass
            
            await asyncio.sleep(1)
        
        await browser.close()
        
        if token_holder["token"]:
            print("\n✅ Turnstile token captured!")
            return token_holder["token"]
        else:
            print("\n❌ Failed to capture Turnstile token automatically.")
            return None

# ─── Core Generation Runner ───────────────────────────────────────────────────
def generate_image_core(prompt, turnstile_token, model_idx=0):
    model = MODELS[model_idx]
    fingerprint = gen_fingerprint()
    session = get_session()
    
    body = {
        "prompt": prompt.strip(),
        "modelName": model["name"],
        "platform": model["platform"],
        "browserFingerprint": fingerprint,
        "width": 1,
        "height": 1,
        "turnstileToken": turnstile_token
    }
    
    resp = call_server_action(session, ACTION_GENERATE, body)
    if resp.status_code != 200:
        return False, f"Generation request failed: HTTP {resp.status_code}"
    
    job_key = None
    for m in re.finditer(r'"key"\s*:\s*"([^"]+)"', resp.text):
        job_key = m.group(1)
        break
        
    if not job_key:
        return False, "Could not extract job key from response."
    
    result = poll_result(session, job_key)
    if result["status"] == "success":
        img_url = result["url"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"img_{timestamp}_{model['name']}.jpg"
        
        img_resp = session.get(img_url, timeout=60)
        img_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(img_resp.content)
            
        return True, str(output_path)
    else:
        return False, result.get("error", "Generation timed out or failed.")

# ─── Telegram Bot Handlers ────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 **Welcome to FreeImgen Auto-Bot!**\n\n"
        "Just give me a prompt, and I will spin up a headless browser instance to automatically bypass the Turnstile challenge and render your asset!\n\n"
        "**Usage:**\n"
        "`/generate a futuristic cybernetic city skyline`"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("❌ Please provide a prompt. Example:\n`/generate cyber cat`")
        return

    status_message = await update.message.reply_text("⏳ Spawning headless browser environment to resolve Turnstile Captcha...")

    try:
        token = await capture_token_playwright_async()
    except Exception as e:
        await status_message.edit_text(f"❌ Playwright runtime exception: `{str(e)}`")
        return

    if not token:
        await status_message.edit_text("❌ Headless execution timed out while tracking the Turnstile frame token.")
        return

    await status_message.edit_text("🚀 Token acquired successfully! Dispatching generation packet to API...")
    
    success, file_or_error = generate_image_core(prompt, token, model_idx=0)

    if success:
        await status_message.edit_text("⬇️ Asset processing completed. Uploading image stream...")
        with open(file_or_error, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption=f"✨ **Prompt:** {prompt}", parse_mode="Markdown")
        try:
            os.remove(file_or_error)
        except OSError:
            pass
    else:
        await status_message.edit_text(f"❌ **API Error:**\n`{file_or_error}`", parse_mode="Markdown")

# ─── Main Lifecycle ───────────────────────────────────────────────────────────
def main():
    print("🤖 Launching bot daemon...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("generate", generate_command))

    print("⚡ Bot polling initialized.")
    app.run_polling()

if __name__ == "__main__":
    main()
