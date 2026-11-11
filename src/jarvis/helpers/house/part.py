# src/jarvis/helpers/house/part.py
"""R11 Part B's plug-in (docs/plans/r11-free-helpers.md D2): `build(ctx)` returns everything the app
wires for the chores rota, home upkeep, weather, disaster alerts and breach notices.

- tools: `house_tools` (families chore_, maint_, weather_, disaster_, breach_; R1 and R2 only)
- 5-minute clock: `chores_due`, `maint_due`, then `disaster_poll` (when
  `disaster_alerts_enabled`) before `weather_poll` (when `weather_enabled`): the more urgent
  feed reads first, and weather waits a run when SACHET used this run's outside time
- morning tick: `breach_watch` (it also sweeps Part B's old claims)
- privacy: `helpers_house`, `helpers_place`; brief: "house", "outside"; pending: "house"
- No-AI: `phrases.PHRASES`; routes read `services["house"]` (`api/helpers_house.py`)
His place needs the keyring (`alerts_place`); without one, weather, disaster alerts and breach
notices say they are off and chores and upkeep still work. Each outside feed is OFF for him until
he types his district (and breach watching until he says he has subscribed).
"""

from __future__ import annotations

from jarvis.helpers.house.breach import BreachJob
from jarvis.helpers.house.brief import ChoresBrief, HousePending, OutsideBrief
from jarvis.helpers.house.chores import ChoresJob
from jarvis.helpers.house.fetch import Fetcher, HttpFetcher, OutsideSlot
from jarvis.helpers.house.phrases import PHRASES
from jarvis.helpers.house.privacy import house_privacy, place_privacy
from jarvis.helpers.house.sachet import DisasterJob
from jarvis.helpers.house.service import HouseService
from jarvis.helpers.house.store import HouseStore, OutsideStore
from jarvis.helpers.house.tools import house_tools
from jarvis.helpers.house.upkeep import UpkeepJob
from jarvis.helpers.house.weather import WeatherJob
from jarvis.helpers.ports import HelperContext, HelperPart
from jarvis.ticks import TickJob

READY_ON = (
    "Chores and upkeep on; weather, disaster alerts and breach notices start once you type your "
    "district"
)
READY_NO_KEY = "Chores and upkeep on; weather and alerts off: this server has no token key"


def build(ctx: HelperContext, fetcher: Fetcher | None = None) -> HelperPart:
    store = HouseStore(ctx.docs, prefix=ctx.prefix)
    outside = OutsideStore(ctx.docs, ctx.keyring, prefix=ctx.prefix)
    svc = HouseService(ctx, store, outside)
    fetch = fetcher or HttpFetcher()
    slot = OutsideSlot()
    clock: list[TickJob] = [ChoresJob(ctx, store), UpkeepJob(ctx, store)]
    if ctx.settings.disaster_alerts_enabled:
        clock.append(DisasterJob(ctx, outside, store, fetch, slot=slot))
    if ctx.settings.weather_enabled:
        clock.append(WeatherJob(ctx, outside, store, fetch, slot=slot))
    return HelperPart(
        name="house",
        tools=house_tools(svc),
        clock_jobs=tuple(clock),
        daily_jobs=(BreachJob(ctx, outside, store),),
        privacy=(house_privacy(store), place_privacy(outside, store)),
        brief=(ChoresBrief(svc), OutsideBrief(svc)),
        pending=(HousePending(svc),),
        phrases=PHRASES,
        services={"house": svc},
        ready=READY_ON if outside.available else READY_NO_KEY,
    )


__all__ = ["READY_NO_KEY", "READY_ON", "build"]
