import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import achievements, agent, analytics, assistant, auth, backtest, briefing, calendar, coach, config, custom, daily, db, dna, fit, fx, ingest, lab, learn, live, news, paper, planner, practice, prefs, prices, prop, record, review, risk, scenarios, sessions, stayorbail, trades, twin

log = logging.getLogger("api")


async def _price_updater():
    """Refresh the core markets and those in use every UPDATE_INTERVAL_MIN minutes (counted from the start
    of each run, so a long run doesn't stretch the gap between updates)."""
    loop = asyncio.get_running_loop()
    while True:
        t0 = loop.time()
        try:
            n = await asyncio.to_thread(ingest.update_all, config.PRICE_SOURCE)
            log.info("price update stored %d bars in %.0fs", n, loop.time() - t0)
        except Exception:
            log.exception("price update failed")
        await asyncio.sleep(max(60.0, config.UPDATE_INTERVAL_MIN * 60 - (loop.time() - t0)))


async def _history_filler():
    """Slow work kept off the price updates: once per start, find catalog markets the feed doesn't carry;
    then keep filling in the older history of markets that have only their recent prices so far."""
    await asyncio.sleep(60)  # let the first price update go first
    try:
        await asyncio.to_thread(ingest.probe, config.PRICE_SOURCE)
    except Exception:
        log.exception("market probe failed")
    while True:
        try:
            n = await asyncio.to_thread(ingest.extend_all, config.PRICE_SOURCE)
            if n:
                log.info("history filler stored %d older hourly bars", n)
        except Exception:
            log.exception("history filler failed")
        await asyncio.sleep(120)


async def _news_updater():
    while True:
        try:
            added, tagged = await asyncio.to_thread(news.update)
            events = await asyncio.to_thread(calendar.update)
            log.info("news update: %d new, %d tagged; calendar: %d events", added, tagged, events)
        except Exception:
            log.exception("news update failed")
        await asyncio.sleep(config.NEWS_INTERVAL_MIN * 60)


async def _agent_runner():
    while True:
        try:
            n = await asyncio.to_thread(agent.step_all)
            if n:
                log.info("strategy agents traded %d times", n)
        except Exception:
            log.exception("agent run failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    ingest.load_monthly_history()
    calendar.seed_fomc()
    ingest.clear_old_unavailable_marks()
    tasks = ([asyncio.create_task(_price_updater()), asyncio.create_task(_history_filler()),
              asyncio.create_task(_news_updater()),
              asyncio.create_task(_agent_runner())] if config.ENABLE_SCHEDULER else [])
    if config.ENABLE_SCHEDULER and config.LIVE_PRICES and config.FINNHUB_API_KEY and config.PRICE_SOURCE != "sample":
        tasks.append(asyncio.create_task(live.run()))
    yield
    for task in tasks:
        task.cancel()
    db.close()


app = FastAPI(title="Trading Lab API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(prices.router)
app.include_router(live.router)
app.include_router(backtest.router)
app.include_router(custom.router)
app.include_router(trades.router)
app.include_router(news.router)
app.include_router(calendar.router)
app.include_router(risk.router)
app.include_router(stayorbail.router)
app.include_router(fit.router)
app.include_router(planner.router)
app.include_router(scenarios.router)
app.include_router(paper.router)
app.include_router(dna.router)  # before prop: its /prop/{cid} would catch /prop/dna
app.include_router(prop.router)
app.include_router(record.router)
app.include_router(agent.router)
app.include_router(assistant.router)
app.include_router(briefing.router)
app.include_router(achievements.router)
app.include_router(lab.router)
app.include_router(practice.router)
app.include_router(sessions.router)
app.include_router(review.router)
app.include_router(coach.router)
app.include_router(learn.router)
app.include_router(prefs.router)
app.include_router(fx.router)
app.include_router(daily.router)
app.include_router(analytics.router)
app.include_router(twin.router)


@app.get("/health")
def health():
    with db.conn() as c:
        c.execute("SELECT 1")
    return {"ok": True}
