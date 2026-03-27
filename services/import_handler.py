from services.onboard import handle_onboard
from services.sweep import handle_sweep
from services.update import handle_update


async def route_import(db, data: dict):
    action = data.get("action")
    if action == "onboard":
        return await handle_onboard(db, data)
    elif action == "sweep":
        return await handle_sweep(db, data)
    elif action == "update":
        return await handle_update(db, data)
    else:
        return {"error": f"Unknown action: {action}"}
