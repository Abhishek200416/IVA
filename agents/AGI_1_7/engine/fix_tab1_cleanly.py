import urllib.request
import json
import time

# 1. Create a clean Bank Nifty tab
req = urllib.request.Request("http://127.0.0.1:9229/json/new?https://www.paytmmoney.com/stocks/fno/option-chain/2000000023/BANKNIFTY/NSE", method="PUT")
resp = urllib.request.urlopen(req)
new_tab = json.loads(resp.read().decode('utf-8'))
print(f"Created clean Bank Nifty tab: {new_tab['id']}")

# 2. Close the stale cycling tab FF12786D98EEF9B0F6EB233E2EE01272
try:
    close_req = urllib.request.urlopen("http://127.0.0.1:9229/json/close/FF12786D98EEF9B0F6EB233E2EE01272")
    print("Closed stale cycling tab FF12786D98EEF9B0F6EB233E2EE01272")
except Exception as e:
    print(f"Close error: {e}")

time.sleep(3)

# 3. Check current open tabs
tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9229/json").read())
print("Active tabs:")
for t in tabs:
    if "paytm" in t.get("url", "") or "8088" in t.get("url", ""):
        print(f" - [{t.get('id')}] {t.get('title')} -> {t.get('url')}")
