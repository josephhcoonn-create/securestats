"""Quick smoke test for MLBClient against the live API."""
import asyncio
import logging
import selectors
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def main() -> None:
    from app.services.mlb_client import MLBClient

    async with MLBClient() as mlb:
        # 1 — Today's schedule
        games = await mlb.get_todays_schedule()
        print(f"\n[Schedule] {len(games)} game(s) today")
        if games:
            g = games[0]
            print(f"  {g['away_team']} @ {g['home_team']}  status={g['status']}  id={g['game_id']}")

        # 2 — Boxscore from first available game
        if games:
            stats = await mlb.get_game_boxscore(games[0]["game_id"])
            print(f"\n[Boxscore] game {games[0]['game_id']}: {len(stats)} batting lines")
            if stats:
                s = stats[0]
                print(f"  {s['player_name']} ({s['team']})  AB={s['at_bats']}  H={s['hits']}  HR={s['home_runs']}")
        else:
            print("\n[Boxscore] skipped — no games today")

        # 3 — Single player (Aaron Judge mlb_id=592450)
        player = await mlb.get_player(592450)
        if player:
            print(f"\n[Player] {player['full_name']} | {player['team']} | pos={player['position']}")

        # 4 — Yankees roster (team_id=147)
        roster = await mlb.get_team_roster(147)
        print(f"\n[Roster] Yankees: {len(roster)} players")
        if roster:
            r = roster[0]
            print(f"  {r['full_name']}  #{r['jersey_number']}  {r['position']}  status={r['status']}")

        # 5 — Standings
        standings = await mlb.get_standings()
        print(f"\n[Standings] {len(standings)} teams returned")
        if standings:
            leader = max(standings, key=lambda t: t["wins"])
            print(f"  Most wins: {leader['team_name']} ({leader['wins']}-{leader['losses']})")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            main(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(main())
