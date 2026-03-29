"""
Australia Post Tracking API integration.
Checks shipped AusPost orders and marks them as delivered.
"""
import urllib.request
import urllib.parse
import json
import database

AUSPOST_API_URL = "https://digitalapi.auspost.com.au/shipping/v1/track"
AUSPOST_CARRIERS = {"Australia Post", "StarTrack"}


def check_tracking(api_key, tracking_ids):
    """
    Query AusPost tracking API for up to 10 IDs at a time.
    Returns dict of {tracking_id: status_string}.
    """
    if not api_key or not tracking_ids:
        return {}

    results = {}
    # API supports up to 10 IDs per request
    for i in range(0, len(tracking_ids), 10):
        batch = tracking_ids[i:i + 10]
        params = urllib.parse.urlencode({"tracking_ids": ",".join(batch)})
        url = f"{AUSPOST_API_URL}?{params}"
        req = urllib.request.Request(url, headers={"AUTH-KEY": api_key})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            for result in data.get("tracking_results", []):
                tid = result.get("tracking_id", "")
                # Status lives at top level or inside trackSummary
                status = (
                    result.get("status")
                    or result.get("trackSummary", {}).get("status")
                    or ""
                )
                if tid:
                    results[tid] = status
        except Exception as e:
            print(f"[AusPost API] error for batch {batch}: {e}")

    return results


def run_delivery_check(cfg):
    """
    Check all shipped AusPost orders and mark delivered ones.
    Returns count of orders marked delivered.
    """
    api_key = cfg.get("auspost", {}).get("api_key", "")
    if not api_key:
        return 0

    orders = database.get_orders(status="shipped")
    eligible = [
        o for o in orders
        if o.get("carrier") in AUSPOST_CARRIERS and o.get("tracking_number")
    ]
    if not eligible:
        return 0

    tracking_map = {o["tracking_number"]: o for o in eligible}
    statuses = check_tracking(api_key, list(tracking_map.keys()))

    count = 0
    for tracking_id, status in statuses.items():
        if "delivered" in status.lower():
            order = tracking_map.get(tracking_id)
            if order:
                database.update_order(order["id"], {"status": "delivered"})
                print(f"[AusPost] Order #{order.get('order_number')} marked delivered "
                      f"(tracking: {tracking_id})")
                count += 1

    return count
